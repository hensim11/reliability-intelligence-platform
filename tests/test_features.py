from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

from reliability_intelligence.features import (
    FEATURE_NAMES,
    TARGET,
    attach_targets,
    build_features,
    feature_matrix,
    partition_mask,
)
from reliability_intelligence.simulation.engine import simulate


def test_feature_boundaries_and_statistics(config):
    telemetry = simulate(config).telemetry
    start = pd.Timestamp(config.start)
    minutes = (telemetry.timestamp - start).dt.total_seconds() / 60
    telemetry["request_rate_rps"] = minutes.astype(float)
    features = build_features(telemetry, coverage_start=start)
    row = features.iloc[0]
    assert row.timestamp == start + pd.Timedelta(minutes=15)
    assert row.request_rate_rps__current == 15
    assert row.request_rate_rps__mean == 8
    assert row.request_rate_rps__min == 1
    assert row.request_rate_rps__max == 15
    assert row.request_rate_rps__change == 14
    assert row.request_rate_rps__slope == 1
    assert row.request_rate_rps__std == pytest.approx(np.std(np.arange(1, 16)))
    changed = telemetry.copy()
    changed.loc[changed.timestamp == start, "request_rate_rps"] = 999
    pd.testing.assert_frame_equal(features, build_features(changed, coverage_start=start))


def test_causality_and_service_isolation(config):
    telemetry = simulate(config).telemetry
    start = pd.Timestamp(config.start)
    t = start + pd.Timedelta(minutes=40)
    service = config.services[0].name
    original = build_features(telemetry, coverage_start=start)
    changed = telemetry.copy()
    changed.loc[(changed.timestamp > t) | (changed.service_id != service), "request_rate_rps"] *= 10
    altered = build_features(changed, coverage_start=start)
    mask = (original.timestamp <= t) & (original.service_id == service)
    pd.testing.assert_frame_equal(original.loc[mask], altered.loc[mask])


@pytest.mark.parametrize("missing", [1, 7, 15])
def test_missing_history_is_ineligible(config, missing):
    telemetry = simulate(config).telemetry
    start = pd.Timestamp(config.start)
    service = config.services[0].name
    telemetry = telemetry.loc[
        ~(
            (telemetry.timestamp == start + pd.Timedelta(minutes=missing))
            & (telemetry.service_id == service)
        )
    ]
    features = build_features(telemetry, coverage_start=start)
    at_t = features.loc[features.timestamp == start + pd.Timedelta(minutes=15)]
    assert service not in set(at_t.service_id)
    assert len(at_t) == len(config.services) - 1


def test_off_grid_replacement_rejected(config):
    telemetry = simulate(config).telemetry
    telemetry.loc[14, "timestamp"] += pd.Timedelta(seconds=30)
    with pytest.raises(ValueError, match="grid"):
        build_features(telemetry, coverage_start=pd.Timestamp(config.start))


@pytest.mark.parametrize(
    "column",
    [TARGET, "history_complete", "incident_type", "incident_id", "severity", "seed", "future_cpu"],
)
def test_predictor_leakage_rejected(config, column):
    telemetry = simulate(config).telemetry.assign(**{column: 1})
    with pytest.raises(ValueError, match="allowlist"):
        build_features(telemetry, coverage_start=pd.Timestamp(config.start))


def test_schema_determinism_and_target_alignment(config):
    result = simulate(config)
    features = build_features(result.telemetry, coverage_start=pd.Timestamp(config.start))
    pd.testing.assert_frame_equal(
        features, build_features(result.telemetry.copy(), coverage_start=pd.Timestamp(config.start))
    )
    assert tuple(features.columns[2:]) == FEATURE_NAMES
    assert all(dtype == np.dtype("float64") for dtype in features.iloc[:, 2:].dtypes)
    joined = attach_targets(features, result.labels)
    shuffled = attach_targets(features, result.labels.iloc[::-1])
    pd.testing.assert_frame_equal(joined, shuffled)
    assert len(joined) == (config.duration_minutes - 25) * len(config.services)
    assert not any(name in FEATURE_NAMES for name in [TARGET, "timestamp", "service_id"])
    labels = result.labels.copy()
    labels[TARGET] = labels[TARGET].mask(labels.horizon_complete, 1)
    changed = attach_targets(features, labels)
    pd.testing.assert_frame_equal(joined[list(FEATURE_NAMES)], changed[list(FEATURE_NAMES)])


@pytest.mark.parametrize("mutation", ["duplicate", "missing", "extra", "invalid", "flags"])
def test_bad_target_join(config, mutation):
    result = simulate(config)
    features = build_features(result.telemetry, coverage_start=pd.Timestamp(config.start))
    labels = result.labels.copy()
    if mutation == "duplicate":
        labels = pd.concat([labels, labels.iloc[[30]]])
    elif mutation == "missing":
        labels = labels.drop(index=30)
    elif mutation == "extra":
        labels["incident_id"] = "secret"
    elif mutation == "invalid":
        labels.loc[30, TARGET] = 2
    else:
        labels["history_complete"] = 1
    with pytest.raises(ValueError):
        attach_targets(features, labels)


@pytest.mark.parametrize("mutation", ["extra", "order", "dtype", "nan"])
def test_strict_inference_matrix(config, mutation):
    x = build_features(simulate(config).telemetry, coverage_start=pd.Timestamp(config.start))[
        list(FEATURE_NAMES)
    ]
    if mutation == "extra":
        x[TARGET] = 0
    elif mutation == "order":
        x = x.iloc[:, ::-1]
    elif mutation == "dtype":
        x[x.columns[0]] = 1
    else:
        x.iloc[0, 0] = np.nan
    with pytest.raises(ValueError):
        feature_matrix(x)


def test_partition_open_closed_boundaries():
    start = pd.Timestamp("2026-01-01T00:00Z")
    times = pd.Series(
        [start + pd.Timedelta(minutes=m) for m in [14, 15, 49, 50, 59, 60, 74, 75, 109, 110]]
    )
    first = partition_mask(times, start, start + pd.Timedelta(minutes=60))
    second = partition_mask(
        times, start + pd.Timedelta(minutes=60), start + pd.Timedelta(minutes=120)
    )
    assert first.tolist() == [False, True, True, False, False, False, False, False, False, False]
    assert second.tolist() == [False, False, False, False, False, False, False, True, True, False]
    assert not (first & second).any()


def test_subminute_input_not_silently_downsampled(config):
    with pytest.raises(ValueError, match="grid"):
        build_features(
            simulate(replace(config, interval_seconds=30)).telemetry,
            coverage_start=pd.Timestamp(config.start),
        )


def test_independent_eligibility_exclusions(config):
    result = simulate(config)
    features = build_features(result.telemetry, coverage_start=pd.Timestamp(config.start))
    baseline = attach_targets(features, result.labels)
    labels = result.labels.copy()
    keys = baseline.iloc[:3][["timestamp", "service_id"]]
    for i, key in enumerate(keys.itertuples(index=False)):
        mask = (labels.timestamp == key.timestamp) & (labels.service_id == key.service_id)
        if i == 0:
            labels.loc[mask, "history_complete"] = False
        elif i == 1:
            labels.loc[mask, "horizon_complete"] = False
        else:
            labels.loc[mask, TARGET] = pd.NA
    assert len(attach_targets(features, labels)) == len(baseline) - 3
