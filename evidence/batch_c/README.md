# Batch C evidence

- [Reference report](reference/REPORT.md)
- [Machine-readable HTTP/PostgreSQL/parity/latency results](reference/results.json)
- [Final check summary](validation.json)
- [Acceptance record](../../docs/BATCH_C_COMPLETION.md)
- [Reproduction runbook](../../docs/SERVING.md)

Native PostgreSQL 18.3 + Python 3.14/Uvicorn passed; Docker runtime validation remains
outstanding because Docker is absent. Reference numerical parity is exact. Timings, UUIDs
and server timestamps vary between runs; source/model/input hashes and assertions make the
method reviewable. Repeat output belongs in an unused ignored `data/` directory. Large
model binaries, datasets, database clusters and transient logs are not committed.
