"""Local TCP bridge binding only on Docker bridge IP (e.g. 172.17.0.1) inside WSL2.

Forwards container-originated connections from ``host.docker.internal:<listen_port>``
to loopback services on ``127.0.0.1:<target_port>`` (host HTTP proxy :2080,
Jev Codex Router :4319, or a local mock Responses API server for zero-cost smoke tests).
"""

from __future__ import annotations

import argparse
import asyncio
import signal
import sys
from dataclasses import dataclass


@dataclass(frozen=True)
class PortMapping:
    listen_port: int
    target_port: int
    target_host: str = "127.0.0.1"


def parse_mapping(spec: str) -> PortMapping:
    """Parse ``listen_port:target_port`` or ``listen_port:target_host:target_port``."""
    parts = [p.strip() for p in spec.split(":")]
    if len(parts) == 2:
        listen_port, target_port = int(parts[0]), int(parts[1])
        target_host = "127.0.0.1"
    elif len(parts) == 3:
        listen_port = int(parts[0])
        target_host = parts[1]
        target_port = int(parts[2])
    else:
        raise ValueError(
            f"Invalid mapping {spec!r}; expected LISTEN_PORT:TARGET_PORT"
        )
    for port in (listen_port, target_port):
        if not (1 <= port <= 65535):
            raise ValueError(f"Port out of range in mapping {spec!r}")
    return PortMapping(
        listen_port=listen_port,
        target_port=target_port,
        target_host=target_host,
    )


async def _pipe(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        while True:
            chunk = await reader.read(65536)
            if not chunk:
                break
            writer.write(chunk)
            await writer.drain()
    except (ConnectionError, OSError, asyncio.CancelledError):
        pass
    finally:
        try:
            if writer.can_write_eof():
                writer.write_eof()
        except (ConnectionError, OSError):
            pass


async def _handle_client(
    client_reader: asyncio.StreamReader,
    client_writer: asyncio.StreamWriter,
    mapping: PortMapping,
    connect_timeout: float = 10.0,
) -> None:
    upstream_writer: asyncio.StreamWriter | None = None
    try:
        upstream_reader, upstream_writer = await asyncio.wait_for(
            asyncio.open_connection(mapping.target_host, mapping.target_port),
            timeout=connect_timeout,
        )
        t1 = asyncio.create_task(_pipe(client_reader, upstream_writer))
        t2 = asyncio.create_task(_pipe(upstream_reader, client_writer))
        await asyncio.gather(t1, t2, return_exceptions=True)
    except (ConnectionError, OSError, asyncio.TimeoutError):
        pass
    finally:
        for w in (upstream_writer, client_writer):
            if w is not None:
                try:
                    w.close()
                    await w.wait_closed()
                except (ConnectionError, OSError):
                    pass


class LocalTcpBridge:
    """Async multi-port TCP forwarder bound to a specific interface IP."""

    def __init__(self, bind_host: str, mappings: list[PortMapping]) -> None:
        self.bind_host = bind_host
        self.mappings = list(mappings)
        self._servers: list[asyncio.base_events.Server] = []
        self.bound_ports: dict[int, int] = {}

    async def start(self) -> None:
        for mapping in self.mappings:
            server = await asyncio.start_server(
                lambda r, w, m=mapping: _handle_client(r, w, m),
                host=self.bind_host,
                port=mapping.listen_port,
                reuse_address=True,
            )
            sock = server.sockets[0]
            actual_port = sock.getsockname()[1]
            self.bound_ports[mapping.target_port] = actual_port
            self._servers.append(server)

    async def stop(self) -> None:
        for server in self._servers:
            server.close()
        for server in self._servers:
            await server.wait_closed()
        self._servers.clear()


async def _run_cli(bind_host: str, mappings: list[PortMapping]) -> int:
    bridge = LocalTcpBridge(bind_host, mappings)
    await bridge.start()
    stop_event = asyncio.Event()

    loop = asyncio.get_running_loop()
    for sig_name in ("SIGINT", "SIGTERM"):
        sig = getattr(signal, sig_name, None)
        if sig is not None:
            try:
                loop.add_signal_handler(sig, stop_event.set)
            except NotImplementedError:
                pass

    summary = ", ".join(
        f"{bind_host}:{m.listen_port}->{m.target_host}:{m.target_port}"
        for m in mappings
    )
    print(f"BRIDGE_READY {summary}", flush=True)
    try:
        await stop_event.wait()
    finally:
        await bridge.stop()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Forward Docker bridge ports to loopback services inside WSL2."
    )
    parser.add_argument(
        "--bind-host",
        default="172.17.0.1",
        help="Interface IP to bind (default: Docker bridge 172.17.0.1)",
    )
    parser.add_argument(
        "--map",
        dest="mappings",
        action="append",
        required=True,
        help="Port mapping LISTEN_PORT:TARGET_PORT (repeatable)",
    )
    args = parser.parse_args(argv)
    mappings = [parse_mapping(spec) for spec in args.mappings]
    try:
        return asyncio.run(_run_cli(args.bind_host, mappings))
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.exit(main())
