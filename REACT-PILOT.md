# GPT React pilot

This pilot compares `gpt-6-astra` and `gpt-6.1-sol` on the same React website task. Each model runs alone and with one Jev offload decision, five times per combination: 20 independent builds. Both GPT models use `xhigh`, a 900-second timeout and the same starter, pinned dependencies, local video, task prompt and motion reference. Claude is not invoked. The reference document was copied from an installed motion-design skill; it is static input available to both models.

Status: all 20 active attempts completed on 2026-10-23: 16 successes, three timeouts and one mobile-overflow failure. Five service interruptions remain archived separately. See [the results and limitations](docs/REACT-PILOT-RESULTS-2026-10-23.md) and the active run's report.json. This single-task pilot does not establish general model superiority.

The owner subsequently requested three clean reruns of limit-affected cells under the same conditions. The separate revision records 17 successes, two timeouts and one mobile-overflow failure; all original outcomes remain available. See [the rerun results and provenance](docs/REACT-PILOT-RERUN-RESULTS-2026-10-23.md). Two replacements again reached the time budget without explicit quota errors. Do not present revised counts as unchanged first-pass results.

The 2026-09-21 published evidence remains separate. This new workload cannot be compared directly to its small Python and browser-form tasks.

## Prepare

Use Node 22.12+ and Python 3.11+. Install the exact starter lockfile:

```powershell
$BenchRoot = (Get-Location).Path
Set-Location (Join-Path $BenchRoot "tasks/react-site-001/starter")
npm.cmd ci --ignore-scripts --no-audit --no-fund
```

Generate the identical shared clip using Python with Pillow and FFmpeg:

```powershell
Set-Location $BenchRoot
python scripts/create-react-assets.py
```

Use an installed Playwright Node module and Chrome. The browser verifier runs outside candidate workspaces and blocks external browser requests. GPT receives no TypeSafe/API key environment variables. Credentials remain in the local key file; it may contain a bare TypeSafe key or `TYPESAFE_API_KEY=...`. Never commit that file.

## Run

From the repository root, set `TYPESAFE_KEY_FILE` to your private local key file and `PLAYWRIGHT_MODULE` to the absolute path of your installed Playwright Node module. Never commit the key.

```powershell
python -m jev_astra_bench.react_resume `
  --output ./results/react-pilot `
  --key-file $env:TYPESAFE_KEY_FILE `
  --playwright-module $env:PLAYWRIGHT_MODULE
```

The recovery wrapper invokes the frozen generation runner one cell at a time and stops on an explicit service interruption. It resumes missing attempts and refuses changed inputs, duplicate rows and ambiguous interrupted workspaces. Ordinary task failures and timeouts are final outcomes and are not retried or repaired by the evaluator. If infrastructure fails before a response or tool execution, inspect the retained evidence before using the lower-level runner's `--retry-infrastructure` option.

After authentication or quota access is restored, prepare a separate output directory with `python -m jev_astra_bench.react_resume --recover-from OLD --output NEW --prepare-only`. The original directory is untouched. Only incomplete, non-timeout attempts with explicit usage-limit or revoked-token evidence are archived outside the active sample cells. Each replacement starts from the clean starter. The report and gallery retain archived sources, checks and known usage. Active-sample timing excludes interruption time; the interruption totals remain separately available in `report.json`.

Chrome updated from 155.0.8059.80 to 155.0.8059.85 between the first and resumed work. The three retained sources were rechecked without edits in the current browser. Previous manifests, results and artifacts remain in their original directories and in the new run's evaluation history. Prompt, starter, dependencies, model runner, reasoning and timeout did not change.

Evaluator revision 3 accepts native modal-dialog focus moving into browser chrome, as permitted by [W3C technique H102](https://www.w3.org/WAI/WCAG22/Techniques/html/H102), while rejecting focus on background page controls. Focus and video checks reload independently so a dialog failure cannot block the video test. Earlier evaluator results remain in evaluation history. All retained candidates were rechecked without source edits. Compare `model_duration_s` for generation performance; recorded total time includes each attempt's original evaluator, and later recheck time is excluded.

Jev sees only bounded task metadata. It selects one of the existing strategies `edit_then_test`, `inspect_then_edit_test`, `test_only`; the GPT model does the implementation. No Jev call is made in baseline mode. Jev outage stops the matrix instead of silently running a baseline.

## Evidence and limits

Every attempt retains source, a source ZIP, model events, a build log, desktop/mobile/reduced-motion screenshots, desktop/mobile recordings and a verification JSON. The run directory contains the input fingerprints, append-only attempt log, report and HTML gallery. Keep raw events local: they contain workspace paths and generated content.

The verifier checks actual filtering, pricing, FAQ state, form errors/confirmation, modal keyboard containment, video pause, mobile menu, overflow, reduced motion and browser runtime errors. It also rejects changes to protected inputs and dependencies. The untouched starter is a negative calibration; a separate functional fixture is the positive calibration. Neither calibration is scored as a model attempt.

Success describes these external functional checks. It is not an automatic visual quality score, a complete accessibility audit, production acceptance or proof that five repeats remove hallucinations. Inspect every screenshot and recording, retaining all results. Verified API prices are recorded in `docs/react-pilot-pricing-2026-10-18.json`; actual CLI billing and interrupted usage remain unavailable, so the report does not infer a charge from API rates.

Export a complete run with `python scripts/export-react-results.py --run RUN --output EXPORT`. An incomplete export requires the explicit `--partial` flag and retains its incomplete status. It includes screenshots, recordings, source ZIPs, unchanged built sites, the prompt, fingerprints and SHA-256 file hashes. Raw model logs and credentials are excluded. Run `python serve-react-results.py --port 8765` inside the export to browse the gallery and sites on loopback.

Models may leave temporary browser profiles and crash dumps inside their allowed source directory. Keep these in the private raw run; omit corroborated browser-profile directories from the exported source ZIP. `source-export.json` records the original/exported archive hashes and exclusion count. Remaining code and assets retain their exact bytes. Source fingerprints in the raw report still describe the original workspace. Ambiguous profile data blocks export for inspection rather than silently excluding source files.

If the caller disappears after a retained `turn.completed` event but before recording a result, `python -m jev_astra_bench.react_finalize --output RUN --attempt ID --playwright-module MODULE` can finish external verification without another model invocation. It validates runner and dependency fingerprints, preserves partial artifacts, and requires a complete response without a service error. Missing original timing, exit status and Jev decision metadata remain unavailable; group timing statistics are unavailable if any sample lacks timing. Token usage comes from the retained completion event. The recovery is explicitly marked in the row and gallery.

The original pilot security review was `LOCAL_REVIEW`; no external security provider was used. Model generation and verification ran locally. The completed outputs are now available in the [public gallery](https://hqvdvn-cmd.github.io/astra-jev-benchmark/gallery/). Publication relocates static asset URL prefixes for GitHub Pages; it does not repair site behavior. Raw model logs, credentials, source ZIPs and browser profiles remain outside the public gallery. Original unchanged builds remain in the reviewed local export.
