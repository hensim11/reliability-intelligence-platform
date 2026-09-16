# Batch D evidence

All evidence is local; synthetic telemetry and ordinal SMD results do not establish production
incident-prediction validity. No production model retraining, recalibration or threshold change.

- [Monitoring/reliability report](REPORT.md) and [results](reliability/reliability.json).
- [Compose validation](reliability/compose_validation.json): source `92ebb54`, environment,
  exact command outcomes, source/model hashes, 238 tests/zero skips and resource cleanup.
- [Training-only monitoring reference](monitoring_reference/reference.json), 34,260 rows,
  identity `240df61ff788f23ac5562097787c37a81f6db83395f2af990e0e23a4956e3f15`.
- [SMD report](smd/REPORT.md), [per-machine table](smd/per_machine.csv),
  [pooled table](smd/pooled.csv), [plot](smd/external_results.png),
  [source/licence/file manifest](smd/source.json), [fixed protocol](smd/protocol.json).
- [Frozen HTTP parity report](parity/REPORT.md), [results](parity/results.json).
- [Regeneration checks](reproducibility/results.json): 16/16 files byte-identical.
- [Acceptance table and commands](../../docs/BATCH_D_COMPLETION.md).

Each evidence subdirectory has a sealed SHA-256 manifest. Raw external data, models, full telemetry,
volumes and transient logs remain ignored. Operational results contain real generated UUIDs,
cutoffs, computation times and measured latency; these are intentionally dynamic. Counts, drift
values for fixed inputs, eligibility, failure statuses and parity are reproducible assertions.

Two development attempts retained local diagnostics: one stopped on a newly edited report script's
lint failure; another completed failure/recovery checks but its reset assertion mistook Prometheus
HELP text for a live counter sample. Both were corrected and a fresh clean-volume run passed.
The final smoke log's `terminating connection due to administrator command` is the deliberate
restart. Regression errors correspond to exercised constraint/rollback failures; no warnings were
suppressed. Two upstream Starlette/anyio deprecation warnings remain.
