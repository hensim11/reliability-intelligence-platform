"""Separate ordinal SMD forecasting study. No production-schema or model transfer."""

import argparse
import json
import platform
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from threadpoolctl import threadpool_limits

from reliability_intelligence.evaluation import row_metrics
from reliability_intelligence.monitoring.reference import publish
from reliability_intelligence.storage import file_hash

COMMIT = "7fb0e0acf89ea49908896bcc9f9e80fcfff6baf4"
MACHINES = tuple(
    f"machine-{group}-{i}"
    for group, count in [(1, 8), (2, 9), (3, 11)]
    for i in range(1, count + 1)
)


def validate_dataset(root, machines=MACHINES):
    inventory, arrays = {}, {}
    for folder in ("train", "test", "test_label"):
        files = sorted((root / folder).glob("*"))
        if {p.name for p in files} != {f"{m}.txt" for m in machines}:
            raise ValueError(f"Unexpected {folder} inventory")
        for path in files:
            data = np.loadtxt(path, delimiter=",", ndmin=2)
            expected = 1 if folder == "test_label" else 38
            if data.shape[1] != expected or not len(data) or not np.isfinite(data).all():
                raise ValueError(f"Invalid array: {path.name}")
            if folder == "test_label" and not np.isin(data, [0, 1]).all():
                raise ValueError("Nonbinary labels")
            inventory[f"{folder}/{path.name}"] = {
                "sha256": file_hash(path),
                "shape": list(data.shape),
            }
            arrays[(folder, path.stem)] = data
    for machine in machines:
        if len(arrays[("test", machine)]) != len(arrays[("test_label", machine)]):
            raise ValueError("Test/label row mismatch")
    return inventory, arrays


def targets(labels):
    labels = np.asarray(labels)
    if labels.ndim != 1 or not np.isin(labels, [0, 1]).all():
        raise ValueError("Binary one-dimensional labels required")
    starts = np.flatnonzero((labels == 1) & np.r_[True, labels[:-1] == 0])
    index = np.arange(len(labels))
    y = (
        np.searchsorted(starts, index + 10, side="right")
        > np.searchsorted(starts, index, side="right")
    ).astype(float)
    y[index + 10 >= len(labels)] = np.nan
    return y, starts


def features(values):
    values = np.asarray(values, dtype=float)
    if values.ndim != 2 or values.shape[1] != 38 or not np.isfinite(values).all():
        raise ValueError("Expected 38 finite anonymous dimensions")
    rolling = pd.DataFrame(values).rolling(15, min_periods=15).mean().to_numpy()
    return np.column_stack([values, rolling])


def partitions(n):
    boundaries = [0, int(n * 0.5), int(n * 0.7), n]
    index = np.arange(n)
    return {
        name: (index - 15 >= begin) & (index + 10 < end)
        for name, begin, end in zip(
            ("train", "validation", "evaluation"), boundaries[:-1], boundaries[1:], strict=True
        )
    }


def step_metrics(index, y, probability, starts, threshold=0.5):
    result = row_metrics(np.asarray(y, dtype=int), probability, threshold)
    active = np.asarray(index)[np.asarray(probability) >= threshold]
    scorable, leads = 0, []
    for onset in starts:
        if ((index < onset) & (index >= onset - 10)).any():
            scorable += 1
            hits = active[(active < onset) & (active >= onset - 10)]
            if len(hits):
                leads.append(int(onset - hits.min()))
    groups = np.split(active, np.flatnonzero(np.diff(active) != 1) + 1) if len(active) else []
    false = sum(
        not any(((group < onset) & (group >= onset - 10)).any() for onset in starts)
        for group in groups
    )
    return {
        **result,
        "scorable_starts": scorable,
        "detected_starts": len(leads),
        "start_detection_rate": len(leads) / scorable if scorable else None,
        "lead_steps": leads,
        "mean_lead_steps": float(np.mean(leads)) if leads else None,
        "false_alert_episodes": false,
        "alert_episodes": len(groups),
        "alert_rows": len(active),
        "alert_row_fraction": len(active) / len(index) if len(index) else None,
    }


