"""Reproduce Batch D Compose acceptance using a NEW disposable project and ignored .env.

Run from the repository root. Requires Docker, the existing frozen model/telemetry fixtures,
and the validated local Python environment. Logs/JUnit remain under the ignored work directory.
Successful compact evidence is written to a new output directory. No credentials are recorded.
"""

import argparse
import hashlib
import json
import os
import platform
import subprocess
import time
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True)
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--reference", type=Path, required=True)
    args = parser.parse_args()
    args.work.mkdir(parents=True, exist_ok=False)
    if args.output.exists():
        raise FileExistsError("Evidence output must be new")
    docker = os.environ.get("DOCKER_BIN", "docker")
    override = args.work.resolve() / "ports.yaml"
    override.write_text(
        'services:\n  db:\n    ports: !override ["127.0.0.1:55435:5432"]\n'
        '  api:\n    ports: !override ["127.0.0.1:58001:8000"]\n'
    )
    compose = [
        docker,
        "compose",
        "-f",
        "compose.yaml",
        "-f",
        str(override),
        "--project-name",
        args.project,
        "--env-file",
        ".env",
    ]
    env_values = dict(
        line.split("=", 1)
        for line in Path(".env").read_text().splitlines()
        if line and not line.startswith("#")
    )
    password = env_values["RIP_DB_PASSWORD"]
    model = Path(env_values["RIP_MODEL_DIR"])
    started = datetime.now(UTC).isoformat()
    records = []

    def run(command, *, label, env=None):
        print(label, flush=True)
        result = subprocess.run(command, capture_output=True, text=True, env=env)
        stdout = result.stdout.replace(password, "<redacted>")
        stderr = result.stderr.replace(password, "<redacted>")
        (args.work / f"{label}.log").write_text(stdout + stderr)
        records.append({"label": label, "command": command, "exit_code": result.returncode})
        if result.returncode:
            raise RuntimeError(f"{label} failed; see ignored log {args.work}/{label}.log")
        return stdout.strip()

    def dc(*command, label):
        return run([*compose, *command], label=label)

    def sql(query, label):
        return dc(
            "exec",
            "-T",
            "db",
            "psql",
            "-X",
            "-U",
            "reliability",
            "-d",
            "reliability",
            "-At",
            "-v",
            "ON_ERROR_STOP=1",
            "-c",
            query,
            label=label,
        )

    def http(path, payload=None):
        request = urllib.request.Request(
            "http://127.0.0.1:58001" + path,
            data=None if payload is None else json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=15) as response:
            return {"status": response.status, "body": json.load(response)}

    def await_ready():
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            try:
                response = http("/health/ready")
                if response["status"] == 200:
                    return response
            except OSError, ValueError:
                pass
            time.sleep(2)
        raise RuntimeError("Readiness did not recover within 120 seconds")

    commit = run(["git", "rev-parse", "HEAD"], label="source_commit")
    branch = run(["git", "branch", "--show-current"], label="branch")
    dirty = run(["git", "status", "--porcelain"], label="initial_worktree")
    versions = {
        "docker": json.loads(
            run([docker, "version", "--format", "{{json .}}"], label="docker_version")
        ),
        "compose": dc("version", "--short", label="compose_version"),
        "host_platform": platform.platform(),
        "host_architecture": platform.machine(),
        "host_python": platform.python_version(),
    }
    volume_name = f"{args.project}_postgres_data"
    volumes = run(
        [docker, "volume", "ls", "--format", "{{.Name}}"], label="existing_volume_names"
    ).splitlines()
    if volume_name in volumes:
        raise RuntimeError("Project volume already exists; choose a new disposable project name")
    containers = run(
        [docker, "ps", "-aq", "--filter", f"label=com.docker.compose.project={args.project}"],
        label="existing_project_containers",
    )
    if containers:
        raise RuntimeError("Project containers already exist; choose a new project")
    dc("config", "--quiet", label="compose_config")
    dc("build", "--pull", "--no-cache", label="clean_build")
    dc("up", "-d", "--wait", "--wait-timeout", "180", label="clean_startup")

    def inspect_status(label):
        raw = dc("ps", "--all", "--format", "json", label=label)
        parsed = (
            json.loads(raw)
            if raw.lstrip().startswith("[")
            else [json.loads(line) for line in raw.splitlines()]
        )
        by_service = {row["Service"]: row for row in parsed}
        assert by_service["db"]["Health"] == "healthy"
        assert by_service["api"]["Health"] == "healthy"
        assert by_service["migrate"]["State"] == "exited"
        assert by_service["migrate"]["ExitCode"] == 0
        for row in parsed:
            for port in row.get("Publishers") or []:
                if port["PublishedPort"]:
                    assert port["URL"] == "127.0.0.1"
        return parsed

    statuses = inspect_status("initial_container_status")
    health = http("/health/live")
    readiness = await_ready()
    assert health["status"] == readiness["status"] == 200
    assert sql("SELECT version_num FROM alembic_version", "initial_revision") == "d001"
    assert sql("SELECT count(*) FROM telemetry", "initial_telemetry_count") == "0"
    assert sql("SELECT count(*) FROM predictions", "initial_prediction_count") == "0"
    versions["postgresql"] = sql("SELECT version()", "postgresql_version")
    versions["container_python"] = dc(
        "exec", "-T", "api", "python", "--version", label="container_python"
    )
    versions["container_platform"] = dc(
        "exec",
        "-T",
        "api",
        "python",
        "-c",
        "import platform; print(platform.platform()); print(platform.machine())",
        label="container_platform",
    )
    versions["container_dependencies"] = json.loads(
        dc(
            "exec",
            "-T",
            "api",
            "python",
            "-c",
            "import importlib.metadata as m, json; "
            "print(json.dumps({d.metadata['Name']: d.version for d in m.distributions()}))",
            label="container_dependencies",
        )
    )
    image_ids = dc("images", "--format", "json", label="image_ids")
    frame = pd.read_parquet("data/batch_a/telemetry.parquet")
    frame = frame.loc[frame.service_id == "api-gateway"].head(16)
    assert len(frame) == 16
    samples = frame.to_dict(orient="records")
    for sample in samples:
        sample["timestamp"] = sample["timestamp"].isoformat()
    assert set(samples[0]) == {
        "timestamp",
        "service_id",
        "request_rate_rps",
        "latency_p50_ms",
        "latency_p95_ms",
        "error_rate",
        "cpu_utilisation_pct",
        "memory_utilisation_pct",
        "dependency_latency_ms",
    }
    ingested = http("/telemetry", {"samples": samples})
    assert ingested == {"status": 200, "body": {"inserted": 16, "unchanged": 0}}
    payload = {"service_id": "api-gateway", "timestamp": samples[-1]["timestamp"]}
    result = http("/predictions", payload)
    assert result["status"] == 201
    prediction = result["body"]
    required = {
        "id",
        "service_id",
        "timestamp",
        "produced_at",
        "available_as_of",
        "model_id",
        "model_name",
        "model_sha256",
        "feature_version",
        "threshold",
        "probability",
        "decision",
        "window_start",
        "window_end",
    }
    assert set(prediction) == required
    assert 0 <= prediction["probability"] <= 1
    assert prediction["model_name"] == "boosting_raw"
    assert prediction["threshold"] == 0.5700000000000001
    assert prediction["model_sha256"] == digest(model / "boosting_raw.joblib")
    assert prediction["decision"] == (
        "elevated-risk"
        if prediction["probability"] >= prediction["threshold"]
        else "not-elevated-risk"
    )
    t = pd.Timestamp(payload["timestamp"])
    assert pd.Timestamp(prediction["timestamp"]) == t
    assert pd.Timestamp(prediction["window_end"]) == t
    assert pd.Timestamp(prediction["window_start"]) == t - pd.Timedelta(minutes=15)
    assert (
        t <= pd.Timestamp(prediction["available_as_of"]) <= pd.Timestamp(prediction["produced_at"])
    )
    history = http("/predictions?service_id=api-gateway&limit=1")
    assert history == {"status": 200, "body": [prediction]}
    assert sql("SELECT count(*) FROM telemetry", "smoke_telemetry_count") == "16"
    assert sql("SELECT count(*) FROM predictions", "smoke_prediction_count") == "1"
    latest = json.loads(sql("SELECT row_to_json(r) FROM latest_risk r", "latest_risk"))
    daily = json.loads(sql("SELECT row_to_json(r) FROM daily_risk r", "daily_risk"))
    assert latest["id"] == prediction["id"] and daily["predictions"] == 1
    assert daily["service_id"] == "api-gateway"
    analytics_code = """import json, os
from datetime import datetime, timedelta
from reliability_intelligence.serving.database import make_engine
from reliability_intelligence.serving.analytics import coverage, risk_summary
engine=make_engine(os.environ['RIP_DATABASE_URL'])
start=datetime.fromisoformat(START)
with engine.connect() as connection:
    print(json.dumps({'coverage':coverage(connection,start,start+timedelta(minutes=16)),
        'risk':risk_summary(connection,start,start+timedelta(minutes=16))},default=str))
""".replace("START", repr(samples[0]["timestamp"]))
    analytics = json.loads(
        dc("exec", "-T", "api", "python", "-c", analytics_code, label="operational_analytics")
    )
    assert analytics["coverage"][0]["observed_minutes"] == 16
    assert analytics["coverage"][0]["missing_minutes"] == 0
    assert analytics["risk"][0]["predictions"] == 1
    # Restart the database first, wait for its actual health, then restart the API.
    dc("restart", "db", label="restart_database")
    dc("up", "-d", "--wait", "--wait-timeout", "120", "db", label="database_after_restart")
    dc("restart", "api", label="restart_api")
    restarted = await_ready()
    after = http("/predictions?service_id=api-gateway&limit=1")
    assert after == history
    retry = http("/predictions", payload)
    assert retry == {"status": 200, "body": prediction}
    assert sql("SELECT count(*) FROM telemetry", "restart_telemetry_count") == "16"
    assert sql("SELECT count(*) FROM predictions", "restart_prediction_count") == "1"
    assert (
        sql(
            "SELECT count(*) FROM (SELECT service_id,timestamp,model_id FROM predictions "
            "GROUP BY 1,2,3 HAVING count(*)>1) r",
            "duplicate_predictions",
        )
        == "0"
    )
    dc("run", "--rm", "migrate", label="migration_rerun")
    assert sql("SELECT version_num FROM alembic_version", "final_revision") == "d001"
    smoke_logs = dc("logs", "--no-color", "db", "migrate", "api", label="smoke_service_logs")
    smoke_error_lines = [
        line
        for line in smoke_logs.splitlines()
        if any(word in line for word in ("ERROR", "FATAL", "Traceback"))
    ]
    dc(
        "exec",
        "-T",
        "db",
        "createdb",
        "-U",
        "reliability",
        "reliability_test",
        label="create_disposable_test_database",
    )
    test_env = os.environ.copy()
    test_env["RIP_TEST_DATABASE_URL"] = (
        f"postgresql+psycopg://reliability:{password}@127.0.0.1:55435/reliability_test"
    )
    pytest = run(
        [".venv/bin/pytest", "-q", f"--junitxml={args.work}/tests.xml"],
        label="full_pytest",
        env=test_env,
    )
    import xml.etree.ElementTree as ET

    root = ET.parse(args.work / "tests.xml").getroot()
    assert len(root.findall(".//testcase")) >= 232
    assert (
        not root.findall(".//skipped")
        and not root.findall(".//failure")
        and not root.findall(".//error")
    )
    run([".venv/bin/ruff", "check", "."], label="ruff_check")
    formatting = run([".venv/bin/ruff", "format", "--check", "."], label="ruff_format")
    pip = run([".venv/bin/python", "-m", "pip", "check"], label="pip_check")
    assert sql("SELECT count(*) FROM predictions", "smoke_survives_tests") == "1"
    final_status = inspect_status("final_container_status")
    logs = dc("logs", "--no-color", "db", "migrate", "api", label="service_logs")
    # Raw logs remain local for inspection; no automatic suppression of unexpected errors.
    error_lines = [
        line
        for line in logs.splitlines()
        if any(word in line for word in ("ERROR", "FATAL", "Traceback"))
    ]
    from batch_d_exercises import run_exercises

    from reliability_intelligence.monitoring.reference import publish

    dc(
        "exec",
        "-T",
        "db",
        "createdb",
        "-U",
        "reliability",
        "batch_d_exercises",
        label="create_exercise_database",
    )
    exercise_url = f"postgresql+psycopg://reliability:{password}@127.0.0.1:55435/batch_d_exercises"
    migration_env = {**os.environ, "RIP_DATABASE_URL": exercise_url}
    run([".venv/bin/alembic", "upgrade", "c001"], label="explicit_c001_upgrade", env=migration_env)
    run([".venv/bin/alembic", "upgrade", "head"], label="explicit_d001_upgrade", env=migration_env)
    run(
        [".venv/bin/alembic", "downgrade", "c001"],
        label="explicit_d001_downgrade",
        env=migration_env,
    )
    run(
        [".venv/bin/alembic", "upgrade", "head"], label="explicit_d001_reupgrade", env=migration_env
    )
    exercises = run_exercises(exercise_url, model, args.reference, Path("data/batch_b"))

    (args.work / "exercise_diagnostics.json").write_text(
        json.dumps(exercises, default=str, indent=2)
    )

    def raw_http(path, payload=None):
        request = urllib.request.Request(
            "http://127.0.0.1:58001" + path,
            data=json.dumps(payload).encode() if payload else None,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return response.status, response.read().decode()
        except urllib.error.HTTPError as error:
            return error.code, error.read().decode()

    assert raw_http("/metrics")[0] == 200
    dc("stop", "db", label="injected_database_outage")
    outage = {
        path: raw_http(path)[0]
        for path in ("/health/live", "/health/ready", "/predictions", "/metrics")
    }
    assert outage == {
        "/health/live": 200,
        "/health/ready": 503,
        "/predictions": 503,
        "/metrics": 200,
    }
    assert 'rip_dependency_failures_total{dependency="database"}' in raw_http("/metrics")[1]
    dc("start", "db", label="recover_database")
    await_ready()
    dc("restart", "api", label="batch_d_restart_api")
    await_ready()
    for table, count in exercises["durable_counts"].items():
        actual = dc(
            "exec",
            "-T",
            "db",
            "psql",
            "-U",
            "reliability",
            "-d",
            "batch_d_exercises",
            "-At",
            "-c",
            f"SELECT count(*) FROM {table}",
            label=f"durable_{table}",
        )
        assert int(actual) == count
    assert "rip_dependency_failures_total{" not in raw_http("/metrics")[1]
    exercises["database_outage"] = outage
    exercises["recovery"] = "ready; durable counts unchanged; process counters reset"
    # JSON-safe datetimes are intentionally dynamic; snapshots retain DB computation clocks.
    exercises = json.loads(json.dumps(exercises, default=str))
    dc("down", "--volumes", label="cleanup")
    assert not run(
        [docker, "ps", "-aq", "--filter", f"label=com.docker.compose.project={args.project}"],
        label="cleanup_containers",
    )
    assert (
        volume_name
        not in run(
            [docker, "volume", "ls", "--format", "{{.Name}}"], label="cleanup_volumes"
        ).splitlines()
    )
    manifest = json.loads((model / "manifest.json").read_text())
    artifacts = {
        name: digest(model / name)
        for name in (
            "boosting_raw.joblib",
            "boosting_raw.json",
            "selection.json",
            "feature_schema.json",
            "environment.json",
            "config.json",
        )
    }
    assert all(manifest["sha256"][name] == value for name, value in artifacts.items())
    evidence = {
        "started_at_utc": started,
        "finished_at_utc": datetime.now(UTC).isoformat(),
        "status": "passed",
        "tested_source_commit": commit,
        "branch": branch,
        "initial_worktree": dirty,
        "versions": versions,
        "image_ids": image_ids,
        "commands": records,
        "initial_status": statuses,
        "final_status": final_status,
        "migration": {"initial": "d001", "rerun": "d001"},
        "liveness": health,
        "readiness": readiness,
        "ingestion": ingested,
        "prediction": result,
        "history": history,
        "restart": {
            "readiness": restarted,
            "persisted_telemetry": 16,
            "persisted_predictions": 1,
            "retry": retry,
            "duplicate_keys": 0,
        },
        "sql": {"latest_risk": latest, "daily_risk": daily, **analytics},
        "validation": {
            "pytest": pytest,
            "test_count": len(root.findall(".//testcase")),
            "skips": 0,
            "ruff_check": "passed",
            "ruff_format": formatting,
            "pip_check": pip,
        },
        "smoke_log_error_lines": smoke_error_lines,
        "regression_log_error_line_count": len(error_lines),
        "cleanup": {"containers_removed": True, "volume_removed": True},
        "source_sha256": {
            str(p): digest(p)
            for p in [
                Path("Dockerfile"),
                Path("compose.yaml"),
                Path("requirements-lock.txt"),
                Path("scripts/validate_batch_d.py"),
                *sorted(Path("src/reliability_intelligence").rglob("*.py")),
                *sorted(Path("tests").glob("*.py")),
                *sorted(Path("configs").glob("*.json")),
                Path("scripts/batch_d_exercises.py"),
                *sorted(Path("migrations").rglob("*.py")),
            ]
        },
        "artifact_sha256": artifacts,
        "telemetry_sha256": digest("data/batch_a/telemetry.parquet"),
        "limitations": [
            "Local loopback validation; no production SLO/security/deployment claim.",
            "Historical predictions use retrospective availability cutoff.",
            "Hosted CI and PR review are separate checks.",
        ],
    }
    publish(args.output, {"compose_validation.json": evidence, "reliability.json": exercises})
    print(
        json.dumps(
            {
                "evidence": str(args.output),
                "status": "passed",
                "smoke_log_error_lines": len(smoke_error_lines),
            },
            indent=2,
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
