"""Immutable, deterministic Batch B corpus and four-stage experiment orchestration."""

import importlib.metadata
import json
import logging
import platform
import shutil
import tempfile
from dataclasses import dataclass, replace
from pathlib import Path

import numpy as np
import pandas as pd

from reliability_intelligence.config import INCIDENT_TYPES, IncidentSpec, SimulationConfig
from reliability_intelligence.evaluation import (
    grouped_uncertainty,
    operational_metrics,
    reliability_table,
    row_metrics,
    select_threshold,
)
from reliability_intelligence.features import (
    FEATURE_NAMES,
    FEATURE_VERSION,
    TARGET,
    attach_targets,
    build_features,
    partition_mask,
)
from reliability_intelligence.models import choose_model, fit_candidates, save_model
from reliability_intelligence.simulation.engine import simulate
from reliability_intelligence.storage import file_hash, read_dataset, write_dataset

LOGGER = logging.getLogger("reliability_intelligence")
STAGES = ("train", "calibration", "validation", "temporal_test")


@dataclass(frozen=True)
class ExperimentConfig:
    simulation: dict
    development_seeds: list[int]
    heldout_seeds: list[int]
    regime_seeds: list[int]
    boundaries_minutes: list[int]
    model_seed: int = 2026
    false_alert_budget: float = 1.0

    def __post_init__(self):
        config = SimulationConfig.from_dict(self.simulation)
        if config.interval_seconds != 60 or config.incidents is not None:
            raise ValueError("Experiments require a one-minute generated simulation schedule")
        groups = [self.development_seeds, self.heldout_seeds, self.regime_seeds]
        if any(not isinstance(group, list) or not group for group in groups):
            raise ValueError("Every seed group must be nonempty")
        seeds = sum(groups, [])
        if any(type(seed) is not int or seed < 0 for seed in seeds) or len(set(seeds)) != len(
            seeds
        ):
            raise ValueError("Seeds must be unique, nonnegative and disjoint across groups")
        b = self.boundaries_minutes
        if (
            len(b) != 5
            or any(type(v) is not int for v in b)
            or b[0] != 0
            or b[-1] != config.duration_minutes
            or any(v - u <= 25 for u, v in zip(b, b[1:], strict=False))
        ):
            raise ValueError("Four ordered partitions of more than 25 minutes must span coverage")
        if type(self.model_seed) is not int or self.model_seed < 0:
            raise ValueError("Invalid model seed")
        if (
            isinstance(self.false_alert_budget, bool)
            or not isinstance(self.false_alert_budget, (float, int))
            or not np.isfinite(self.false_alert_budget)
            or self.false_alert_budget < 0
        ):
            raise ValueError("False-alert budget must be finite and nonnegative")

    def resolved(self):
        return {
            **self.__dict__,
            "simulation": SimulationConfig.from_dict(self.simulation).to_dict(),
        }

    @classmethod
    def load(cls, path):
        return cls(**json.loads(Path(path).read_text()))


def run_configs(config: ExperimentConfig):
    base = SimulationConfig.from_dict(config.simulation)
    for group, seeds in [
        ("development", config.development_seeds),
        ("heldout_seed", config.heldout_seeds),
        ("heldout_regime", config.regime_seeds),
    ]:
        for seed in seeds:
            simulation = replace(base, seed=seed)
            if group == "heldout_regime":
                # Renewal-like scheduling: no stratified slots, changed spacing, duration,
                # severity and type frequencies. Equations and service profiles stay fixed.
                rng = np.random.default_rng(seed)
                events = []
                for service in base.services:
                    cursor = float(base.warmup_minutes)
                    while True:
                        cursor += rng.uniform(45, 210)
                        event = IncidentSpec(
                            service.name,
                            str(rng.choice(INCIDENT_TYPES)),
                            cursor,
                            precursor_minutes=float(rng.uniform(15, 45)),
                            active_minutes=float(rng.uniform(20, 50)),
                            recovery_minutes=float(rng.uniform(10, 35)),
                            severity=float(rng.uniform(0.6, 1.4)),
                        )
                        if (
                            event.recovery_end_minute
                            > base.duration_minutes - base.cooldown_minutes
                        ):
                            break
                        events.append(event)
                        cursor = event.recovery_end_minute
                simulation = replace(simulation, incidents=tuple(events))
            yield f"{group}-{seed}", group, simulation


