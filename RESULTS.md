# Live Astra and Astra + Jev benchmark

**English** | [Русский](RESULTS.ru.md)

Run date: September 21, 2026.

The benchmark completed 45 independent attempts: three tasks, five modes, and three repeats. Every mode used `gpt-6-astra` at `xhigh` reasoning. Luna, Terra, and Sol were not called.

Redacted attempt records, aggregate reports, and checksums are published in [`evidence/2026-09-21-five-mode/`](./evidence/2026-09-21-five-mode/).

## Aggregate result

| Mode | Passed | Mean time | Total cost | Cost per success |
|---|---:|---:|---:|---:|
| Astra | 9/9 | 55.6 s | $3.764 | $0.418 |
| Jev Observe | 9/9 | 63.4 s | $4.534 | $0.504 |
| Jev Offload | 9/9 | 44.1 s | $3.107 | $0.345 |
| Guarded retry | 8/9 | 64.0 s | $4.672 | $0.584 |
| Offload + guard | 9/9 | 44.4 s | $3.214 | $0.357 |

Compared with Astra alone, Jev Offload reduced mean duration by 20.7%, Astra input tokens by 15.1%, and cost per success by 17.5%. Offload + guard reduced the same metrics by 20.1%, 13.2%, and 14.6%.

Observe increased cost per success by 20.5%. Guarded retry increased it by 39.6% and passed 8 of 9 attempts. Jev Offload was the lowest-cost primary mode for this task set. Offload + guard stayed close while adding a final Jev decision.

The estimated cost of the complete series was $19.292.

## Failed attempt

On the third bug-fix repeat, Guarded retry changed both the allowed `clamp.py` and the protected `test_clamp.py`. Local verification rejected the first pass before Jev was called. Astra received `retry_scope`, then changed the protected test again on the second pass. The attempt ended at the two-pass limit.

The scope verifier caught the violation, but the second pass did not correct it. The failed attempt cost $1.161 and took 170 seconds.

## Results by task

| Task | Mode | Passed | Mean time | Cost per success |
|---|---|---:|---:|---:|
| Code writing | Astra | 3/3 | 66.7 s | $0.453 |
| Code writing | Observe | 3/3 | 87.6 s | $0.580 |
| Code writing | Offload | 3/3 | 55.7 s | $0.387 |
| Code writing | Guarded | 3/3 | 68.2 s | $0.456 |
| Code writing | Offload + guard | 3/3 | 58.2 s | $0.470 |
| Bug fixing | Astra | 3/3 | 78.1 s | $0.604 |
| Bug fixing | Observe | 3/3 | 78.3 s | $0.572 |
| Bug fixing | Offload | 3/3 | 62.7 s | $0.480 |
| Bug fixing | Guarded | 2/3 | 102.0 s | $1.241 |
| Bug fixing | Offload + guard | 3/3 | 62.1 s | $0.515 |
| Browser form | Astra | 3/3 | 22.0 s | $0.197 |
| Browser form | Observe | 3/3 | 24.4 s | $0.359 |
| Browser form | Offload | 3/3 | 13.9 s | $0.169 |
| Browser form | Guarded | 3/3 | 21.7 s | $0.274 |
| Browser form | Offload + guard | 3/3 | 12.9 s | $0.086 |

## Cost calculation

The estimate includes uncached, cached, and cache-write Astra input tokens; Astra output tokens; and Jev input tokens. Prices were checked on the run date:

- Astra: <https://developers.openai.com/api/docs/pricing>;
- Jev: <https://typesafe.ai/blog/introducing-system-one-models-and-jev>.

Codex subscription usage may differ from the API-price equivalent.

## Infrastructure outage and resume

The first full run crossed a temporary Astra outage. After seven completed attempts, 38 consecutive Codex processes returned `exit_code=1` without a model response. Those records were classified as infrastructure failures rather than task failures.

The runner now stops on the first infrastructure failure, archives the interrupted journal, and uses `--resume` to run only missing pairs. The published dataset contains 45 unique task-mode-repeat combinations and no infrastructure failures.

## Limits

- Each task-mode pair has three repeats.
- The tasks are synthetic and shorter than real development work.
- The matrix isolates Astra and Jev by disabling user plugins, hooks, apps, memory, and parallel agents.
- The browser task uses a local page without network access or credentials.
- Resuming after the outage split the run across two time windows. Mode rotation was preserved, but service load may have differed.
