# Batch B evidence

Start with [generated/REPORT.md](generated/REPORT.md). All metrics and figures are generated
from immutable saved predictions, not manually constructed examples. Configuration, schemas,
seed assignments, exact corpus/event/split counts, environment/source hashes and source
manifests accompany them. See [the completion checklist](../../docs/BATCH_B_COMPLETION.md).

## Local reproduction

```bash
source .venv/bin/activate
reliability batch-b --config configs/batch_b.json --corpus data/batch_b --output data/batch_b_next --evidence data/batch_b_next_evidence
reliability batch-b-evidence --experiment data/batch_b_experiment --output data/batch_b_evidence_next
```

Choose unused output paths. The final reference source is `data/batch_b_experiment/`; corpus
bundles, row predictions and trusted-local fitted binaries are ignored. The 26 compact files
in `generated/` reproduce byte-for-byte in the recorded environment. Their hashes are in the
manifest. `validation.txt` and `visual_review.md` record local checks and figure review.

Strong same-regime results are synthetic feasibility only. Changed schedules/durations/severity
cause degradation; final false-alert budgets fail to transfer. Always-on baselines demonstrate
why episode precision/recall need burden context. No production or remote-CI success is claimed.
