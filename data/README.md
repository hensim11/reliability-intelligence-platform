# Local generated data

Canonical runs contain telemetry.parquet, incidents.parquet, labels.parquet, config.json and
manifest.json. Run `reliability generate --config configs/batch_a.json --output data/my_run`.

The delivered local reference is `data/batch_a/`. Generated bundles are excluded from Git to
avoid accumulating binaries; keep originals locally for audit and reproduce from the saved
configuration/dependency environment. A future dataset registry/storage policy is deferred.
Never join ground truth or future labels into operational predictor fields.


Batch C loads the ignored `data/batch_b_experiment` artefacts read-only. Generated sample
requests and repeat evidence belong under `data/` and remain ignored. PostgreSQL data belongs
in the Compose named volume (or an isolated native cluster), never in version control.
The committed compact Batch C report is under `evidence/batch_c/reference`.