def prepare_corpus(config: ExperimentConfig, root: Path) -> list:
    records = []
    for run_id, group, simulation in run_configs(config):
        path = root / run_id
        LOGGER.info(f"corpus_run {run_id}")
        if not path.exists():
            write_dataset(simulate(simulation), simulation, path)
        result, manifest = read_dataset(path)
        if SimulationConfig.load(path / "config.json").to_dict() != simulation.to_dict():
            raise ValueError(f"Existing corpus configuration differs: {run_id}")
        records.append((run_id, group, simulation, result, manifest))
    return records


def assign_rows(result, simulation, group, config):
    start = pd.Timestamp(simulation.start)
    features = build_features(result.telemetry, coverage_start=start)
    joined = attach_targets(features, result.labels)
    joined["partition"] = "purged"
    if group == "development":
        for stage, begin, end in zip(
            STAGES, config.boundaries_minutes[:-1], config.boundaries_minutes[1:], strict=True
        ):
            mask = partition_mask(
                joined.timestamp,
                start + pd.Timedelta(minutes=begin),
                start + pd.Timedelta(minutes=end),
            )
            joined.loc[mask, "partition"] = stage
    else:
        mask = partition_mask(
            joined.timestamp, start, start + pd.Timedelta(minutes=simulation.duration_minutes)
        )
        joined.loc[mask, "partition"] = group
    return joined


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")


def publish_manifest(path):
    write_json(
        path / "manifest.json",
        {
            "schema_version": "batch-b-1.0",
            "sha256": {
                str(file.relative_to(path)): file_hash(file)
                for file in sorted(path.rglob("*"))
                if file.is_file() and file.name != "manifest.json"
            },
        },
    )


def verify_experiment(path):
    manifest = json.loads((path / "manifest.json").read_text())
    if manifest["schema_version"] != "batch-b-1.0":
        raise ValueError("Unsupported experiment version")
    actual = {
        str(file.relative_to(path))
        for file in path.rglob("*")
        if file.is_file() and file.name != "manifest.json"
    }
    if actual != set(manifest["sha256"]):
        raise ValueError("Experiment file inventory mismatch")
    for name, digest in manifest["sha256"].items():
        if file_hash(path / name) != digest:
            raise ValueError(f"Experiment integrity failure: {name}")
    return manifest


def run_experiment(config: ExperimentConfig, corpus: Path, output: Path) -> dict:
    if output.exists():
        raise FileExistsError(f"Experiment output exists: {output}")
    records = prepare_corpus(config, corpus)
    output.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{output.name}-", dir=output.parent))
    try:
        summary = _run(config, records, staging)
        publish_manifest(staging)
        if output.exists():
            raise FileExistsError(f"Output appeared: {output}")
        staging.rename(output)
        return summary
    finally:
        if staging.exists():
            shutil.rmtree(staging)


