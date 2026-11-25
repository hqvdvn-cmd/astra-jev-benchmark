"""Custom Pier DockerEnvironment for JEVBENCH DeepSWE runs inside WSL2.

Handles four host-specific requirements without modifying site-packages:
1. Fast, deterministic offline Codex CLI injection when a pinned Linux x64
   binary is cached in ``JEVBENCH_CODEX_BINARY_DIR`` (seconds per task instead
   of re-downloading nvm + Node + npm on every task image), with fallback to
   build.network=host + build.args proxy when building from scratch. Optionally
   injects an official ``merged-models.json`` catalog for ``jev/auto`` so Codex
   CLI loads real model metadata instead of defaulting to fallback metadata.
2. Runtime isolation preserved: ``main`` stays strictly on the internal Docker
   network (``pier-egress-internal``) and can reach only the Squid policy proxy.
3. Expanded egress allowlist for ChatGPT subscription Codex CLI (``chatgpt.com``,
   ``auth.openai.com``, ``api.openai.com``) and local ``host.docker.internal``
   routing to ``jew-codex-harness`` (``jev_server.py`` on :4319 / ``router.mjs`` on :4202).
4. Upstream Squid ``cache_peer`` forwarding external allowlisted traffic via the
   local Docker-bridge proxy forwarder (``host.docker.internal:2081 -> 127.0.0.1:2080``)
   while routing ``host.docker.internal`` directly (``always_direct``).
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from pathlib import Path
from typing import Any

DEFAULT_BUILD_PROXY = "http://127.0.0.1:2080"
DEFAULT_UPSTREAM_PROXY_HOST = "host.docker.internal"
DEFAULT_UPSTREAM_PROXY_PORT = 2081
CONTAINER_MODEL_CATALOG_PATH = "/usr/local/share/jevbench/merged-models.json"
DEFAULT_CODEX_BINARY_DIRS = (
    "/opt/jevbench-codex-bin",
    "/mnt/e/PROJECT/JEVBENCH/runtime/codex-bin",
)
DEFAULT_EXTRA_ALLOW_DOMAINS = (
    "api.openai.com",
    "auth.openai.com",
    "chatgpt.com",
    "host.docker.internal",
)
DEFAULT_EXTRA_SAFE_PORTS = (4319, 4202)
EGRESS_PROXY_SERVICE = "pier-egress-proxy"
EGRESS_PROXY_PORT = 8080


def resolve_default_codex_binary_dir(
    candidates: tuple[str, ...] = DEFAULT_CODEX_BINARY_DIRS,
) -> str:
    """Prefer fast ext4 cached binary dir inside WSL2, falling back to E:."""
    for candidate in candidates:
        if (Path(candidate) / "codex").is_file():
            return candidate
    return candidates[-1] if candidates else ""


def parse_csv_tokens(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [item.strip() for item in raw.split(",") if item.strip()]


def parse_ports(raw: str | list[int] | tuple[int, ...] | None) -> list[int]:
    if raw is None:
        return []
    tokens = parse_csv_tokens(raw) if isinstance(raw, str) else list(raw)
    ports: list[int] = []
    for tok in tokens:
        port = int(tok)
        if not (1 <= port <= 65535):
            raise ValueError(f"Invalid port: {port}")
        if port not in ports:
            ports.append(port)
    return ports


def merge_allowlist_domains(
    base_domains: list[str] | tuple[str, ...],
    extra_domains: list[str] | tuple[str, ...],
) -> list[str]:
    merged: set[str] = set()
    for d in list(base_domains) + list(extra_domains):
        clean = d.strip().lower().rstrip(".")
        if clean:
            merged.add(clean)
    return sorted(merged)


def build_proxy_build_args(build_proxy: str | None) -> dict[str, str]:
    if not build_proxy:
        return {}
    no_proxy = "localhost,127.0.0.1,::1"
    return {
        "http_proxy": build_proxy,
        "https_proxy": build_proxy,
        "HTTP_PROXY": build_proxy,
        "HTTPS_PROXY": build_proxy,
        "no_proxy": no_proxy,
        "NO_PROXY": no_proxy,
    }


def write_cached_codex_dockerfile(
    *,
    build_dir: Path,
    prebuilt_image_name: str,
    fingerprint: str,
    codex_binary: Path,
    rg_binary: Path | None = None,
    code_mode_host_binary: Path | None = None,
    model_catalog_json: Path | None = None,
) -> Path:
    """Write a fast offline Dockerfile injecting pinned Linux x64 codex (+ helpers)."""
    build_dir.mkdir(parents=True, exist_ok=True)
    bin_stage = build_dir / ".jevbench-codex-bin"
    if bin_stage.exists():
        shutil.rmtree(bin_stage)
    bin_stage.mkdir(parents=True, exist_ok=True)

    shutil.copy2(codex_binary, bin_stage / "codex")
    lines = [
        f"FROM {prebuilt_image_name}",
        f"ARG PIER_AGENT_INSTALL_FINGERPRINT={fingerprint}",
        "USER root",
        "COPY .jevbench-codex-bin/codex /usr/local/bin/codex",
    ]
    chmod_targets = ["/usr/local/bin/codex"]
    if rg_binary is not None and rg_binary.is_file():
        shutil.copy2(rg_binary, bin_stage / "rg")
        lines.append("COPY .jevbench-codex-bin/rg /usr/local/bin/rg")
        chmod_targets.append("/usr/local/bin/rg")
    if code_mode_host_binary is not None and code_mode_host_binary.is_file():
        shutil.copy2(code_mode_host_binary, bin_stage / "codex-code-mode-host")
        lines.append(
            "COPY .jevbench-codex-bin/codex-code-mode-host "
            "/usr/local/bin/codex-code-mode-host"
        )
        chmod_targets.append("/usr/local/bin/codex-code-mode-host")
    catalog_chmod = ""
    if model_catalog_json is not None and model_catalog_json.is_file():
        shutil.copy2(model_catalog_json, bin_stage / "merged-models.json")
        lines.append(
            f"COPY .jevbench-codex-bin/merged-models.json {CONTAINER_MODEL_CATALOG_PATH}"
        )
        catalog_chmod = f" && chmod 644 {CONTAINER_MODEL_CATALOG_PATH}"

    lines.append(
        f"RUN chmod 755 {' '.join(chmod_targets)}{catalog_chmod} && /usr/local/bin/codex --version"
    )
    lines.append("")
    dockerfile_path = build_dir / "Dockerfile"
    dockerfile_path.write_text("\n".join(lines), encoding="utf-8", newline="\n")
    return dockerfile_path


def build_squid_bootstrap_script(
    *,
    extra_safe_ports: list[int] | tuple[int, ...] = DEFAULT_EXTRA_SAFE_PORTS,
    upstream_proxy_host: str | None = DEFAULT_UPSTREAM_PROXY_HOST,
    upstream_proxy_port: int | None = DEFAULT_UPSTREAM_PROXY_PORT,
    direct_hosts: list[str] | tuple[str, ...] = ("host.docker.internal",),
) -> str:
    safe_ports = sorted({80, 443, *(int(p) for p in extra_safe_ports)})
    safe_ports_str = " ".join(str(p) for p in safe_ports)
    direct_hosts_str = " ".join(
        sorted({h.strip().lower() for h in direct_hosts if h.strip()})
    )

    peer_lines: list[str] = []
    if upstream_proxy_host and upstream_proxy_port and int(upstream_proxy_port) > 0:
        if direct_hosts_str:
            peer_lines.append(f"acl direct_hosts dstdomain {direct_hosts_str}")
        peer_lines.append(
            f"cache_peer {upstream_proxy_host} parent {int(upstream_proxy_port)} "
            "0 no-query default"
        )
        if direct_hosts_str:
            peer_lines.append("always_direct allow direct_hosts")
            peer_lines.append("never_direct allow !direct_hosts")
        else:
            peer_lines.append("never_direct allow all")

    peer_block = ("\n" + "\n".join(peer_lines) + "\n") if peer_lines else "\n"

    return (
        "#!/usr/bin/env bash\n"
        "set -eu\n"
        "\n"
        'printf \'%s\' "$ALLOWLIST_DOMAINS" | tr \',\' \'\\n\' | sed \'/^[[:space:]]*$/d\' \\\n'
        "  > /tmp/allowed_domains.txt\n"
        "\n"
        'htpasswd -bc /tmp/squid.passwd agent "$PROXY_TOKEN"\n'
        "\n"
        "cat > /tmp/squid.conf <<'EOF'\n"
        "http_port 0.0.0.0:8080\n"
        "pid_filename /tmp/squid.pid\n"
        "coredump_dir /tmp\n"
        "\n"
        "auth_param basic program /usr/lib/squid/basic_ncsa_auth /tmp/squid.passwd\n"
        "auth_param basic realm PierPolicyProxy\n"
        "acl authenticated proxy_auth REQUIRED\n"
        "\n"
        "acl SSL_ports port 443\n"
        f"acl Safe_ports port {safe_ports_str}\n"
        "acl CONNECT method CONNECT\n"
        'acl allowed_domains dstdomain "/tmp/allowed_domains.txt"\n'
        "\n"
        "http_access deny !Safe_ports\n"
        "http_access deny CONNECT !SSL_ports\n"
        "http_access allow authenticated allowed_domains\n"
        "http_access deny all\n"
        f"{peer_block}"
        "cache deny all\n"
        "access_log stdio:/tmp/squid_access.log\n"
        "cache_log /tmp/squid_cache.log\n"
        "log_mime_hdrs off\n"
        "shutdown_lifetime 1 seconds\n"
        "EOF\n"
        "\n"
        "exec squid -N -f /tmp/squid.conf -d 1\n"
    )


def build_proxy_compose_dict(
    *,
    proxy_dir: Path,
    allowlist_domains: list[str],
    token: str,
    build_proxy: str | None = DEFAULT_BUILD_PROXY,
) -> dict[str, Any]:
    build_cfg: dict[str, Any] = {
        "context": str(proxy_dir.resolve().absolute()),
    }
    if build_proxy:
        build_cfg["network"] = "host"
        build_cfg["args"] = build_proxy_build_args(build_proxy)

    return {
        "services": {
            "main": {
                "networks": ["pier-egress-internal"],
                "depends_on": {
                    EGRESS_PROXY_SERVICE: {
                        "condition": "service_healthy",
                    },
                },
            },
            EGRESS_PROXY_SERVICE: {
                "build": build_cfg,
                "extra_hosts": ["host.docker.internal:host-gateway"],
                "environment": {
                    "PROXY_TOKEN": token,
                    "ALLOWLIST_DOMAINS": ",".join(allowlist_domains),
                },
                "healthcheck": {
                    "test": ["CMD-SHELL", "bash -lc '</dev/tcp/127.0.0.1/8080'"],
                    "interval": "1s",
                    "timeout": "1s",
                    "retries": 30,
                },
                "networks": ["pier-egress-internal", "default"],
            },
        },
        "networks": {
            "pier-egress-internal": {
                "internal": True,
            },
        },
    }


def build_main_build_override_dict(build_proxy: str | None) -> dict[str, Any]:
    build_cfg: dict[str, Any] = {"network": "host"}
    if build_proxy:
        build_cfg["args"] = build_proxy_build_args(build_proxy)
    return {
        "services": {
            "main": {
                "build": build_cfg,
            }
        }
    }


def write_jevbench_proxy_compose(
    *,
    path: Path,
    proxy_dir: Path,
    allowlist_domains: list[str],
    token: str,
    extra_safe_ports: list[int] | tuple[int, ...] = DEFAULT_EXTRA_SAFE_PORTS,
    upstream_proxy_host: str | None = DEFAULT_UPSTREAM_PROXY_HOST,
    upstream_proxy_port: int | None = DEFAULT_UPSTREAM_PROXY_PORT,
    build_proxy: str | None = DEFAULT_BUILD_PROXY,
) -> Path:
    proxy_dir.mkdir(parents=True, exist_ok=True)
    # Deterministic Dockerfile so BuildKit caches the ubuntu + squid layer across trials.
    (proxy_dir / "Dockerfile").write_text(
        "\n".join(
            [
                "FROM ubuntu:24.04",
                "RUN apt-get update && "
                "DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends "
                "apache2-utils ca-certificates squid && "
                "rm -rf /var/lib/apt/lists/*",
                "COPY start-squid.sh /usr/local/bin/start-squid.sh",
                "RUN chmod +x /usr/local/bin/start-squid.sh",
                'CMD ["bash", "/usr/local/bin/start-squid.sh"]',
                "",
            ]
        ),
        encoding="utf-8",
        newline="\n",
    )
    (proxy_dir / "start-squid.sh").write_text(
        build_squid_bootstrap_script(
            extra_safe_ports=extra_safe_ports,
            upstream_proxy_host=upstream_proxy_host,
            upstream_proxy_port=upstream_proxy_port,
        ),
        encoding="utf-8",
        newline="\n",
    )
    compose = build_proxy_compose_dict(
        proxy_dir=proxy_dir,
        allowlist_domains=allowlist_domains,
        token=token,
        build_proxy=build_proxy,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(compose, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    return path


try:
    from pier.environments.agent_setup import new_proxy_token, proxy_environment
    from pier.environments.docker.docker import DockerEnvironment
except ImportError:  # pragma: no cover - allows importing pure helpers on Windows host
    DockerEnvironment = None  # type: ignore[assignment]
    new_proxy_token = None  # type: ignore[assignment]
    proxy_environment = None  # type: ignore[assignment]


if DockerEnvironment is not None:

    class JevbenchDockerEnvironment(DockerEnvironment):
        """Pier DockerEnvironment tailored for WSL2 proxy + Jev Codex Router."""

        def __init__(
            self,
            *args: Any,
            build_proxy: str | None = None,
            upstream_proxy_host: str | None = None,
            upstream_proxy_port: int | str | None = None,
            extra_allow_domains: str | list[str] | None = None,
            extra_safe_ports: str | list[int] | None = None,
            codex_binary_dir: str | None = None,
            model_catalog_json: str | None = None,
            **kwargs: Any,
        ) -> None:
            env_build_proxy = os.environ.get("JEVBENCH_BUILD_PROXY", DEFAULT_BUILD_PROXY)
            self._jev_build_proxy = (
                build_proxy if build_proxy is not None else env_build_proxy
            ) or None

            env_up_host = os.environ.get(
                "JEVBENCH_UPSTREAM_PROXY_HOST", DEFAULT_UPSTREAM_PROXY_HOST
            )
            self._jev_upstream_proxy_host = (
                upstream_proxy_host if upstream_proxy_host is not None else env_up_host
            ) or None

            raw_up_port = (
                upstream_proxy_port
                if upstream_proxy_port is not None
                else os.environ.get(
                    "JEVBENCH_UPSTREAM_PROXY_PORT", str(DEFAULT_UPSTREAM_PROXY_PORT)
                )
            )
            self._jev_upstream_proxy_port = (
                int(raw_up_port) if str(raw_up_port).strip() else 0
            )

            env_codex_dir = os.environ.get("JEVBENCH_CODEX_BINARY_DIR")
            if codex_binary_dir is not None:
                self._jev_codex_binary_dir = codex_binary_dir
            elif env_codex_dir is not None:
                self._jev_codex_binary_dir = env_codex_dir
            else:
                self._jev_codex_binary_dir = resolve_default_codex_binary_dir()

            env_catalog = os.environ.get("JEVBENCH_MODEL_CATALOG_JSON")
            self._jev_model_catalog_json = (
                model_catalog_json if model_catalog_json is not None else env_catalog
            ) or None

            if extra_allow_domains is None:
                raw_domains = os.environ.get("JEVBENCH_EXTRA_ALLOW_DOMAINS")
                self._jev_extra_domains = (
                    parse_csv_tokens(raw_domains)
                    if raw_domains is not None
                    else list(DEFAULT_EXTRA_ALLOW_DOMAINS)
                )
            elif isinstance(extra_allow_domains, str):
                self._jev_extra_domains = parse_csv_tokens(extra_allow_domains)
            else:
                self._jev_extra_domains = list(extra_allow_domains)

            if extra_safe_ports is None:
                raw_ports = os.environ.get("JEVBENCH_EXTRA_SAFE_PORTS")
                self._jev_extra_safe_ports = (
                    parse_ports(raw_ports)
                    if raw_ports is not None
                    else list(DEFAULT_EXTRA_SAFE_PORTS)
                )
            else:
                self._jev_extra_safe_ports = parse_ports(extra_safe_ports)

            self._main_build_override_path: Path | None = None
            super().__init__(*args, **kwargs)

        @property
        def _docker_compose_paths(self) -> list[Path]:
            paths = list(super()._docker_compose_paths)
            if (
                not self._use_prebuilt
                and self._main_build_override_path is not None
                and self._main_build_override_path.exists()
            ):
                paths.append(self._main_build_override_path)
            return paths

        def _prepare_agent_build_context(self) -> None:
            install = self.agent_install_spec
            cached_codex = (
                Path(self._jev_codex_binary_dir) / "codex"
                if self._jev_codex_binary_dir
                else None
            )
            if (
                install is not None
                and install.agent_name == "codex"
                and self.task_env_config.docker_image
                and not self._uses_compose
                and not self._is_windows_container
                and cached_codex is not None
                and cached_codex.is_file()
            ):
                build_dir = self.trial_paths.trial_dir / "agent-build-context"
                if build_dir.exists():
                    shutil.rmtree(build_dir)
                rg_bin = Path(self._jev_codex_binary_dir) / "rg"
                code_mode_host_bin = (
                    Path(self._jev_codex_binary_dir) / "codex-code-mode-host"
                )
                catalog_path = (
                    Path(self._jev_model_catalog_json)
                    if self._jev_model_catalog_json
                    else None
                )
                fp_suffix = ""
                if catalog_path is not None and catalog_path.is_file():
                    digest = hashlib.sha256(catalog_path.read_bytes()).hexdigest()[:12]
                    fp_suffix = f"-cat-{digest}"
                write_cached_codex_dockerfile(
                    build_dir=build_dir,
                    prebuilt_image_name=self.task_env_config.docker_image,
                    fingerprint=f"cached-codex-v2-{install.fingerprint()}{fp_suffix}",
                    codex_binary=cached_codex,
                    rg_binary=rg_bin if rg_bin.is_file() else None,
                    code_mode_host_binary=(
                        code_mode_host_bin if code_mode_host_bin.is_file() else None
                    ),
                    model_catalog_json=(
                        catalog_path
                        if catalog_path is not None and catalog_path.is_file()
                        else None
                    ),
                )
                self._agent_build_context_dir = build_dir
                self._env_vars.context_dir = str(build_dir.resolve().absolute())
                return

            super()._prepare_agent_build_context()
            if install is not None and self._jev_build_proxy:
                override_path = (
                    self.trial_paths.trial_dir / "docker-compose-build-proxy.json"
                )
                override_path.parent.mkdir(parents=True, exist_ok=True)
                override_path.write_text(
                    json.dumps(
                        build_main_build_override_dict(self._jev_build_proxy),
                        indent=2,
                    )
                    + "\n",
                    encoding="utf-8",
                    newline="\n",
                )
                self._main_build_override_path = override_path

        def _prepare_egress_proxy_compose(self) -> None:
            allowlist = self.network_allowlist
            if self.task_env_config.allow_internet or not allowlist.domains:
                return
            if self._uses_compose:
                raise ValueError(
                    "Filtered inference egress is currently supported only for Dockerfile "
                    "or prebuilt-image tasks, not docker-compose tasks."
                )
            merged_domains = merge_allowlist_domains(
                allowlist.domains, self._jev_extra_domains
            )
            token = new_proxy_token()
            self._egress_proxy_env = proxy_environment(
                token, EGRESS_PROXY_SERVICE, EGRESS_PROXY_PORT
            )
            self._egress_proxy_compose_path = write_jevbench_proxy_compose(
                path=self.trial_paths.trial_dir / "docker-compose-egress-proxy.json",
                proxy_dir=self.trial_paths.trial_dir / "egress-proxy",
                allowlist_domains=merged_domains,
                token=token,
                extra_safe_ports=self._jev_extra_safe_ports,
                upstream_proxy_host=self._jev_upstream_proxy_host,
                upstream_proxy_port=self._jev_upstream_proxy_port,
                build_proxy=self._jev_build_proxy,
            )