def study(root, output, config_path):
    config = json.loads(config_path.read_text())
    expected_protocol = {
        "source_commit": "7fb0e0acf89ea49908896bcc9f9e80fcfff6baf4",
        "observation_steps": 15,
        "horizon_steps": 10,
        "train_fraction": 0.5,
        "validation_end_fraction": 0.7,
        "logistic_C": 1.0,
        "logistic_max_iter": 2000,
        "seed": 2026,
        "threshold": 0.5,
        "selection": "No family or threshold selection; report both fixed baselines",
        "features": "38 anonymous dimensions: current and preceding-15-step mean",
        "pooling": (
            "Fit separately per machine; pooled evaluation concatenates frozen machine predictions"
        ),
    }
    if config != expected_protocol:
        raise ValueError("Study protocol differs from fixed implementation")
    checkout = root.parent
    head = subprocess.check_output(
        ["git", "-C", str(checkout), "rev-parse", "HEAD"], text=True
    ).strip()
    if head != COMMIT:
        raise ValueError("Wrong upstream commit")
    dirty = subprocess.check_output(
        ["git", "-C", str(checkout), "status", "--porcelain", "--", "ServerMachineDataset"],
        text=True,
    )
    if dirty:
        raise ValueError("Upstream source modified")
    inventory, arrays = validate_dataset(root)
    results, pooled = [], {}
    with threadpool_limits(limits=1):
        for machine in MACHINES:
            values = arrays[("test", machine)]
            labels = arrays[("test_label", machine)].ravel()
            x, (y, starts), masks = features(values), targets(labels), partitions(len(values))
            train = masks["train"]
            prior = float(y[train].mean())
            model = None
            if len(np.unique(y[train])) == 2:
                model = make_pipeline(
                    StandardScaler(), LogisticRegression(C=1, max_iter=2000, random_state=2026)
                ).fit(x[train], y[train].astype(int))
            for partition, mask in masks.items():
                if partition == "train":
                    continue
                index = np.flatnonzero(mask)
                for family in ("prevalence", "logistic"):
                    if family == "logistic" and model is None:
                        results.append(
                            {
                                "machine": machine,
                                "partition": partition,
                                "family": family,
                                "unavailable": "development training has one class",
                            }
                        )
                        continue
                    p = (
                        np.full(len(index), prior)
                        if family == "prevalence"
                        else model.predict_proba(x[mask])[:, 1]
                    )
                    result = {
                        "machine": machine,
                        "partition": partition,
                        "family": family,
                        "training_rows": int(train.sum()),
                        "training_prevalence": prior,
                        **step_metrics(index, y[mask], p, starts),
                    }
                    results.append(result)
                    pooled.setdefault((partition, family), []).append((y[mask], p, result))
    aggregates = []
    for (partition, family), items in sorted(pooled.items()):
        row = row_metrics(
            np.concatenate([item[0] for item in items]).astype(int),
            np.concatenate([item[1] for item in items]),
            0.5,
        )
        summed = {
            key: sum(item[2][key] for item in items)
            for key in (
                "scorable_starts",
                "detected_starts",
                "false_alert_episodes",
                "alert_episodes",
                "alert_rows",
            )
        }
        leads = [lead for item in items for lead in item[2]["lead_steps"]]
        aggregates.append(
            {
                "partition": partition,
                "family": family,
                "machines": len(items),
                **row,
                **summed,
                "start_detection_rate": summed["detected_starts"] / summed["scorable_starts"]
                if summed["scorable_starts"]
                else None,
                "mean_lead_steps": float(np.mean(leads)) if leads else None,
                "alert_row_fraction": summed["alert_rows"] / row["rows"],
            }
        )
    source = {
        "repository": "https://github.com/NetManAIOps/OmniAnomaly",
        "dataset": f"https://github.com/NetManAIOps/OmniAnomaly/tree/{COMMIT}/ServerMachineDataset",
        "commit": head,
        "download_timestamp": datetime.fromtimestamp(
            (checkout / ".git/FETCH_HEAD").stat().st_mtime
            if (checkout / ".git/FETCH_HEAD").exists()
            else (checkout / ".git/HEAD").stat().st_mtime,
            UTC,
        ).isoformat(),
        "licence": "MIT",
        "licence_sha256": file_hash(root / "LICENSE"),
        "files": inventory,
    }
    publish(
        output,
        {
            "source.json": source,
            "protocol.json": config,
            "results.json": {"per_machine": results, "pooled": aggregates},
            "environment.json": {
                "python": platform.python_version(),
                "packages": subprocess.check_output(
                    [__import__("sys").executable, "-m", "pip", "freeze"], text=True
                ).splitlines(),
            },
        },
    )
    return aggregates


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--config", type=Path, default=Path("configs/batch_d_external.json"))
    args = parser.parse_args()
    print(json.dumps(study(args.dataset, args.output, args.config), indent=2))


if __name__ == "__main__":
    main()
