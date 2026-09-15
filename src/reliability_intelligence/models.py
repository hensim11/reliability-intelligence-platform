"""Training-stage isolation and a versioned, strict persisted inference interface."""

import importlib.metadata
import json
from dataclasses import dataclass
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.dummy import DummyClassifier
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from threadpoolctl import threadpool_limits

from reliability_intelligence.features import FEATURE_NAMES, FEATURE_VERSION, TARGET, feature_matrix
from reliability_intelligence.storage import file_hash


def stage_rows(rows: pd.DataFrame, expected: str) -> tuple[pd.DataFrame, np.ndarray]:
    if rows.empty or set(rows.partition) != {expected}:
        raise ValueError(f"Only nonempty {expected} rows are permitted")
    allowed = {*FEATURE_NAMES, TARGET, "partition", "timestamp", "service_id", "run_id"}
    if set(rows.columns) - allowed:
        raise ValueError("Unexpected columns in modelling table")
    x = feature_matrix(rows[list(FEATURE_NAMES)])
    if rows[TARGET].isna().any() or not rows[TARGET].isin([0, 1]).all():
        raise ValueError("Stage targets must be observed binary values")
    y = rows[TARGET].to_numpy(dtype=int)
    if set(np.unique(y)) != {0, 1}:
        raise ValueError(f"{expected} requires both classes")
    return x, y


def logits(probability):
    p = np.clip(probability, 1e-8, 1 - 1e-8)
    return np.log(p / (1 - p)).reshape(-1, 1)


@dataclass
class ForecastModel:
    name: str
    pipeline: object
    calibrator: object | None = None

    def predict(self, features: pd.DataFrame) -> np.ndarray:
        x = feature_matrix(features)
        with threadpool_limits(limits=1):
            p = self.pipeline.predict_proba(x)[:, 1]
            if self.calibrator is not None:
                p = self.calibrator.predict_proba(logits(p))[:, 1]
        return p


def fit_candidates(training: pd.DataFrame, calibration: pd.DataFrame, seed: int) -> dict:
    x, y = stage_rows(training, "train")
    cx, cy = stage_rows(calibration, "calibration")
    if min(np.bincount(cy)) < 20:
        raise ValueError("Sigmoid calibration requires at least 20 rows in each class")
    estimators = {
        "prevalence": make_pipeline(DummyClassifier(strategy="prior")),
        "logistic": make_pipeline(
            StandardScaler(), LogisticRegression(C=1.0, max_iter=2000, random_state=seed)
        ),
        "boosting": make_pipeline(
            HistGradientBoostingClassifier(
                max_iter=100,
                max_leaf_nodes=15,
                min_samples_leaf=30,
                l2_regularization=1.0,
                learning_rate=0.1,
                early_stopping=False,
                random_state=seed,
            )
        ),
    }
    models = {}
    with threadpool_limits(limits=1):
        for name, estimator in estimators.items():
            estimator.fit(x, y)
            models[name + "_raw"] = ForecastModel(name + "_raw", estimator)
            if name != "prevalence":
                calibrator = LogisticRegression(C=1e6, max_iter=1000, random_state=seed)
                calibrator.fit(logits(estimator.predict_proba(cx)[:, 1]), cy)
                if calibrator.coef_[0, 0] <= 0:
                    raise ValueError("Calibration reversed ranking; experiment is not usable")
                models[name + "_sigmoid"] = ForecastModel(name + "_sigmoid", estimator, calibrator)
    return models


def choose_model(validation: pd.DataFrame, models: dict) -> tuple[str, pd.DataFrame]:
    from reliability_intelligence.evaluation import row_metrics

    x, y = stage_rows(validation, "validation")
    rows = [
        {"candidate": name, **row_metrics(y, model.predict(x))} for name, model in models.items()
    ]
    table = pd.DataFrame(rows)
    # Choose family by raw AP; calibration is a separate probability-quality decision.
    raw = table.loc[table.candidate.str.endswith("_raw")].sort_values(
        ["average_precision", "log_loss", "candidate"], ascending=[False, True, True]
    )
    selected = str(raw.iloc[0].candidate)
    alternative = selected.removesuffix("_raw") + "_sigmoid"
    if alternative in models:
        a = table.set_index("candidate").loc[alternative]
        b = table.set_index("candidate").loc[selected]
        if a.brier < b.brier and a.log_loss < b.log_loss:
            selected = alternative
    return selected, table


def save_model(model: ForecastModel, path: Path) -> None:
    if path.exists() or path.with_suffix(".json").exists():
        raise FileExistsError("Model artefact already exists")
    joblib.dump(model, path)
    path.with_suffix(".json").write_text(
        json.dumps(
            {
                "feature_version": FEATURE_VERSION,
                "features": FEATURE_NAMES,
                "dtype": "float64",
                "sklearn_version": importlib.metadata.version("scikit-learn"),
                "sha256": file_hash(path),
                "name": model.name,
            },
            indent=2,
        )
        + "\n"
    )


def load_model(path: Path) -> ForecastModel:
    """Load trusted local artefacts only: joblib/pickle is executable Python data."""
    metadata = json.loads(path.with_suffix(".json").read_text())
    if (
        metadata["feature_version"] != FEATURE_VERSION
        or tuple(metadata["features"]) != FEATURE_NAMES
        or metadata["dtype"] != "float64"
        or metadata["sklearn_version"] != importlib.metadata.version("scikit-learn")
    ):
        raise ValueError("Incompatible model or feature version")
    if file_hash(path) != metadata["sha256"]:
        raise ValueError("Model integrity check failed")
    model = joblib.load(path)
    if not isinstance(model, ForecastModel) or model.name != metadata["name"]:
        raise ValueError("Unsupported model artefact")
    return model
