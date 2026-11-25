# Astra + Jev Benchmark (DeepSWE)

**English** | [Русский](README.ru.md)

[![Corpus](https://img.shields.io/badge/corpus-DeepSWE%20pilot--10-22324A)](https://github.com/datacurve-ai/deep-swe)
[![Harness](https://img.shields.io/badge/harness-jev--codex--harness%20%40%20cea6502-22324A)](https://github.com/teo-nex/jev-codex-harness)
[![Result](https://img.shields.io/badge/pass-2%2F4%20jev%20vs%204%2F4%20codex-B3443A)](#apples-to-apples-summary-4-complete-valid-pairs-14)
[![Uncached input](https://img.shields.io/badge/uncached%20input-22.1%C3%97%20baseline-B3443A)](#why-jev-auto-failed-here)
[![Run date](https://img.shields.io/badge/run-2026--11--24-767D88)](evidence/2026-11-24-deepswe-pilot-10-v1/)

A paired test of plain Codex CLI (`openai/gpt-6.2-sol`, `reasoning_effort=high`) against [`teo-nex/jev-codex-harness`](https://github.com/teo-nex/jev-codex-harness) (`jev/auto`), built by **Teo | Nexcore ([@teo-nex](https://github.com/teo-nex))**. Both arms ran the same real repository tasks from the open-source [DeepSWE](https://github.com/datacurve-ai/deep-swe) corpus (Apache-2.0) through `datacurve-pier==0.3.1`, inside isolated `no-network` Docker containers.

> [!IMPORTANT]
> **Verdict.** On 4 complete paired tasks, plain Codex passed **4/4**. `jev/auto` (commit `cea6502`, policy `split-v17-terra6.1-default-sol6.2-hard`) passed **2/4**, sent **22.1× more uncached input tokens** (`9.54M` vs `431k`) and routed **0 of 215** calls to the cheaper `gpt-6.1-terra`. The extra uncached input coincided with the ChatGPT subscription limit (`HTTP 429`) on the first call of task #5, which ended the 10-task pilot early.

<p align="center">
  <img src="docs/images/en/overview-comparison.png" alt="Headline comparison over tasks #1–#4: pass rate 100% (4/4) for Codex vs 50% (2/4) for jev-auto; prompt cache hit 96.7% vs 35.5%; uncached input 431k vs 9.54M (22.1×), about 482k (+11.8%) if the cache were fixed; output tokens 120.9k vs 147.0k (+21.5%); wall time 79.2 vs 83.0 min; agent steps 189 vs 227." width="100%">
</p>

## What the run shows

- **Lower pass rate.** `jev-auto` passed `2/4` (`50%`); plain Codex passed `4/4` (`100%`) on the same 4 completed pairs.
- **Prompt cache collapse.** `jev-auto` hit the prompt cache on `35.5%` of input tokens against `96.7%` for plain Codex. Uncached input rose from `430,976` to `9,539,458` tokens (`22.1×`); per task the ratio ranged from `16.4×` to `27.0×`.
- **No down-routing.** The policy name promises a `gpt-6.1-terra` default, yet all `215/215` calls stayed on `gpt-6.2-sol`. `194` calls (`90.2%`) ran at `high` effort and `21` (`9.8%`) at `medium`.
- **A cache fix alone would not produce savings.** `jev-auto` took more steps (`227` vs `189`), read more prompt tokens (`+11.8%`) and wrote more output tokens (`+21.5%`). With the cache hit rate raised to baseline's `96.74%`, uncached input would still land near `482k`, `11.8%` above baseline, and `7.0%` of calls would still wait out a router timeout.
- **Reasoning tokens were the one metric that went down** (`50,275` vs `56,085`, `−10.4%`), and that drop did not offset the rest.

On hard multi-file repository tasks of DeepSWE difficulty, plain `gpt-6.2-sol (high)` in Codex CLI beat `jev/auto` on pass rate, uncached input, output tokens, steps and total wall time.

## Tested stack

| Component | Exact version / reference |
|---|---|
| Harness under test | [`teo-nex/jev-codex-harness`](https://github.com/teo-nex/jev-codex-harness) by **Teo \| Nexcore** ([@teo-nex](https://github.com/teo-nex)), commit `cea6502c8c968cef34602be4a7247ebda5d5e84c` |
| Jev routing policy | `split-v17-terra6.1-default-sol6.2-hard` (`decision_provider = typesafe`) |
| Baseline (`codex-baseline`) | Plain `codex-cli 0.171.0`, `openai/gpt-6.2-sol`, `reasoning_effort=high` |
| Treatment (`jev-auto`) | `codex-cli 0.171.0` through `jev-codex-harness` (`jev/auto`) |
| Corpus | [`datacurve-ai/deep-swe`](https://github.com/datacurve-ai/deep-swe), [`tasks/deepswe-pilot-10.json`](tasks/deepswe-pilot-10.json): stratified 10-task pilot (3 Go, 3 TypeScript, 3 Python, 1 Rust) |
| Execution | `datacurve-pier==0.3.1` (`harbor==0.27.0`), Docker Engine, `network_mode = "no-network"` with a Squid allowlist egress proxy |
| Run | 2026-11-24, `deepswe-pilot-10-v1` |

Both arms used the same ChatGPT subscription auth profile, the same pinned offline Linux x64 `codex-cli 0.171.0` binary (with `codex-code-mode-host` and `ripgrep 15.2.0`), and identical per-task Docker images and verifiers.

## Apples-to-apples summary (4 complete valid pairs, #1–#4)

The right column is a projection. It keeps `jev-auto`'s measured prompt tokens, output tokens, steps and test outcomes, and applies the unrounded baseline cache hit rate (`96.74%`) to its prompt tokens. Wall time is left unmodeled because the run gives no clean way to split prefill time from router latency.

| Metric (sum over #1–#4) | `codex-baseline` (`sol high`) | `jev-auto` measured (cache 35.5%) | `jev-auto` with cache at 96.7% (projection) |
|---|---:|---:|---:|
| Valid pairs | 4 | 4 | 4 |
| Pass (`reward=1`) | **4 / 4 (100%)** | 2 / 4 (50%) | 2 / 4 (50%) |
| Mean partial score | `1.0000` | `0.9986` | `0.9986` |
| Wall-clock time | **79.2 min** (`4753.92 s`) | 83.0 min (`4981.62 s`, `+4.8%`) | not modeled |
| Agent steps (ATIF) | **189** | 227 (`+20.1%`) | 227 (`+20.1%`) |
| Total prompt tokens | **13,236,480** | 14,795,778 (`+11.8%`) | 14,795,778 (`+11.8%`) |
| Cached prompt tokens | 12,805,504 (**96.7%**) | 5,256,320 (**35.5%**) | ~14,314,000 (96.7%) |
| **Uncached input tokens** | **430,976** | **9,539,458 (`22.1×`)** | ~482,000 (`+11.8%`) |
| **Output tokens** | **120,923** | 146,980 (`+21.5%`) | 146,980 (`+21.5%`) |
| Reasoning tokens | 56,085 | 50,275 (`−10.4%`) | 50,275 (`−10.4%`) |
| Calls to `gpt-6.1-terra` | n/a | **0 / 215 (0%)** | **0 / 215 (0%)** |
| Effort split (`high` / `medium`) | 100% / 0% | 90.2% / 9.8% (`194` / `21`) | 90.2% / 9.8% |
| Jev decision sources | n/a | `jev: 128`, `lease: 72`, `technical_fallback: 15` (`7.0%`) | same |

## Per-task results (`deepswe-pilot-10-v1`)

<p align="center">
  <img src="docs/images/en/per-task-breakdown.png" alt="Per-task scorecard for tasks #1–#5. Uncached input per task: #1 76.2k vs 1.93M (25.4×), #2 144.5k vs 2.37M (16.4×), #3 101.1k vs 2.29M (22.7×), #4 109.1k vs 2.94M (27.0×). jev-auto failed #2 (F2P 77/79) and #4 (P2P 164/165); on #5 Codex failed with F2P 45/49 and jev-auto stopped on HTTP 429." width="100%">
</p>

| # | Task | Lang | Mode | Valid | Reward | F2P | P2P | Time (s) | Prompt / Cache % | Uncached In | Output / Reas | Jev telemetry |
|---:|---|---|---|---:|---:|---|---|---:|---|---:|---|---:|
| 1 | `abs-module-cache-flags` | go | `codex-baseline` | yes | **1** | 20/20 | 3/3 | 771.24 | 2.66M / 97.1% | 76.2k | 27.5k / 13.6k | n/a |
| 1 | `abs-module-cache-flags` | go | `jev-auto` | yes | **1** | 20/20 | 3/3 | 1070.03 | 2.75M / 29.6% | 1.93M | 36.7k / 11.5k | `sol:47`, `high:42/med:5`, `lease:18`, `timeout:1`, `avg 1200ms` |
| 2 | `expr-try-catch-errors` | go | `codex-baseline` | yes | **1** | 79/79 | 66265/66265 | 1391.23 | 4.23M / 96.6% | 144.5k | 36.4k / 18.3k | n/a |
| 2 | `expr-try-catch-errors` | go | `jev-auto` | yes | **0** | 77/79 | 66265/66265 | 1407.12 | 3.59M / 34.1% | 2.37M | 38.0k / 13.8k | `sol:50`, `high:45/med:5`, `lease:11`, `timeout:4`, `avg 1555ms` |
| 3 | `scc-bounded-memory-spilling` | go | `codex-baseline` | yes | **1** | 31/31 | 286/286 | 1144.94 | 3.82M / 97.4% | 101.1k | 35.6k / 14.7k | n/a |
| 3 | `scc-bounded-memory-spilling` | go | `jev-auto` | yes | **1** | 31/31 | 286/286 | 1322.10 | 3.50M / 34.4% | 2.29M | 41.0k / 14.7k | `sol:53`, `high:49/med:4`, `lease:27`, `timeout:4`, `avg 1753ms` |
| 4 | `happy-dom-abort-pending-body-reads` | ts | `codex-baseline` | yes | **1** | 14/14 | 165/165 | 1446.51 | 2.53M / 95.7% | 109.1k | 21.4k / 9.5k | n/a |
| 4 | `happy-dom-abort-pending-body-reads` | ts | `jev-auto` | yes | **0** | 14/14 | **164/165** | 1182.37 | 4.95M / 40.6% | 2.94M | 31.3k / 10.3k | `sol:65`, `high:58/med:7`, `lease:16`, `timeout:6`, `avg 1665ms` |
| 5 | `meriyah-explicit-resource-declarations` | ts | `codex-baseline` | yes | **0** | 45/49 | 51469/51469 | 1251.19 | 3.08M / 96.4% | 111.2k | 16.1k / 6.4k | n/a |
| 5 | `meriyah-explicit-resource-declarations` | ts | `jev-auto` | no | 0 | 0/49 | n/a | 150.03 | 0 / n/a | 0 | 0 / 0 | `HTTP 429` usage limit on call #1 (`quota_fallback_detected`) |
| 6–10 | `arktype`, `mashumaro`, `fastapi`, `vulture`, `oxvg` | ts/py/rs | both | pending | n/a | n/a | n/a | n/a | n/a | n/a | n/a | Pilot stopped cleanly at the quota limit |

## Why `jev-auto` failed here

<p align="center">
  <img src="docs/images/en/routing-diagnostics.png" alt="Routing telemetry over 215 jev-auto calls: 215/215 on gpt-6.2-sol and 0 on gpt-6.1-terra; effort high on 194 (90.2%) and medium on 21 (9.8%); decision sources jev 128 (59.5%), lease 72 (33.5%), TimeoutExpired fallback 15 (7.0%); mean Jev decision time per task 1200.2, 1554.9, 1752.8 and 1664.7 ms." width="100%">
</p>

Post-run code inspection of `jev-codex-harness @ cea6502` and a follow-up 30-call live validation on `abs-module-cache-flags` (`exp-sticky-catalog-v1`, 2026-11-26) identified the mechanisms behind the telemetry:

1. **Prompt cache collapse (`35.5%` vs `96.7%`) — sticky-routing headers stripped across proxy hops.**
   In `server/jev_server.py` (`Handler._forward`, lines `2826`, `2936–2939`, `3095–3098`), incoming Codex sticky headers (`x-codex-turn-state`, `session_id`, `x-client-request-id`, etc.) are omitted when building the request to `router.mjs`, and upstream `x-codex-turn-state` is omitted on SSE and JSON responses. Static code inspection shows the full installed chain (`router.mjs :4202 → LiteLLM :4200 → api-forwarder.mjs :4203 → jev_server.py :4319 → router.mjs :4202`) also omits client headers in `router/src/router.mjs` (`routedHeaders()`, line `990`), passes through LiteLLM (`:4200`) without sticky-header passthrough, and strips `x-codex-*` and `originator` in `router/src/api-forwarder.mjs` (`upstreamHeaders()`, lines `1535` and `1537`).
2. **Cache-hit drop when `TimeoutExpired` forces `effort="medium"`.**
   When the router's 4-second decision call fails with an exception (`jev_error:TimeoutExpired`, `15 / 215` calls in `v1`), `server/jev_server.py:2327` falls back to `SOL, "medium", "default"`. In the live validation below, switching `high → medium` on timeout call #16 dropped cache hit from `98.1%` (#15) to `8.2%` (`3,968` cached / `44,322` uncached); returning to `high` on #17 immediately hit `99.1%`, and the second timeout (#26, `medium`) hit `84.9%` (`48,256` cached, matching #16's `48,290`-token input length; `8,550` uncached). Those two timeout calls alone accounted for **`45.3%` (`52,872 / 116,615`)** of all uncached input across the 30 calls.
3. **Zero down-routing to `gpt-6.1-terra` (`0 / 215` in `v1`, `0 / 30` in validation).**
   Under `split-v17-terra6.1-default-sol6.2-hard`, `server/routing_policy.py:190–198` applies `confidence_hold` unless `astra_conf >= 0.90` and model confidence `>= 0.90` (with a Terra-specific exception only when `P(sol) <= 0.10`, and no such exception for Luna). In `v1`, `confidence_hold` held all `50 / 50` non-`sol` proposals (`48` Terra, `2` Luna). On `abs-module-cache-flags`, `P(sol)` ranged `0.36–0.85` across the full 47-call `v1` run (4 `confidence_hold` holds on calls 31–47) and `0.55–0.84` across the 18 Jev-scored calls of `exp-sticky-catalog-v1`.
4. **Router latency and timeouts (`15 / 215` = `7.0%`).**
   Mean Jev decision time per task ranged from `1200.2 ms` to `1752.8 ms` in `v1` (`539–608 ms` on 15 fast calls, `3715–3737 ms` on 3 slow successes, and `4034–4061 ms` on 2 timeouts in validation).

### Follow-up 30-call live validation (`abs-module-cache-flags`, `jev-auto`)

Using the benchmark's direct ingress topology (`Codex CLI → TCP bridge → jev_server.py :4319 → router.mjs :4202`), we tested an uncommitted local diff in `server/jev_server.py` forwarding Codex sticky request/response headers when `not external`, combined with copying official `codex-router/merged-models.json` into the agent image (`exp-sticky-catalog-v1`, first 30 completed Responses API calls before the 600s host command cutoff). Both changes were enabled together without separate ablation:

| Metric (first 30 Responses API calls of `abs-module-cache-flags`, `jev-auto`) | `deepswe-pilot-10-v1` (unpatched `cea6502`, no catalog) | `exp-sticky-catalog-v1` (sticky-header diff + `merged-models.json`) |
|---|---:|---:|
| Total input tokens | `1,390,318` | `1,331,079` |
| Cached input tokens (**cache hit %**) | `428,032` (**30.8%**) | `1,214,464` (**91.2%**, `94.8%` on 28 `high` calls, peak `99.8%`) |
| **Uncached input tokens** | **`962,286`** | **`116,615`** (`8.25×` less; `63,743` excluding 2 timeout fallbacks) |
| Output tokens | `28,171` | `19,174` (`−31.9%`) |
| `Model metadata for jev/auto not found` warning | present | absent |
| Native `apply_patch` tool calls (`file_change` items) | `0` native (`8` `file_change` via `exec_command`) | `7` native (`7` `file_change`, `0` via `exec_command`) |
| Calls routed to `gpt-6.1-terra` | `0 / 30` | `0 / 30` (`28 high`, `2 medium` on `TimeoutExpired`) |

## Scope and limits

- **Benchmark harness wiring caveat in `v1` (fixed after the pilot).** In `deepswe-pilot-10-v1`, the runner connected `jev-auto` directly to `jev_server.py:4319` (bypassing `router.mjs :4202 → LiteLLM :4200 → api-forwarder.mjs :4203` on ingress) and did not copy `codex-router/merged-models.json` into the container. As a result, `codex-cli 0.171.0` fell back to generic metadata (`20,751`-char base instructions, no native `apply_patch` tool, and `44` nonempty reasoning summaries in the `abs-module-cache-flags` rollout vs `0` in `exp-sticky-catalog-v1`). The runner in this repository now copies the official `merged-models.json` catalog into the agent image and sets `model_catalog_json` by default (`--jev-model-catalog`). Note that upstream `catalog.mjs` for `jev/auto` still omits `tool_mode = "code_mode_only"` and sets `supports_parallel_tool_calls = false` relative to native `gpt-6.2-sol`.
- **Small sample and combined validation.** `N = 4` complete valid pairs, plus one valid baseline run on task #5. The subscription quota hit `HTTP 429` on task #5; token volume telemetry shows a `22.1×` uncached-input increase, though subscription quota accounting is opaque. The 30-call follow-up validation changed sticky headers and the model catalog together (so the `−31.9%` output drop likely reflects disabling reasoning summaries and restoring native `apply_patch` alongside different agent steps), and was stopped by the 600s host command timeout before verifier scoring (no full-task reward was computed).
- **Close test margins.** Both failed `jev-auto` tasks came close to passing (`77/79` F2P on #2; `14/14` F2P with one `164/165` P2P regression on #4). Treat the `50%` vs `100%` pass-rate gap as a 4-task observation with wide variance.
- **The token-usage result rests on telemetry from all 215 calls**: `0/215` on `gpt-6.1-terra`, `90.2%` at `high`, output tokens `+21.5%`, cache hit rate down `61.2` percentage points.
- **One workload, one commit.** Results cover hard multi-file SWE tasks under `jev-codex-harness` commit `cea6502` with policy `split-v17-terra6.1-default-sol6.2-hard`. A mixed workload of many trivial prompts routed whole-task to a cheaper model, with a working prompt cache, was not tested.
- **The projection column is arithmetic, not a run.** It applies the unrounded baseline cache hit rate (`96.744%`, giving `~482k`; literal `96.7%` gives `~488k`) and assumes the same test outcomes, steps and output volume after a cache fix.

## Evidence and verification

Redacted run artifacts live in [`evidence/2026-11-24-deepswe-pilot-10-v1/`](evidence/2026-11-24-deepswe-pilot-10-v1/):

- [`summary.json`](evidence/2026-11-24-deepswe-pilot-10-v1/summary.json): per-task rewards, ATIF token totals and Jev routing counters. Local filesystem mount prefixes are stripped; it contains no credentials, prompts or raw model output.
- [`summary.md`](evidence/2026-11-24-deepswe-pilot-10-v1/summary.md): rendered per-task and aggregate tables.
- [`manifest.json`](evidence/2026-11-24-deepswe-pilot-10-v1/manifest.json): environment versions and SHA-256 digests of `summary.json` and `summary.md`.

Check the digests and run the unit tests (no API spend):

```bash
sha256sum evidence/2026-11-24-deepswe-pilot-10-v1/summary.json evidence/2026-11-24-deepswe-pilot-10-v1/summary.md
python -m unittest discover -s tests -v
```

Every number in the charts is computed from `summary.json` by [`scripts/render_charts.py`](scripts/render_charts.py). To print the computed metrics or rebuild the PNGs:

```bash
python scripts/render_charts.py --print-metrics   # numbers only, no browser needed
pip install playwright && python -m playwright install chromium
python scripts/render_charts.py                   # writes docs/images/{en,ru}/*.png
```

## Repository layout

```text
jev_astra_bench/          DeepSWE Pier adapter, TCP bridge, paired runner and report builder
scripts/                  PowerShell/WSL2 wrappers and a zero-cost mock Responses API check
scripts/render_charts.py  Chart renderer: summary.json -> HTML/SVG -> 2x PNG via Playwright
docs/images/en/, ru/      Rendered charts used in README.md and README.ru.md
tasks/                    deepswe-pilot-10.json, the stratified 10-task manifest
tests/                    Unit tests for the manifest, Squid proxy compose, bridge and reporting
evidence/                 Redacted 2026-11-24 pilot summary and SHA-256 manifest
```

## Credits

`jev-codex-harness` and the Jev router are the work of **Teo | Nexcore ([@teo-nex](https://github.com/teo-nex))**. This benchmark tests one commit (`cea6502`) and one policy on one workload, and the per-task evidence is published so the result can be checked and rerun against later versions. DeepSWE tasks come from [`datacurve-ai/deep-swe`](https://github.com/datacurve-ai/deep-swe) (Apache-2.0).
