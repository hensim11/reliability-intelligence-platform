import json
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from reliability_intelligence.cli import main
from reliability_intelligence.experiment import (
    ExperimentConfig,
    assign_rows,
    run_configs,
    verify_experiment,
)
from reliability_intelligence.features import FEATURE_NAMES
from reliability_intelligence.models import ForecastModel, load_model
from reliability_intelligence.simulation.engine import simulate
from reliability_intelligence.storage import file_hash


def small_config():
    raw = json.loads(Path("configs/batch_b.json").read_text())
    raw["simulation"].update(duration_minutes=1440, incidents_per_service=12)
    raw.update(
        development_seeds=[101],
        heldout_seeds=[404],
        regime_seeds=[606],
        boundaries_minutes=[0, 720, 960, 1200, 1440],
    )
    return ExperimentConfig(**raw)


@pytest.mark.parametrize(
    "change",
    [
        {"heldout_seeds": [101]},
        {"regime_seeds": []},
        {"development_seeds": [True]},
        {"boundaries_minutes": [0, 700, 600, 1200, 1440]},
        {"boundaries_minutes": [0, 20, 960, 1200, 1440]},
        {"false_alert_budget": -1},
        {"false_alert_budget": float("nan")},
        {"model_seed": True},
    ],
)
def test_invalid_configuration(change):
    with pytest.raises(ValueError):
        replace(small_config(), **change)


def test_unknown_config_fields_and_subminute_rejected(tmp_path):
    raw = small_config().resolved()
    raw["target_as_feature"] = True
    path = tmp_path / "invalid.json"
    path.write_text(json.dumps(raw))
    with pytest.raises(TypeError):
        ExperimentConfig.load(path)
    raw.pop("target_as_feature")
    raw["simulation"]["interval_seconds"] = 30
    with pytest.raises(ValueError, match="one-minute"):
        ExperimentConfig(**raw)


def test_regime_reproducibility_and_split_windows():
    config = small_config()
    runs = list(run_configs(config))
    assert runs == list(run_configs(config))
    assert runs[-1][2].incidents is not None
    assert len({event.precursor_minutes for event in runs[-1][2].incidents}) > 1
    _, group, simulation = runs[0]
    rows = assign_rows(simulate(simulation), simulation, group, config)
    origin = pd.Timestamp(simulation.start)
    for stage, begin, end in zip(
        ["train", "calibration", "validation", "temporal_test"],
        config.boundaries_minutes[:-1],
        config.boundaries_minutes[1:],
        strict=True,
    ):
        subset = rows.loc[rows.partition == stage]
        assert len(subset)
        assert (
            subset.timestamp - pd.Timedelta(minutes=15) >= origin + pd.Timedelta(minutes=begin)
        ).all()
        assert (
            subset.timestamp + pd.Timedelta(minutes=10) < origin + pd.Timedelta(minutes=end)
        ).all()


def test_cli_roundtrip_freeze_order_and_evidence(tmp_path, monkeypatch):
    from reliability_intelligence import experiment

    config = small_config()
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(config.resolved()))
    output, corpus, evidence = tmp_path / "experiment", tmp_path / "corpus", tmp_path / "evidence"
    _, group, simulation = next(run_configs(config))
    assigned = assign_rows(simulate(simulation), simulation, group, config)
    validation_indices = set(assigned.index[assigned.partition == "validation"])
    saved = []
    original_save = experiment.save_model
    original_predict = ForecastModel.predict

    def audited_save(model, path):
        selection = json.loads((path.parent / "selection.json").read_text())
        assert len(selection["candidate_thresholds"]) == 5
        saved.append(path)
        original_save(model, path)

    def audited_predict(model, features):
        if not set(features.index).issubset(validation_indices):
            assert len(saved) == 5, "Test/holdout prediction occurred before choices were persisted"
        return original_predict(model, features)

    monkeypatch.setattr(experiment, "save_model", audited_save)
    monkeypatch.setattr(ForecastModel, "predict", audited_predict)
    args = [
        "batch-b",
        "--config",
        str(config_path),
        "--corpus",
        str(corpus),
        "--output",
        str(output),
        "--evidence",
        str(evidence),
    ]
    assert main(args) == 0
    monkeypatch.setattr(ForecastModel, "predict", original_predict)
    verify_experiment(output)
    verify_experiment(evidence)
    assert len(list(evidence.glob("*.png"))) == 5
    assert (evidence / "REPORT.md").is_file()
    predictions = pd.read_parquet(output / "predictions.parquet")
    assert set(predictions.partition) == {
        "validation",
        "temporal_test",
        "heldout_seed",
        "heldout_regime",
    }
    selected = json.loads((output / "selection.json").read_text())["candidate"]
    validation = assigned.loc[assigned.partition == "validation"]
    model = load_model(output / f"{selected}.joblib")
    actual = predictions.loc[
        (predictions.partition == "validation") & (predictions.candidate == selected)
    ]
    np.testing.assert_array_equal(
        model.predict(validation[list(FEATURE_NAMES)]), actual.probability
    )
    assert main(args) == 1  # immutable experiment and evidence
    repeated = tmp_path / "repeated"
    assert main(["batch-b-evidence", "--experiment", str(output), "--output", str(repeated)]) == 0
    for path in evidence.iterdir():
        assert file_hash(path) == file_hash(repeated / path.name)
    (output / "metrics.csv").write_text("tampered")
    assert (
        main(["batch-b-evidence", "--experiment", str(output), "--output", str(tmp_path / "bad")])
        == 1
    )
    assert not (tmp_path / "bad").exists()
