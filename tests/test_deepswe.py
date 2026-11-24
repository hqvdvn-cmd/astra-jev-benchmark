"""Unit tests for the DeepSWE Pier adapter, TCP bridge, manifest, and paired report."""

from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from pathlib import Path

from jev_astra_bench.deepswe_bridge import LocalTcpBridge, PortMapping, parse_mapping
from jev_astra_bench.deepswe_env import (
    DEFAULT_EXTRA_ALLOW_DOMAINS,
    build_main_build_override_dict,
    build_squid_bootstrap_script,
    merge_allowlist_domains,
    resolve_default_codex_binary_dir,
    write_cached_codex_dockerfile,
    write_jevbench_proxy_compose,
)
from jev_astra_bench.deepswe_report import (
    compute_aggregate,
    extract_trial_summary,
    find_latest_trial_dir,
    render_markdown_summary,
)
from jev_astra_bench.deepswe_runner import (
    build_jev_codex_config_toml,
    build_pier_command,
    expected_harness_policy_version,
    load_manifest,
    read_jev_caller_secret,
    resolve_jev_state_dir,
)

REPO_ROOT = Path(__file__).resolve().parent.parent


class TestDeepSweManifest(unittest.TestCase):
    def test_pilot_10_manifest_stratification(self) -> None:
        manifest_path = REPO_ROOT / "tasks" / "deepswe-pilot-10.json"
        data = load_manifest(manifest_path)
        tasks = data["tasks"]
        self.assertEqual(len(tasks), 10)
        self.assertEqual(tasks[0]["task_id"], "abs-module-cache-flags")
        self.assertTrue(tasks[0]["canary"])
        langs = {}
        for t in tasks:
            langs[t["language"]] = langs.get(t["language"], 0) + 1
            self.assertEqual(t["agent_network_mode"], "no-network")
            self.assertEqual(t["verifier_network_mode"], "no-network")
        self.assertEqual(langs, {"go": 3, "typescript": 3, "python": 3, "rust": 1})
        self.assertEqual(
            data["target_comparison"]["baseline"]["model"], "openai/gpt-6.2-sol"
        )
        self.assertEqual(
            data["target_comparison"]["treatment"]["policy_version"],
            "split-v17-terra6.1-default-sol6.2-hard",
        )


