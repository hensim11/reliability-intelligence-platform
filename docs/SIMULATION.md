# Simulation mechanics and assumptions

## Configuration

`configs/batch_a.json` selects a fixed UTC start, 48 hours, 60-second sampling, seed 42 and
four services. `SimulationConfig`, `ServiceProfile`, `IncidentSpec` and `Dynamics` centralise
configuration with strict validation, rejecting unknown JSON keys, invalid ranges and schedules.
The resolved config written with every run includes default coefficients as well as supplied values.
Sampling intervals are positive integer seconds up to 60 and must divide total duration exactly.
15/10-minute task windows are deliberately fixed in this batch.

Set `incidents: []` for a normal-only run. Omit `incidents` (or set it to null) for seeded scheduling;
`incidents_per_service: 0` also disables generated incidents. For explicit schedules use:

```json
"incidents": [
  {"service_id": "api-gateway", "incident_type": "memory_leak",
   "precursor_start_minute": 150, "precursor_minutes": 25,
   "active_minutes": 30, "recovery_minutes": 20, "severity": 1.0}
]
```

Replace/add that member in the complete configuration; this fragment is not standalone JSON.
Explicit events must fit fully within coverage and cannot overlap for one service. Explicit
schedules override `incidents_per_service`; omitted incident durations use the IncidentSpec defaults.
Generated schedules use the top-level duration settings. No silent truncation occurs.

## Normal signals

Each service has its own request rate, comfortable capacity, application/dependency latency
and memory baseline. Daily (24h) and hourly sine cycles adjust offered traffic. Stationary
AR(1) noise introduces persistence with a five-minute correlation length; correlation adjusts
with the sampling interval. A shared traffic-noise stream links services under common load,
and per-service noise streams generate local variation.

Offered traffic divided by capacity drives CPU and modest memory/dependency increases.
CPU above 70%, memory above 80%, and load above capacity introduce additional latency stress.
Dependency time adds directly to application latency. p95 includes a stress-dependent tail;
errors combine low variable baseline failure rates with resource/dependency stress. Saturation
is bounded to physically meaningful ranges. The equations are intentionally interpretable;
constants such as percentile-tail ratios are model assumptions, not empirically fitted values.

## Scheduling and lifecycle

The default places four events in disjoint time blocks per service, after a 120-minute warmup
and before a 60-minute cooldown. Type order and placement within blocks are seeded. Every
service receives each type once; larger counts repeat the four-type cycle before shuffling.
This coverage-oriented design is not a Poisson arrival model or estimated production frequency.
Generated severity varies uniformly between 0.85 and 1.15.

Fault pressure is zero until precursor start, rises linearly to `0.7 × severity` at onset,
rises to peak during the first third of active time, stays at peak until incident end,
and declines linearly to zero over recovery. Thus metric effects are continuous across
boundaries. The formal active state is defined by an injected fault reaching onset pressure,
not by observing an SLO breach. Recovery represents intervention/resolution; it is not an
implemented remedial controller. Non-overlap prevents ambiguous same-service combinations.

| Scenario | Primary mechanism | Secondary consequences |
|---|---|---|
| Memory leak | Memory increases by up to 48 percentage points × pressure | Near exhaustion, application latency and errors rise |
| Database degradation | Dependency time increases by 260 ms × pressure | Application latency rises immediately; errors after dependency stress |
| CPU saturation | CPU increases by 68 percentage points × pressure | CPU stress enlarges latency tail and error fraction |
| Traffic overload | Offered rate multiplies by `1 + 2.8 × pressure` | CPU, memory and dependency load rise; excess capacity pressure adds latency/errors |

The generator accesses scheduled faults only to apply their **current** pressure. It never
inserts schedules or labels into operational output. Independent schedule/noise streams allow
paired counterfactual tests: adding a future incident leaves all earlier rows unchanged, and
affected rows return exactly to the baseline trajectory when the injected effect ends.
This is simulator causality, not proof of causal identification from observational data.

## Limitations relevant to ML

- Four services share load but have no explicit dependency graph or propagating failures.
- One fault per service at a time; fixed default durations and structured timing can be memorised.
- Linear ramps, direct response equations and clipped utilisation simplify real systems.
- Dense, immediate, aggregate observations; no drops, lateness, restarts, retries or measurement bias.
- No benign deployments/load spikes mimicking precursors, abrupt unforeseeable incidents, or external data.
- The 48-hour default is a review fixture with only 16 events, not sufficient model-selection evidence.
- Some low-severity faults may not cross an operational SLO despite their simulation active state.

Batch B should evaluate held-out seeds/time regimes and assess these limitations before interpreting
forecasting performance. Synthetic class balance and correlations are not production estimates.
