# DeepSWE Paired Benchmark Summary — `deepswe-pilot-10-v1`

- Manifest: `deepswe-pilot-10`
- Updated: `2026-11-24T17:58:26Z`
- Modes: `codex-baseline`, `jev-auto`

## Per-Task Paired Results

| # | Task | Lang | Mode | Valid | Reward | F2P | Partial | Time (s) | Prompt Tok | Cached Tok | Output Tok | Jev Routes |
|---:|---|---|---|---|---:|---|---:|---:|---:|---:|---:|---|
| 1 | `abs-module-cache-flags` | go | `codex-baseline` | yes | 1 | 20/20 | 1.00 | 771.24 | 2659608 | 2583424 | 27522 | — |
| 1 | `abs-module-cache-flags` | go | `jev-auto` | yes | 1 | 20/20 | 1.00 | 1070.03 | 2748717 | 814976 | 36711 | gpt-6.2-sol:47 |
| 2 | `expr-try-catch-errors` | go | `codex-baseline` | yes | 1 | 79/79 | 1.00 | 1391.23 | 4225951 | 4081408 | 36350 | — |
| 2 | `expr-try-catch-errors` | go | `jev-auto` | yes | 0 | 77/79 | 1.00 | 1407.12 | 3593629 | 1224704 | 38029 | gpt-6.2-sol:50 |
| 3 | `scc-bounded-memory-spilling` | go | `codex-baseline` | yes | 1 | 31/31 | 1.00 | 1144.94 | 3821436 | 3720320 | 35604 | — |
| 3 | `scc-bounded-memory-spilling` | go | `jev-auto` | yes | 1 | 31/31 | 1.00 | 1322.10 | 3499003 | 1204352 | 40961 | gpt-6.2-sol:53 |
| 4 | `happy-dom-abort-pending-body-reads` | typescript | `codex-baseline` | yes | 1 | 14/14 | 1.00 | 1446.51 | 2529485 | 2420352 | 21447 | — |
| 4 | `happy-dom-abort-pending-body-reads` | typescript | `jev-auto` | yes | 0 | 14/14 | 0.99 | 1182.37 | 4954429 | 2012288 | 31279 | gpt-6.2-sol:65 |
| 5 | `meriyah-explicit-resource-declarations` | typescript | `codex-baseline` | yes | 0 | 45/49 | 1.00 | 1251.19 | 3077358 | 2966144 | 16096 | — |
| 5 | `meriyah-explicit-resource-declarations` | typescript | `jev-auto` | no (quota_fallback_detected) | 0 | 0/49 | 1.00 | 150.03 | 0 | 0 | 0 | gpt-6.2-sol:1 [FALLBACK] |
| 6 | `arktype-json-schema-refs-dependencies` | typescript | `codex-baseline` | pending | — | — | — | — | — | — | — | — |
| 6 | `arktype-json-schema-refs-dependencies` | typescript | `jev-auto` | pending | — | — | — | — | — | — | — | — |
| 7 | `mashumaro-flattened-dataclass-fields` | python | `codex-baseline` | pending | — | — | — | — | — | — | — | — |
| 7 | `mashumaro-flattened-dataclass-fields` | python | `jev-auto` | pending | — | — | — | — | — | — | — | — |
| 8 | `fastapi-implicit-head-options` | python | `codex-baseline` | pending | — | — | — | — | — | — | — | — |
| 8 | `fastapi-implicit-head-options` | python | `jev-auto` | pending | — | — | — | — | — | — | — | — |
| 9 | `vulture-persistent-analysis-cache` | python | `codex-baseline` | pending | — | — | — | — | — | — | — | — |
| 9 | `vulture-persistent-analysis-cache` | python | `jev-auto` | pending | — | — | — | — | — | — | — | — |
| 10 | `oxvg-structural-selector-preservation` | rust | `codex-baseline` | pending | — | — | — | — | — | — | — | — |
| 10 | `oxvg-structural-selector-preservation` | rust | `jev-auto` | pending | — | — | — | — | — | — | — | — |

## Aggregate by Mode

| Mode | Completed | Valid | Pass (reward=1) | Mean Partial | Total Prompt Tok | Total Cached Tok | Total Output Tok |
|---|---:|---:|---:|---:|---:|---:|---:|
| `codex-baseline` | 5 | 5 | 4 | 1.00 | 16313838 | 15771648 | 137019 |
| `jev-auto` | 5 | 4 | 2 | 1.00 | 14795778 | 5256320 | 146980 |