class TestDeepSweEnvHelpers(unittest.TestCase):
    def test_squid_script_allows_extra_ports_and_routes_external_via_peer(self) -> None:
        script = build_squid_bootstrap_script(
            extra_safe_ports=[4319, 18080],
            upstream_proxy_host="host.docker.internal",
            upstream_proxy_port=2081,
        )
        self.assertIn("acl Safe_ports port 80 443 4319 18080", script)
        self.assertIn("acl direct_hosts dstdomain host.docker.internal", script)
        self.assertIn(
            "cache_peer host.docker.internal parent 2081 0 no-query default", script
        )
        self.assertIn("always_direct allow direct_hosts", script)
        self.assertIn("never_direct allow !direct_hosts", script)

    def test_merge_allowlist_and_compose_files(self) -> None:
        merged = merge_allowlist_domains(["api.openai.com"], DEFAULT_EXTRA_ALLOW_DOMAINS)
        self.assertEqual(
            merged,
            [
                "api.openai.com",
                "auth.openai.com",
                "chatgpt.com",
                "host.docker.internal",
            ],
        )
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            compose_path = write_jevbench_proxy_compose(
                path=tmp_path / "docker-compose-egress-proxy.json",
                proxy_dir=tmp_path / "egress-proxy",
                allowlist_domains=merged,
                token="tok123",
                extra_safe_ports=[4319],
                upstream_proxy_port=2081,
                build_proxy="http://127.0.0.1:2080",
            )
            compose = json.loads(compose_path.read_text(encoding="utf-8"))
            proxy_svc = compose["services"]["pier-egress-proxy"]
            self.assertEqual(
                proxy_svc["extra_hosts"], ["host.docker.internal:host-gateway"]
            )
            self.assertEqual(proxy_svc["build"]["network"], "host")
            self.assertEqual(
                proxy_svc["build"]["args"]["http_proxy"], "http://127.0.0.1:2080"
            )
            self.assertTrue(compose["networks"]["pier-egress-internal"]["internal"])

        main_override = build_main_build_override_dict("http://127.0.0.1:2080")
        self.assertEqual(main_override["services"]["main"]["build"]["network"], "host")

    def test_cached_codex_dockerfile_injects_local_binaries(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            fake_codex = tmp_path / "codex"
            fake_rg = tmp_path / "rg"
            fake_cmh = tmp_path / "codex-code-mode-host"
            fake_codex.write_bytes(b"ELF-codex")
            fake_rg.write_bytes(b"ELF-rg")
            fake_cmh.write_bytes(b"ELF-cmh")
            build_dir = tmp_path / "ctx"
            df = write_cached_codex_dockerfile(
                build_dir=build_dir,
                prebuilt_image_name="example/task:v1",
                fingerprint="fp-123",
                codex_binary=fake_codex,
                rg_binary=fake_rg,
                code_mode_host_binary=fake_cmh,
            )
            txt = df.read_text(encoding="utf-8")
            self.assertIn("FROM example/task:v1", txt)
            self.assertIn("COPY .jevbench-codex-bin/codex /usr/local/bin/codex", txt)
            self.assertIn("COPY .jevbench-codex-bin/rg /usr/local/bin/rg", txt)
            self.assertIn(
                "COPY .jevbench-codex-bin/codex-code-mode-host /usr/local/bin/codex-code-mode-host",
                txt,
            )
            self.assertTrue((build_dir / ".jevbench-codex-bin" / "codex").is_file())
            self.assertTrue((build_dir / ".jevbench-codex-bin" / "rg").is_file())
            self.assertTrue(
                (build_dir / ".jevbench-codex-bin" / "codex-code-mode-host").is_file()
            )

    def test_resolve_default_codex_binary_dir_prefers_first_existing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            missing = tmp_path / "missing"
            present = tmp_path / "present"
            present.mkdir()
            (present / "codex").write_bytes(b"ELF")
            chosen = resolve_default_codex_binary_dir((str(missing), str(present)))
            self.assertEqual(chosen, str(present))


class TestDeepSweRunnerHelpers(unittest.TestCase):
    def test_jev_config_toml_uses_env_key_without_leaking_secret(self) -> None:
        toml_text = build_jev_codex_config_toml(
            jev_base_url="http://host.docker.internal:4319/v1"
        )
        self.assertIn('model = "jev/auto"', toml_text)
        self.assertIn('wire_api = "responses"', toml_text)
        self.assertIn('base_url = "http://host.docker.internal:4319/v1"', toml_text)
        self.assertIn('env_key = "OPENAI_API_KEY"', toml_text)
        self.assertIn("requires_openai_auth = false", toml_text)

    def test_build_pier_command_modes(self) -> None:
        base_cmd = build_pier_command(
            task_dir=Path("/tasks/foo"),
            jobs_dir=Path("/results/foo/base"),
            mode="codex-baseline",
            baseline_model="openai/gpt-6.2-sol",
            baseline_effort="high",
        )
        self.assertIn("--environment-import-path", base_cmd)
        self.assertIn("openai/gpt-6.2-sol", base_cmd)
        self.assertIn("reasoning_effort=high", base_cmd)

        jev_cmd = build_pier_command(
            task_dir=Path("/tasks/foo"),
            jobs_dir=Path("/results/foo/jev"),
            mode="jev-auto",
            baseline_model="openai/gpt-6.2-sol",
            baseline_effort="high",
            jev_config_toml_path=Path("/tmp/jev.toml"),
        )
        self.assertIn("jev/auto", jev_cmd)
        self.assertIn("command_model_name=jev/auto", jev_cmd)
        self.assertIn("config_toml_file=/tmp/jev.toml", jev_cmd)

    def test_harness_policy_version_parser(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            srv = Path(tmp) / "server"
            srv.mkdir()
            (srv / "routing_policy.py").write_text(
                'POLICY_VERSION = "split-v17-terra6.1-default-sol6.2-hard"\n',
                encoding="utf-8",
            )
            self.assertEqual(
                expected_harness_policy_version(Path(tmp)),
                "split-v17-terra6.1-default-sol6.2-hard",
            )

    def test_resolve_jev_state_dir_accepts_codex_home_or_router_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "jev-codex-home"
            creds = home / "codex-router" / "generic-provider-credentials"
            creds.mkdir(parents=True)
            (creds / "jev.key").write_text("local-caller-token\n", encoding="utf-8")
            self.assertEqual(resolve_jev_state_dir(home), home / "codex-router")
            self.assertEqual(
                resolve_jev_state_dir(home / "codex-router"), home / "codex-router"
            )
            self.assertEqual(read_jev_caller_secret(home), "local-caller-token")


class TestDeepSweReport(unittest.TestCase):
    def test_find_latest_trial_dir_handles_pier_32_char_truncation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            job_dir = Path(tmp) / "2026-11-24__19-31-52"
            truncated = job_dir / "happy-dom-abort-pending-body-rea__NKw48LW"
            (truncated / "verifier").mkdir(parents=True)
            (truncated / "verifier" / "reward.json").write_text(
                '{"reward": 1}\n', encoding="utf-8"
            )
            found = find_latest_trial_dir(
                Path(tmp), "happy-dom-abort-pending-body-reads"
            )
            self.assertEqual(found, truncated)

    def test_extract_trial_summary_and_quota_fallback_invalidation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            trial_dir = Path(tmp) / "abs-module-cache-flags__abc"
            (trial_dir / "verifier").mkdir(parents=True)
            (trial_dir / "agent").mkdir(parents=True)
            (trial_dir / "result.json").write_text(
                json.dumps(
                    {
                        "started_at": "2026-11-23T19:00:00Z",
                        "finished_at": "2026-11-23T19:01:30Z",
                        "exception_info": None,
                    }
                ),
                encoding="utf-8",
            )
            (trial_dir / "verifier" / "reward.json").write_text(
                json.dumps(
                    {
                        "reward": 1,
                        "f2p_passed": 20,
                        "f2p_total": 20,
                        "p2p_passed": 3,
                        "p2p_total": 3,
                        "partial": 1.0,
                    }
                ),
                encoding="utf-8",
            )
            (trial_dir / "agent" / "trajectory.json").write_text(
                json.dumps(
                    {
                        "steps": [{"step_id": 1}],
                        "final_metrics": {
                            "total_prompt_tokens": 12000,
                            "total_cached_tokens": 8000,
                            "total_completion_tokens": 1500,
                            "extra": {"reasoning_tokens": 600},
                        },
                    }
                ),
                encoding="utf-8",
            )

            clean_rec = extract_trial_summary(
                trial_dir,
                mode="jev-auto",
                task_id="abs-module-cache-flags",
                jev_records=[
                    {
                        "model": "gpt-6.1-terra",
                        "effort": "medium",
                        "decision_source": "jev",
                        "gate": "normal",
                        "policy_version": "split-v17-terra6.1-default-sol6.2-hard",
                        "jev_ms": 180,
                        "status": 200,
                    },
                    {
                        "model": "gpt-6.2-sol",
                        "effort": "high",
                        "decision_source": "lease",
                        "lease_hit": True,
                        "gate": "normal",
                        "status": 200,
                    },
                ],
                returncode=0,
            )
            self.assertTrue(clean_rec["valid"])
            self.assertEqual(clean_rec["duration_sec"], 90.0)
            self.assertEqual(clean_rec["tokens"]["cached_tokens"], 8000)
            self.assertEqual(clean_rec["tokens"]["reasoning_tokens"], 600)
            self.assertEqual(clean_rec["jev_routing"]["lease_hits"], 1)
            self.assertFalse(clean_rec["jev_routing"]["quota_fallback_detected"])

            dry_rec = extract_trial_summary(
                trial_dir,
                mode="jev-auto",
                task_id="abs-module-cache-flags",
                jev_records=[
                    {
                        "model": "deepseek/deepseek-v4.1-flash",
                        "gate": "codex_dry(auto):gpt-6.1-terra",
                        "status": 200,
                    }
                ],
                returncode=0,
            )
            self.assertFalse(dry_rec["valid"])
            self.assertEqual(dry_rec["invalid_reason"], "quota_fallback_detected")

            pairs = [
                {
                    "index": 1,
                    "task_id": "abs-module-cache-flags",
                    "language": "go",
                    "runs": {"jev-auto": clean_rec},
                }
            ]
            agg = compute_aggregate(pairs, ["codex-baseline", "jev-auto"])
            self.assertEqual(agg["jev-auto"]["passed"], 1)
            self.assertEqual(agg["codex-baseline"]["completed"], 0)
            md = render_markdown_summary(
                {
                    "run_name": "test-run",
                    "manifest_name": "deepswe-pilot-10",
                    "updated_at": "2026-11-23T20:00:00Z",
                    "modes": ["codex-baseline", "jev-auto"],
                    "pairs": pairs,
                    "aggregate": agg,
                }
            )
            self.assertIn("abs-module-cache-flags", md)
            self.assertIn("gpt-6.1-terra:1", md)


class TestLocalTcpBridge(unittest.TestCase):
    def test_parse_mapping(self) -> None:
        m = parse_mapping("2081:2080")
        self.assertEqual(m, PortMapping(2081, 2080, "127.0.0.1"))

    def test_bridge_roundtrip_on_loopback(self) -> None:
        async def _scenario() -> bytes:
            async def echo(
                reader: asyncio.StreamReader, writer: asyncio.StreamWriter
            ) -> None:
                data = await reader.read(1024)
                writer.write(b"ECHO:" + data)
                await writer.drain()
                writer.close()
                await writer.wait_closed()

            backend = await asyncio.start_server(echo, "127.0.0.1", 0)
            backend_port = backend.sockets[0].getsockname()[1]

            bridge = LocalTcpBridge("127.0.0.1", [PortMapping(0, backend_port)])
            await bridge.start()
            bridge_port = bridge.bound_ports[backend_port]
            try:
                r, w = await asyncio.open_connection("127.0.0.1", bridge_port)
                w.write(b"hello")
                await w.drain()
                resp = await r.read(1024)
                w.close()
                await w.wait_closed()
                return resp
            finally:
                await bridge.stop()
                backend.close()
                await backend.wait_closed()

        self.assertEqual(asyncio.run(_scenario()), b"ECHO:hello")


if __name__ == "__main__":
    unittest.main()
