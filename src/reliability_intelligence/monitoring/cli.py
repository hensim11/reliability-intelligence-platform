"""Trusted-local admin commands; never exposed as outcome-writing HTTP routes."""

import argparse
import json
from datetime import datetime
from pathlib import Path

import sqlalchemy as sa

from reliability_intelligence.monitoring.outcomes import import_outcomes
from reliability_intelligence.monitoring.reference import (
    DriftConfig,
    generate_reference,
    load_reference,
)
from reliability_intelligence.monitoring.snapshots import create_snapshot
from reliability_intelligence.serving.artifact import load_artifact
from reliability_intelligence.serving.contracts import Settings
from reliability_intelligence.serving.database import make_engine
from reliability_intelligence.serving.repository import Repository


def main(argv=None):
    parser = argparse.ArgumentParser(description="Batch D trusted-local monitoring administration")
    commands = parser.add_subparsers(dest="command", required=True)
    reference = commands.add_parser("reference")
    for name in ("experiment", "corpus", "output"):
        reference.add_argument(f"--{name}", required=True, type=Path)
    reference.add_argument("--config", type=Path)
    outcome = commands.add_parser("import-outcomes")
    outcome.add_argument("--input", required=True, type=Path)
    snapshot = commands.add_parser("snapshot")
    snapshot.add_argument("--kind", choices=["drift", "delayed"], required=True)
    snapshot.add_argument("--start", required=True)
    snapshot.add_argument("--end", required=True)
    snapshot.add_argument("--cutoff", type=datetime.fromisoformat)
    snapshot.add_argument("--reference", type=Path)
    args = parser.parse_args(argv)
    if args.command == "reference":
        config = (
            DriftConfig(**json.loads(args.config.read_text())) if args.config else DriftConfig()
        )
        result = generate_reference(args.experiment, args.corpus, args.output, config)
        print(
            json.dumps({"reference_id": result["sha256"], "training_rows": result["training_rows"]})
        )
        return 0
    settings = Settings.from_env()
    engine = make_engine(settings.database_url.get_secret_value())
    try:
        if args.command == "import-outcomes":
            result = import_outcomes(engine, json.loads(args.input.read_text()))
        else:
            artifact = load_artifact(settings.model_directory)
            repo = Repository(engine, artifact)
            repo.check_database()
            repo.register_model()
            reference = (
                load_reference(args.reference, artifact.metadata["id"]) if args.reference else None
            )
            if args.kind == "drift" and reference is None:
                parser.error("drift requires --reference")
            with engine.connect() as connection:
                cutoff = args.cutoff or connection.scalar(sa.text("SELECT clock_timestamp()"))
            result = create_snapshot(repo, args.kind, args.start, args.end, cutoff, reference)
        print(json.dumps(result, default=str, allow_nan=False))
    finally:
        engine.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
