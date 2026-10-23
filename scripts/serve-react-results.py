"""Serve an exported gallery and its unchanged Vite builds on loopback only."""
from __future__ import annotations

import argparse
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse
import threading


class SafeHandler(SimpleHTTPRequestHandler):
    def translate_path(self, path):
        translated = Path(super().translate_path(path)).resolve()
        if not translated.is_relative_to(Path(self.directory).resolve()):
            return str(Path(self.directory) / '__blocked_external_path__')
        return str(translated)


class Handler(SafeHandler):
    site_routes: dict[str, str] = {}

    def do_GET(self):
        request = urlparse(self.path).path
        if request == '/':
            self.path = '/gallery.html'
        else:
            for prefix, origin in self.site_routes.items():
                if request.startswith(prefix):
                    self.send_response(302)
                    self.send_header('Location', origin + self.path[len(prefix):])
                    self.end_headers()
                    return
        return super().do_GET()


def site_servers(root: Path) -> tuple[list[ThreadingHTTPServer], dict[str, str]]:
    servers, routes = [], {}
    for index in sorted(root.glob('**/site/index.html')):
        directory = index.parent.resolve()
        if not directory.is_relative_to(root.resolve()):
            raise ValueError('Site path must stay within the export')
        server = ThreadingHTTPServer(('127.0.0.1', 0), partial(SafeHandler, directory=str(directory)))
        threading.Thread(target=server.serve_forever, daemon=True).start()
        servers.append(server)
        routes['/' + index.parent.relative_to(root).as_posix() + '/'] = f'http://127.0.0.1:{server.server_port}/'
    return servers, routes


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8765)
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    sites, Handler.site_routes = site_servers(root)
    print(f'Gallery: http://127.0.0.1:{args.port}/gallery.html', flush=True)
    try:
        ThreadingHTTPServer(('127.0.0.1', args.port), partial(Handler, directory=str(root))).serve_forever()
    finally:
        for server in sites:
            server.shutdown()
            server.server_close()
