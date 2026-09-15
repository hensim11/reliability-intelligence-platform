# Visual review — 2026-09-15

All five saved final PNGs were opened and visually inspected at readable resolution.

| Figure | Review |
| --- | --- |
| precision_recall.png | All four partition titles, axes and legends legible; full [0,1] recall and precision ranges. Raw/sigmoid curves overlap because sigmoid preserves ranking; both remain in the legend for traceability. |
| calibration.png | Initial top-panel title spacing was inadequate. Regenerated with explicit margins and subplot spacing; all four titles and axes now visible without overlap. Full probability/frequency axes; occupied bins only, exact counts in CSV. |
| thresholds.png | All grid points shown, with false-alert budget line. Discrete points avoid implying a monotonic episode-count frontier. Separate burden panel exposes always-on forecasts; complete vertical scale retained. |
| operations.png | Four stages and metric units are readable. Fraction axes start at zero and end at one; warning lead ends at ten minutes. False-episode axis starts at zero and contains all bars. Regime degradation and budget breaches are visible. |
| coefficients.png | All 15 long feature labels fit; signed axis contains full coefficients and zero reference. Title states association, not causal importance. |

Final figures were reinspected after regeneration. Numerical predictions, selected models and
thresholds were unchanged. Evidence-only reproduction then matched all five PNG hashes exactly.
No favourable time examples or manually adjusted plotted metrics were used.
