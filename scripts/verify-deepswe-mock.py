"""Zero-cost end-to-end verification of the DeepSWE + Pier + Codex + Squid stack.

Runs inside Linux/WSL2 against a real DeepSWE task container (default:
``abs-module-cache-flags``) with ``network_mode = "no-network"``:
1. Starts a local mock OpenAI Responses SSE server on ``127.0.0.1:18088``.
2. Starts ``deepswe_bridge`` on ``172.17.0.1`` forwarding the mock Responses API.
3. Runs real ``pier run --agent codex --environment-import-path
   jev_astra_bench.deepswe_env:JevbenchDockerEnvironment`` pointing ``config.toml``
   at ``http://host.docker.internal:18088/v1`` with ``OPENAI_API_KEY=mock-jev-secret``.
4. Verifies:
   - Real Codex CLI reached the host mock server through Squid egress proxy with
     ``model = "jev/auto"`` and ``Authorization: Bearer mock-jev-secret``.
   - The secret did NOT leak into Pier's ``lock.json`` or ``config.json``.
   - Pier extracted ATIF ``agent/trajectory.json`` with token usage.
   - Separate ``no-network`` verifier ran cleanly and emitted ``verifier/reward.json``.
"""

from __future__ import annotations

import http.server
import json
import os
import socketserver
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

BENCH_ROOT = Path(__file__).resolve().parent.parent
if str(BENCH_ROOT) not in sys.path:
    sys.path.insert(0, str(BENCH_ROOT))

from jev_astra_bench.deepswe_report import (  # noqa: E402
    extract_trial_summary,
    find_latest_trial_dir,
)
from jev_astra_bench.deepswe_runner import (  # noqa: E402
    ENV_IMPORT_PATH,
    _start_bridge,
    build_jev_codex_config_toml,
)

MOCK_PORT = int(os.environ.get("JEVBENCH_MOCK_PORT", "18088"))
MOCK_SECRET = "mock-jev-secret-zero-cost-check"
TASK_ID = os.environ.get("JEVBENCH_MOCK_TASK_ID", "abs-module-cache-flags")
TASK_DIR = Path(
    os.environ.get("JEVBENCH_DEEPSWE_TASKS_DIR", str(BENCH_ROOT / "deep-swe" / "tasks"))
) / TASK_ID
OUT_DIR = Path(
    os.environ.get(
        "JEVBENCH_MOCK_OUT_DIR",
        str(BENCH_ROOT / "results" / "deepswe-smoke-codex-mock"),
    )
)


class _MockState:
    def __init__(self) -> None:
        self.requests: list[dict[str, Any]] = []


