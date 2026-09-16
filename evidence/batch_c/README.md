# Batch C evidence

- [Reference report](reference/REPORT.md)
- [Machine-readable HTTP/PostgreSQL/parity/latency results](reference/results.json)
- [Compose acceptance report](COMPOSE_VALIDATION.md)
- [Compose machine-readable results](compose_validation.json)
- [Final check summary](validation.json)
- [Acceptance record](../../docs/BATCH_C_COMPLETION.md)
- [Reproduction runbook](../../docs/SERVING.md)

Native PostgreSQL 18.3 + Python 3.14/Uvicorn and clean-volume Docker Compose passed.
Batch C is locally accepted; Gate 14 is closed. The original `reference/results.json` remains
unchanged and records the earlier native exercise. Reference numerical parity is exact. Timings, UUIDs
and server timestamps vary between runs; source/model/input hashes and assertions make the
method reviewable. Repeat output belongs in an unused ignored `data/` directory. Large
model binaries, datasets, database clusters and transient logs are not committed.
