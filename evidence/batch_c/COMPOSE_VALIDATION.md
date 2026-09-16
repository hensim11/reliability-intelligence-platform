# Batch C Compose acceptance

**Passed — Gate 14 closed; Batch C locally accepted.** Final clean-volume repeat:
2026-09-16 **05:06:59–05:08:50 UTC** (about 111 seconds including build and tests).
Branch: `batch-c-production-serving-persistence`. Clean source tested:
`42f40614e922384eee64d4fbe1dfcccd321df17d`. The later documentation/evidence commit
records this run; it does not change the tested application, tests, Dockerfile or Compose file.

[Machine-readable evidence](compose_validation.json) contains sanitized commands, source and
artefact hashes, image IDs, health states, representative HTTP/SQL results and exact test output.
The earlier [native reference](reference/results.json) is unchanged.

## Environment and reproduction

| Component | Version |
| --- | --- |
| Host | macOS 26.2, arm64 |
| Docker Desktop | 4.91.0 (239619), installed with explicit user authorization |
| Docker Engine / API | 29.8.0 / 1.56 |
| Compose plugin | 5.5.1 |
| Container platform | Linux arm64, kernel 7.0.12-linuxkit |
| PostgreSQL | 18.3 (Debian 18.3-1.pgdg13+1), aarch64 |
| Python | 3.14.0 on host and in application container |

With the original ignored frozen model/telemetry files and a mode-0600 ignored `.env`:

```bash
export PATH="/Applications/Docker.app/Contents/Resources/bin:$PATH"
export DOCKER_BIN=/Applications/Docker.app/Contents/Resources/bin/docker
.venv/bin/python scripts/validate_compose.py \
  --project rip-batchc-closeout-20260916-r4 \
  --work data/batch_c_compose_run_20260916_r4 \
  --output data/batch_c_compose_evidence_20260916_r4
```

Use new project/work/output names for another run. The runner executes `compose config
--quiet`, `build --pull --no-cache`, `up -d --wait --wait-timeout 180`, HTTP/SQL assertions,
service restarts, migration rerun, regression checks and `down --volumes`. Exact command
arguments are recorded in JSON. Passwords and the test database URL are excluded from evidence.

## Results

| Check | Observed result |
| --- | --- |
| Clean configuration/build | Exit 0; both application images built without cache |
| Empty PostgreSQL volume | No prior project/volume; telemetry/predictions initially 0/0 |
| Startup and migration | Database/API healthy; one-shot migration exit 0; revision `c001` |
| Loopback ports | Host bindings `127.0.0.1:5432` and `127.0.0.1:8000` |
| Liveness/readiness | Both HTTP 200 |
| Ingestion | HTTP 200; 16 inserted, 0 unchanged; durable SQL count 16 |
| Prediction | HTTP 201; one persisted prediction with all 14 contract fields |
| Saved history | HTTP 200; exactly the original prediction |
| SQL latest/daily | Matching prediction UUID; daily count 1 |
| Coverage/probability | api-gateway 16 observed / 0 missing minutes; one risk probability |
| Restart durability | Restarted database then API; ready; telemetry/prediction counts remain 16/1 |
| Idempotency | Retry HTTP 200 with identical full response/UUID; duplicate keys 0 |
| Migration rerun | Exit 0; still `c001` |
| Regression | **205 passed, 0 failed, 0 errors, 0 skipped**, 14.89 s; all 23 PostgreSQL tests |
| Quality | Ruff check passed; format: 59 files already formatted; pip: no broken requirements |
| Isolation | Tests use separate disposable `reliability_test`; smoke prediction survives tests |
| Cleanup | All project containers and disposable named volume removed after evidence capture |

The api-gateway event time is `2026-01-05T00:15:00Z`, observation bounds
`(2026-01-05T00:00:00Z, 2026-01-05T00:15:00Z]`. Advisory probability:
`0.00036702774501820524`; threshold `0.5700000000000001`; decision `not-elevated-risk`.
UUID `b2335b7c-4547-4f2e-a50a-432d890947e1` was preserved across restarts/retry.
Availability cutoff and production timestamps are server-recorded on 2026-09-16: this is
**retrospective event-time scoring**, not a claim of historical availability.
Input assertions permit only the nine operational telemetry fields; no labels, incident truth,
future observations or client ingestion times enter the smoke request.

## Hashes and preservation

- Frozen model SHA-256:
  `14dba3dcab87892e37e1a00cc6623f9d708be9f874552fcde8f35c51287350ef`
- Model identity:
  `2d3f3c7c1e0f72d4c19970e0ad11766c2005644228d8c8f51395edacfd8498c8`
- Telemetry SHA-256:
  `c1520d3bdc674dcb9d4a70893a2765440f60b67c4bdf115d264cac3f83a2abe1`

All six required model artefacts match their existing manifest. JSON records those hashes,
serving/migration/build/runner source hashes, exact dependency versions and all three image IDs.
No Batch A/B implementation, frozen model, threshold, dataset or committed evidence was changed.
No training, tuning or recalibration occurred.

## Log review and deviations

- One smoke `FATAL: terminating connection due to administrator command` coincides with the
  deliberate database restart. Readiness subsequently recovers and persisted records match.
- Fourteen further database errors correspond to explicit regression cases: invalid metrics,
  service/time constraints, immutability, missing predictions/migration tables, injected write
  failure, duplicate prediction key, probability range and model foreign key. No unexpected
  application errors or tracebacks were found. Raw logs remain ignored locally.
- The two existing upstream Starlette/httpx and anyio deprecation warnings remain visible;
  no suppression or test weakening was used.
- Bundled Compose **5.5.1** replaces the original runbook's v2 prerequisite; the `docker compose`
  interface works unchanged. Docker's binary directory must be on PATH for its credential helper.
- Earlier attempts encountered a Docker container-start stall. A Desktop restart restored a
  no-mount probe; a subsequent full run passed after an unexplained long startup/UI delay.
  This final clean build/empty-volume repeat completed in about 111 seconds. The root cause of
  that earlier host/runtime delay was not established; no application correction was needed.

## Acceptance and limitations

The independent review had conditionally accepted Gates 1–13 and 15–25. This Compose evidence
closes Gate 14. [Hosted CI for tested source](https://github.com/hensim11/reliability-intelligence-platform/actions/runs/35012633105)
passed with PostgreSQL and quality checks. Later documentation/evidence commits require their
own hosted checks; consult the branch/PR for the final result and review status. Do not merge.

This local synthetic-data advisory model retains changed-regime degradation and final-partition
false-alert-budget failures. No external validity, production SLO, authentication, deployment,
monitoring, backup/recovery or Batch D/E completion is claimed. Native concurrency timings
remain separate from this Compose correctness exercise.
