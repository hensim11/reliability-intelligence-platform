# External validation: a separate ordinal SMD study

Read the [generated report](../evidence/batch_d/smd/REPORT.md),
[per-machine table](../evidence/batch_d/smd/per_machine.csv) and
[pinned source manifest](../evidence/batch_d/smd/source.json).

SMD's machines are not software services; anomaly episodes are not confirmed operational incidents.
Its 38 normalized anonymous dimensions are never renamed to our seven metrics. Cadence does not
support a ten-minute claim. The production model is semantically incompatible and is never applied
to SMD. This study evaluates a forecasting protocol under a different domain, not model transfer.

Official source: https://github.com/NetManAIOps/OmniAnomaly/tree/7fb0e0acf89ea49908896bcc9f9e80fcfff6baf4/ServerMachineDataset
Dataset-specific licence: MIT, copyright 2021 NetManAIOps-SMD. Raw files stay ignored under
`data/external/`. The manifest records repository/dataset URL, exact commit, checkout download-time
provenance, licence hash and all 84 train/test/label file hashes and shapes. The runner refuses
another commit or modified dataset files and validates exact 28-machine inventory, 38 dimensions,
finite values, binary labels and matching test/label lengths. Interpretation labels are not read.

Only official test sequences have labels; those sequences are repurposed chronologically. Per
machine: first 50% development-training, next 20% selection-validation, final 30% evaluation.
Rows require `t−15 >= region_start` and `t+10 < region_end`, purging both windows. Current values
and preceding-15-sample means form 76 anonymous numeric features. Labels collapse consecutive
positive runs to starts; target `(t,t+10 steps]`; right-censored rows are excluded. Machine identity
is solely a grouping key. No random splits, future preprocessing or label-derived feature occurs.

The fixed pre-evaluation protocol is [configs/batch_d_external.json](../configs/batch_d_external.json).
Fit each machine's scaler/logistic baseline only on development-training, with C=1, max_iter=2000,
seed=2026, no class balancing. Compare training prevalence, both at fixed 0.5. There is no family or
threshold selection. Validation is retained as diagnostic evidence, not used to change the final
choice. One-class training makes logistic unavailable; all machines remain represented by baseline
and explicit unavailable records. Pooled denominators must therefore accompany results.

Final logistic results are weak: 1/85 scorable starts detected on 22 available machines, 424 false
alert episodes and 2,777 alert rows. Six machines cannot fit logistic because development-training
contains no positive starts. The prevalence baseline covers all 28 machines and detects 0/108
starts at 0.5. Undefined metrics and machines without final starts are listed explicitly. Do not
compare these scores numerically against Batch B as the same task. No evidence of real ten-minute
warning, useful incident prediction or direct synthetic-model transfer is established.

## Reproduction

Downloads are manual/local and never part of CI. Use a new checkout/output path when repeating:

```bash
git clone https://github.com/NetManAIOps/OmniAnomaly.git data/external/OmniAnomaly
git -C data/external/OmniAnomaly checkout 7fb0e0acf89ea49908896bcc9f9e80fcfff6baf4
python -m reliability_intelligence.external \
  --dataset data/external/OmniAnomaly/ServerMachineDataset --output data/new_smd_study
python scripts/export_batch_d.py --study data/new_smd_study --output data/new_smd_evidence
```

Tests use generated tiny fixtures and never download SMD. Results/CSV/plots are deterministic in the
recorded environment. Checkout timestamp, environment paths and package versions are provenance
fields; a new environment must not be claimed byte-identical without checking it. Outputs are
published atomically into previously absent directories with sealed manifests.
