# React pilot evidence — 2026-10-23

The original 20-cell series and three owner-requested reruns are separate:

| Model / mode | Original | After requested reruns |
| --- | ---: | ---: |
| Astra baseline |4/5|4/5|
| Astra + Jev |3/5|4/5|
| Sol 6.1 baseline |4/5|4/5|
| Sol 6.1 + Jev |5/5|5/5|

`original-summary.json` and `rerun-summary.json` retain all 20 numerical outcomes, per-check verdicts, known timings/token usage and source-manifest fingerprints. `provenance.json` identifies exactly three replaced cells and explains the distinction between timeouts and quota/transport failures. `manifest.json` fixes the common prompt, starter, dependency and evaluator fingerprints. The 17 other sample rows are unchanged.

Two replacement attempts again reached the 900-second budget without explicit quota errors. Sol baseline r5 retained a site passing all 18 checks; its attempt still timed out. Astra baseline r1 stayed at the starter. Astra offload r4 retains its mobile-overflow failure. Five service interruptions are listed separately. Unknown timing/usage remains null; actual CLI cost is unavailable.

These are curated public summaries. Full logs, credentials and ancillary browser profiles are excluded. Generated sites, source ZIPs, screenshots and recordings are retained in the owner's local gallery; the public repository does not host that gallery. Summary raw-report hashes and source-manifest hashes provide a check against the retained evidence. Functional checks do not rate design or establish general model superiority.
