import json

import numpy as np
import pandas as pd
import pytest

from reliability_intelligence.features import FEATURE_NAMES, TARGET
from reliability_intelligence.models import choose_model, fit_candidates, load_model, save_model


def modelling_rows(seed, partition):
    rng = np.random.default_rng(seed)
    x = rng.normal(size=(160, len(FEATURE_NAMES)))
    frame = pd.DataFrame(x, columns=FEATURE_NAMES)
    frame[TARGET] = (x[:, 0] + x[:, 1] > 0).astype(int)
    frame["partition"] = partition
    return frame


@pytest.fixture(scope="module")
def fitted():
    training = modelling_rows(1, "train")
    calibration = modelling_rows(2, "calibration")
    return training, calibration, fit_candidates(training, calibration, 2026)


def test_preprocessing_training_only_and_calibration_isolation(fitted):
    train, calibration, models = fitted
    scaler = models["logistic_raw"].pipeline[0]
    np.testing.assert_allclose(scaler.mean_, train[list(FEATURE_NAMES)].mean())
    altered = calibration.copy()
    altered[list(FEATURE_NAMES)] += 0.2
    second = fit_candidates(train, altered, 2026)
    x = train[list(FEATURE_NAMES)]
    for name in ["prevalence_raw", "logistic_raw", "boosting_raw"]:
        np.testing.assert_array_equal(models[name].predict(x), second[name].predict(x))
    assert not np.array_equal(
        models["logistic_sigmoid"].predict(x), second["logistic_sigmoid"].predict(x)
    )


def test_deterministic_training_and_roundtrip(fitted, tmp_path):
    train, calibration, models = fitted
    second = fit_candidates(train, calibration, 2026)
    x = train[list(FEATURE_NAMES)]
    for name, model in models.items():
        np.testing.assert_array_equal(model.predict(x), second[name].predict(x))
        path = tmp_path / f"{name}.joblib"
        save_model(model, path)
        np.testing.assert_array_equal(model.predict(x), load_model(path).predict(x))
        with pytest.raises(FileExistsError):
            save_model(model, path)
    assert models["prevalence_raw"].predict(x)[0] == train[TARGET].mean()
    assert models["boosting_raw"].pipeline[-1].early_stopping is False


@pytest.mark.parametrize("stage", ["validation", "temporal_test", "heldout_seed", "heldout_regime"])
def test_training_calibration_and_selection_reject_wrong_stage(fitted, stage):
    train, calibration, models = fitted
    wrong = modelling_rows(4, stage)
    with pytest.raises(ValueError, match="train"):
        fit_candidates(wrong, calibration, 1)
    with pytest.raises(ValueError, match="calibration"):
        fit_candidates(train, wrong, 1)
    if stage != "validation":
        with pytest.raises(ValueError, match="validation"):
            choose_model(wrong, models)


def test_selection_does_not_refit(fitted):
    train, _, models = fitted
    before = models["logistic_raw"].predict(train[list(FEATURE_NAMES)])
    selected, comparison = choose_model(modelling_rows(3, "validation"), models)
    assert selected in models
    assert len(comparison) == 5
    np.testing.assert_array_equal(
        before, models["logistic_raw"].predict(train[list(FEATURE_NAMES)])
    )


def test_corrupt_and_incompatible_artifact(fitted, tmp_path):
    path = tmp_path / "model.joblib"
    save_model(fitted[2]["logistic_raw"], path)
    metadata = json.loads(path.with_suffix(".json").read_text())
    metadata["feature_version"] = "future"
    path.with_suffix(".json").write_text(json.dumps(metadata))
    with pytest.raises(ValueError, match="Incompatible"):
        load_model(path)
    metadata["feature_version"] = "1.0"
    path.with_suffix(".json").write_text(json.dumps(metadata))
    path.write_bytes(b"corrupt")
    with pytest.raises(ValueError, match="integrity"):
        load_model(path)


def test_insufficient_calibration_and_leaking_modelling_table(fitted):
    train, calibration, _ = fitted
    with pytest.raises(ValueError, match="20 rows"):
        fit_candidates(train, calibration.iloc[:10], 2026)
    with pytest.raises(ValueError, match="Unexpected columns"):
        fit_candidates(train.assign(incident_type="truth"), calibration, 2026)
    invalid = train.copy()
    invalid[TARGET] = 0.5
    with pytest.raises(ValueError, match="binary"):
        fit_candidates(invalid, calibration, 2026)