def _make_handler(state: _MockState):
    class MockResponsesHandler(http.server.BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
            pass

        def do_POST(self) -> None:  # noqa: N802
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length > 0 else b"{}"
            try:
                body = json.loads(raw.decode("utf-8", errors="replace"))
            except ValueError:
                body = {}
            auth = self.headers.get("Authorization") or ""
            state.requests.append(
                {
                    "path": self.path,
                    "auth_ok": auth == f"Bearer {MOCK_SECRET}",
                    "model": body.get("model"),
                    "stream": body.get("stream"),
                }
            )
            if auth != f"Bearer {MOCK_SECRET}":
                payload = json.dumps({"error": {"message": "unauthorized"}}).encode()
                self.send_response(401)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
                return

            resp_id = "resp_mock_001"
            item_id = "msg_mock_001"
            created = int(time.time())
            usage = {
                "input_tokens": 123,
                "input_tokens_details": {"cached_tokens": 45},
                "output_tokens": 17,
                "output_tokens_details": {"reasoning_tokens": 7},
                "total_tokens": 140,
            }
            text = "Mock responses smoke check completed."
            events = [
                {
                    "type": "response.created",
                    "response": {
                        "id": resp_id,
                        "object": "response",
                        "created_at": created,
                        "status": "in_progress",
                        "model": body.get("model") or "jev/auto",
                        "output": [],
                    },
                },
                {
                    "type": "response.output_item.added",
                    "output_index": 0,
                    "item": {
                        "id": item_id,
                        "type": "message",
                        "role": "assistant",
                        "status": "in_progress",
                        "content": [],
                    },
                },
                {
                    "type": "response.content_part.added",
                    "item_id": item_id,
                    "output_index": 0,
                    "content_index": 0,
                    "part": {"type": "output_text", "text": "", "annotations": []},
                },
                {
                    "type": "response.output_text.delta",
                    "item_id": item_id,
                    "output_index": 0,
                    "content_index": 0,
                    "delta": text,
                },
                {
                    "type": "response.output_text.done",
                    "item_id": item_id,
                    "output_index": 0,
                    "content_index": 0,
                    "text": text,
                },
                {
                    "type": "response.content_part.done",
                    "item_id": item_id,
                    "output_index": 0,
                    "content_index": 0,
                    "part": {"type": "output_text", "text": text, "annotations": []},
                },
                {
                    "type": "response.output_item.done",
                    "output_index": 0,
                    "item": {
                        "id": item_id,
                        "type": "message",
                        "role": "assistant",
                        "status": "completed",
                        "content": [
                            {"type": "output_text", "text": text, "annotations": []}
                        ],
                    },
                },
                {
                    "type": "response.completed",
                    "response": {
                        "id": resp_id,
                        "object": "response",
                        "created_at": created,
                        "status": "completed",
                        "model": body.get("model") or "jev/auto",
                        "output": [
                            {
                                "id": item_id,
                                "type": "message",
                                "role": "assistant",
                                "status": "completed",
                                "content": [
                                    {
                                        "type": "output_text",
                                        "text": text,
                                        "annotations": [],
                                    }
                                ],
                            }
                        ],
                        "usage": usage,
                    },
                },
            ]
            sse_chunks = []
            for ev in events:
                sse_chunks.append(
                    f"event: {ev['type']}\ndata: {json.dumps(ev)}\n\n".encode("utf-8")
                )
            blob = b"".join(sse_chunks)
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Content-Length", str(len(blob)))
            self.end_headers()
            self.wfile.write(blob)

    return MockResponsesHandler


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    cfg_path = OUT_DIR / "mock-codex-config.toml"
    cfg_path.write_text(
        build_jev_codex_config_toml(
            jev_base_url=f"http://host.docker.internal:{MOCK_PORT}/v1"
        ),
        encoding="utf-8",
    )

    state = _MockState()

    class _ReuseTCPServer(socketserver.ThreadingTCPServer):
        allow_reuse_address = True
        daemon_threads = True

    server = _ReuseTCPServer(("127.0.0.1", MOCK_PORT), _make_handler(state))
    srv_thread = threading.Thread(target=server.serve_forever, daemon=True)
    srv_thread.start()

    bridge = _start_bridge(
        bind_host="172.17.0.1",
        mappings=["2081:2080", f"{MOCK_PORT}:{MOCK_PORT}"],
        bench_root=BENCH_ROOT,
    )
    try:
        env = dict(os.environ)
        env["PYTHONPATH"] = str(BENCH_ROOT) + (
            ":" + env["PYTHONPATH"] if env.get("PYTHONPATH") else ""
        )
        env["OPENAI_API_KEY"] = MOCK_SECRET
        env.pop("CODEX_AUTH_JSON_PATH", None)
        env.pop("CODEX_FORCE_AUTH_JSON", None)
        env["JEVBENCH_EXTRA_SAFE_PORTS"] = f"4319,4202,{MOCK_PORT}"

        cmd = [
            "pier",
            "run",
            "-p",
            str(TASK_DIR),
            "--agent",
            "codex",
            "--model",
            "jev/auto",
            "--ak",
            "command_model_name=jev/auto",
            "--ak",
            f"config_toml_file={cfg_path}",
            "--environment-import-path",
            ENV_IMPORT_PATH,
            "--jobs-dir",
            str(OUT_DIR),
        ]
        print("[mock-e2e] Running pier with real Codex CLI against local mock...", flush=True)
        proc = subprocess.run(cmd, env=env, check=False)
        print(f"[mock-e2e] pier exit code: {proc.returncode}", flush=True)
        print(f"[mock-e2e] mock requests captured: {json.dumps(state.requests)}", flush=True)

        trial_dir = find_latest_trial_dir(OUT_DIR, TASK_ID)
        assert trial_dir is not None, "Trial dir not found"
        rec = extract_trial_summary(
            trial_dir,
            mode="jev-auto-mock",
            task_id=TASK_ID,
            returncode=proc.returncode,
        )
        print(f"[mock-e2e] trial summary: {json.dumps(rec, indent=2)}", flush=True)

        # Verify no secret leaked into Pier metadata files
        for meta_name in ("lock.json", "config.json"):
            for mf in OUT_DIR.rglob(meta_name):
                txt = mf.read_text(encoding="utf-8", errors="replace")
                assert MOCK_SECRET not in txt, f"SECRET LEAKED into {mf}"

        assert proc.returncode == 0, f"pier failed with rc={proc.returncode}"
        assert len(state.requests) >= 1, "Mock server received 0 requests from Codex CLI!"
        assert all(r["auth_ok"] for r in state.requests), "Auth header mismatch"
        assert any(r["model"] == "jev/auto" for r in state.requests), "Model mismatch"
        assert rec["valid"], f"Trial marked invalid: {rec['invalid_reason']}"
        assert rec["tokens"]["present"], "ATIF trajectory.json missing"
        assert rec["tokens"]["prompt_tokens"] >= 123, "Prompt tokens not recorded in ATIF"
        assert rec["tokens"]["cached_tokens"] >= 45, "Cached tokens not recorded in ATIF"
        print("MOCK_E2E_VERIFIED_OK", flush=True)
        return 0
    finally:
        bridge.terminate()
        try:
            bridge.wait(timeout=5)
        except subprocess.TimeoutExpired:
            bridge.kill()
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    sys.exit(main())
