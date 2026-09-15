# Batch A reference evidence

[Generated report](generated/REPORT.md) contains seven saved figures and links their source
statistics/metadata. Input: local `data/batch_a/`, generated with `configs/batch_a.json` and seed 42.

To reproduce without overwriting the reference:

```bash
reliability generate --config configs/batch_a.json --output data/reproduction
reliability evidence --dataset data/reproduction --output evidence/reproduction
```

Compare table values and manifest hashes in the recorded environment. Plot pixel identity
across OS/font/library changes is not guaranteed. Outputs are computed from data, and none
represent model performance. `validation.txt` records final local engineering checks.