def _run(config, records, output):
    write_json(output / "config.json", config.resolved())
    write_json(
        output / "feature_schema.json",
        {"version": FEATURE_VERSION, "names": FEATURE_NAMES, "dtype": "float64"},
    )
    write_json(
        output / "environment.json",
        {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "dependencies": {
                name: importlib.metadata.version(name)
                for name in [
                    "numpy",
                    "pandas",
                    "pyarrow",
                    "matplotlib",
                    "scikit-learn",
                    "scipy",
                    "joblib",
                    "threadpoolctl",
                ]
            },
            "source_sha256": {
                str(p): file_hash(p)
                for p in sorted(Path("src/reliability_intelligence").rglob("*.py"))
            },
            "model_seed": config.model_seed,
        },
    )
    frames, truths, corpus_rows, manifests, boundaries = [], [], [], {}, []
    for run_id, group, simulation, result, manifest in records:
        rows = assign_rows(result, simulation, group, config).assign(run_id=run_id)
        frames.append(rows)
        truth = result.incidents.assign(run_id=run_id, group=group)
        truth["onset_partition"] = group
        if group == "development":
            start = pd.Timestamp(simulation.start)
            for stage, begin, end in zip(
                STAGES, config.boundaries_minutes[:-1], config.boundaries_minutes[1:], strict=True
            ):
                lower, upper = (
                    start + pd.Timedelta(minutes=begin),
                    start + pd.Timedelta(minutes=end),
                )
                truth.loc[
                    (truth.incident_start >= lower) & (truth.incident_start < upper),
                    "onset_partition",
                ] = stage
                boundaries.append(
                    {
                        "run_id": run_id,
                        "partition": stage,
                        "start_inclusive": lower,
                        "end_exclusive": upper,
                    }
                )
        else:
            boundaries.append(
                {
                    "run_id": run_id,
                    "partition": group,
                    "start_inclusive": simulation.start,
                    "end_exclusive": pd.Timestamp(simulation.start)
                    + pd.Timedelta(minutes=simulation.duration_minutes),
                }
            )
        truths.append(truth)
        corpus_rows.append(
            {
                "run_id": run_id,
                "group": group,
                "seed": simulation.seed,
                "duration_minutes": simulation.duration_minutes,
                "telemetry_rows": len(result.telemetry),
                "incidents": len(truth),
            }
        )
        manifests[run_id] = manifest
    all_rows = pd.concat(frames, ignore_index=True)
    truth = pd.concat(truths, ignore_index=True)
    pd.DataFrame(corpus_rows).to_csv(output / "corpus.csv", index=False)
    pd.DataFrame(boundaries).to_csv(output / "boundaries.csv", index=False)
    truth.groupby(["group", "onset_partition", "service_id", "incident_type"]).size().rename(
        "incidents"
    ).to_csv(output / "event_counts.csv")
    truth.to_parquet(output / "incidents.parquet", index=False)
    write_json(output / "corpus_manifests.json", manifests)
    all_rows.groupby(["run_id", "partition"]).agg(
        rows=(TARGET, "size"),
        positives=(TARGET, "sum"),
        first=("timestamp", "min"),
        last=("timestamp", "max"),
    ).to_csv(output / "splits.csv")
    all_rows[["run_id", "timestamp", "service_id", "partition"]].to_parquet(
        output / "assignments.parquet", index=False
    )
    train = all_rows.loc[all_rows.partition == "train"]
    calibration = all_rows.loc[all_rows.partition == "calibration"]
    validation = all_rows.loc[all_rows.partition == "validation"]
    LOGGER.info("fitting_candidates")
    models = fit_candidates(train, calibration, config.model_seed)
    selected, comparison = choose_model(validation, models)
    comparison.to_csv(output / "validation_candidates.csv", index=False)
    predictions, reliability = [], []
    for name, model in models.items():
        rows = validation[["run_id", "timestamp", "service_id", "partition", TARGET]].copy()
        rows["probability"] = model.predict(validation[list(FEATURE_NAMES)])
        rows["candidate"] = name
        predictions.append(rows)
    val_predictions = pd.concat(predictions, ignore_index=True)
    tradeoffs = []
    # Includes 1.0 as a practical no-alert endpoint for these nondegenerate estimators.
    thresholds = np.unique(np.r_[0, np.linspace(0.01, 0.99, 50), 1.0])
    for name, rows in val_predictions.groupby("candidate"):
        for threshold in thresholds:
            op, _, _ = operational_metrics(rows, truth, threshold)
            tradeoffs.append(
                {
                    "candidate": name,
                    "threshold": float(threshold),
                    **row_metrics(rows[TARGET], rows.probability, threshold),
                    **op,
                }
            )
    tradeoffs = pd.DataFrame(tradeoffs)
    threshold = select_threshold(
        tradeoffs.loc[tradeoffs.candidate == selected], config.false_alert_budget
    )
    tradeoffs.to_csv(output / "thresholds.csv", index=False)
    candidate_thresholds = {
        name: select_threshold(
            tradeoffs.loc[tradeoffs.candidate == name], config.false_alert_budget
        )
        for name in models
    }
    selection = {
        "candidate_thresholds": candidate_thresholds,
        "candidate": selected,
        "threshold": threshold,
        "false_alert_budget": config.false_alert_budget,
        "family_rule": "highest raw validation average precision; ties use log loss then name",
        "calibration_rule": "sigmoid only if validation Brier AND log loss strictly improve",
        "threshold_rule": (
            "max detection within budget; tie: fewer alert minutes, then higher threshold"
        ),
        "fit_partition": "train",
        "calibration_partition": "calibration",
        "selection_partition": "validation",
    }
    # Freeze and persist BEFORE generating any test/holdout predictions or scores.
    write_json(output / "selection.json", selection)
    for name, model in models.items():
        save_model(model, output / f"{name}.joblib")
    LOGGER.info(f"choices_frozen {selected} threshold={threshold}")
    for partition in ["temporal_test", "heldout_seed", "heldout_regime"]:
        subset = all_rows.loc[all_rows.partition == partition]
        for name, model in models.items():
            rows = subset[["run_id", "timestamp", "service_id", "partition", TARGET]].copy()
            rows["probability"] = model.predict(subset[list(FEATURE_NAMES)])
            rows["candidate"] = name
            predictions.append(rows)
    predictions = pd.concat(predictions, ignore_index=True)
    predictions.to_parquet(output / "predictions.parquet", index=False)
    metrics, event_frames, episode_frames, uncertainty, service_metrics = [], [], [], {}, []
    for (partition, name), rows in predictions.groupby(["partition", "candidate"], sort=True):
        # Each candidate has its own validation-frozen threshold for fair comparisons.
        cut = candidate_thresholds[name]
        op, events, episodes = operational_metrics(rows, truth, cut)
        metrics.append(
            {
                "partition": partition,
                "candidate": name,
                "threshold": cut,
                **row_metrics(rows[TARGET], rows.probability, cut),
                **op,
            }
        )
        rel = reliability_table(rows[TARGET], rows.probability)
        reliability.append(rel.assign(partition=partition, candidate=name))
        event_frames.append(events.assign(partition=partition, candidate=name))
        episode_frames.append(episodes.assign(partition=partition, candidate=name))
        if name == selected:
            uncertainty[partition] = grouped_uncertainty(rows, events)
            for service, group in rows.groupby("service_id"):
                sm, _, _ = operational_metrics(group, truth, cut)
                service_metrics.append(
                    {
                        "partition": partition,
                        "service_id": service,
                        **row_metrics(group[TARGET], group.probability, cut),
                        **sm,
                    }
                )
    table = pd.DataFrame(metrics)
    table.to_csv(output / "metrics.csv", index=False)
    pd.DataFrame(service_metrics).to_csv(output / "service_metrics.csv", index=False)
    pd.concat(reliability).to_csv(output / "calibration.csv", index=False)
    pd.concat(event_frames).to_csv(output / "incident_results.csv", index=False)
    pd.concat(episode_frames).to_csv(output / "alert_episodes.csv", index=False)
    write_json(output / "uncertainty.json", uncertainty)
    coefficients = models["logistic_raw"].pipeline[-1].coef_[0]
    pd.DataFrame(
        {"feature": FEATURE_NAMES, "standardised_logistic_coefficient": coefficients}
    ).to_csv(output / "coefficients.csv", index=False)
    summary = {
        "synthetic": True,
        "selection": selection,
        "corpus_incidents": len(truth),
        "telemetry_rows": sum(row["telemetry_rows"] for row in corpus_rows),
        "selected_metrics": table.loc[table.candidate == selected]
        .replace({np.nan: None})
        .to_dict("records"),
    }
    write_json(output / "summary.json", summary)
    from reliability_intelligence.ml_evidence import report_text

    (output / "REPORT.md").write_text(report_text(output))
    return summary
