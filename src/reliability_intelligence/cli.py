"""Batch A command-line entry point with machine-readable application logs."""

import argparse
import json
import logging
from pathlib import Path

from reliability_intelligence.config import SimulationConfig
from reliability_intelligence.simulation.engine import simulate
from reliability_intelligence.storage import write_dataset

LOGGER = logging.getLogger("reliability_intelligence")


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return json.dumps(
            {
                "level": record.levelname,
                "logger": record.name,
                "event": record.getMessage(),
                **getattr(record, "fields", {}),
            }
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Synthetic reliability telemetry tools")
    commands = parser.add_subparsers(dest="command", required=True)
    generate = commands.add_parser("generate", help="Write a new immutable Parquet dataset")
    generate.add_argument("--config", type=Path, required=True)
    generate.add_argument("--output", type=Path, required=True)
    evidence = commands.add_parser("evidence", help="Create plots and a report from saved data")
    evidence.add_argument("--dataset", type=Path, required=True)
    evidence.add_argument("--output", type=Path, required=True)
    batch_b = commands.add_parser("batch-b", help="Generate/reuse corpus, fit and evaluate Batch B")
    batch_b.add_argument("--config", type=Path, required=True)
    batch_b.add_argument("--corpus", type=Path, required=True)
    batch_b.add_argument("--output", type=Path, required=True)
    batch_b.add_argument("--evidence", type=Path)
    ml_evidence = commands.add_parser("batch-b-evidence", help="Regenerate saved ML evidence")
    ml_evidence.add_argument("--experiment", type=Path, required=True)
    ml_evidence.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    LOGGER.handlers = [handler]
    LOGGER.setLevel(logging.INFO)
    LOGGER.propagate = False
    try:
        if args.command == "generate":
            config = SimulationConfig.load(args.config)
            manifest = write_dataset(simulate(config), config, args.output)
            LOGGER.info(
                "dataset_written",
                extra={
                    "fields": {
                        "output": str(args.output),
                        "rows": manifest["rows"],
                        "seed": config.seed,
                    }
                },
            )
        elif args.command == "batch-b":
            from reliability_intelligence.experiment import ExperimentConfig, run_experiment
            from reliability_intelligence.ml_evidence import generate_ml_evidence

            if args.evidence is not None and args.evidence.exists():
                raise FileExistsError(f"Evidence output exists: {args.evidence}")
            run_experiment(ExperimentConfig.load(args.config), args.corpus, args.output)
            if args.evidence is not None:
                generate_ml_evidence(args.output, args.evidence)
            LOGGER.info("experiment_written", extra={"fields": {"output": str(args.output)}})
        elif args.command == "batch-b-evidence":
            from reliability_intelligence.ml_evidence import generate_ml_evidence

            generate_ml_evidence(args.experiment, args.output)
            LOGGER.info("ml_evidence_written", extra={"fields": {"output": str(args.output)}})
        else:
            from reliability_intelligence.evidence import generate_evidence

            summary = generate_evidence(args.dataset, args.output)
            LOGGER.info(
                "evidence_written",
                extra={
                    "fields": {
                        "output": str(args.output),
                        "incidents": summary["incidents"],
                    }
                },
            )
    except (ValueError, TypeError, KeyError, OSError) as error:
        LOGGER.error("command_failed", extra={"fields": {"reason": str(error)}})
        return 1
    return 0
