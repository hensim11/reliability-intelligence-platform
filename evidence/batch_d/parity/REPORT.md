# Batch C local HTTP/PostgreSQL evidence

184 telemetry samples ingested, 121 predictions persisted.
121 database windows match all 49 offline float64 features exactly; saved
probabilities match the frozen model exactly (maximum absolute error 0.0).

Eight concurrent HTTP clients exercised new requests and retries. A 32-request same-key
race produced exactly one row (201) and 31 identical retries (200).
See `results.json` for measured latency percentiles, environment, hashes, API paths,
SQL analytics and representative failures. The database started empty at revision d001.

This is a loopback, one-worker local exercise, not a production SLO. Inputs are historical
telemetry scored at the current ingestion cutoff. Synthetic validity and changed-regime
limitations from Batch B remain. Docker Compose validation is a separate gate.
