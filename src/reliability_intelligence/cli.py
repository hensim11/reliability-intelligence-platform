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
