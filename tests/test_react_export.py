from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.request
import zipfile
from urllib.parse import urlparse
from functools import partial
from http.server import ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('react_gallery_server', ROOT / 'scripts/serve-react-results.py')
server_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(server_module)


class GalleryExportTests(unittest.TestCase):
    def test_incomplete_export_requires_explicit_partial_flag_and_keeps_raw_events_out(self):
        with tempfile.TemporaryDirectory() as directory:
            run, export = Path(directory) / 'run', Path(directory) / 'export'
            folder = run / 'sample'
            (folder / 'artifacts').mkdir(parents=True)
            (run / 'manifest.json').write_text('{}')
            with zipfile.ZipFile(folder / 'source.zip', 'w') as archive:
                archive.writestr('src/App.jsx', 'fixture source')
            (folder / 'codex-events.jsonl').write_text('private raw events')
            row = {'attempt_id': 'sample', 'model': 'gpt-6-astra', 'mode': 'baseline',
                   'repeat': 1, 'duration_s': 2, 'success': False}
            (run / 'attempts.jsonl').write_text(json.dumps(row) + '\n')
            command = [sys.executable, str(ROOT / 'scripts/export-react-results.py'), '--run', str(run), '--output', str(export)]
            rejected = subprocess.run(command, capture_output=True, text=True)
            self.assertNotEqual(rejected.returncode, 0)
            self.assertFalse(export.exists())
            accepted = subprocess.run(command + ['--partial'], capture_output=True, text=True)
            self.assertEqual(accepted.returncode, 0, accepted.stderr)
            self.assertEqual(json.loads((export / 'report.json').read_text())['status'], 'incomplete')
            self.assertFalse((export / 'sample/codex-events.jsonl').exists())
            self.assertTrue((export / 'sample/source.zip').exists())

    def test_local_server_gives_each_unchanged_site_its_own_asset_origin(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'sample/site/assets').mkdir(parents=True)
            (root / 'sample/site/index.html').write_text('site-index')
            (root / 'sample/site/assets/app.js').write_text('site-asset')
            sites, server_module.Handler.site_routes = server_module.site_servers(root)
            handler = partial(server_module.Handler, directory=str(root))
            server = ThreadingHTTPServer(('127.0.0.1', 0), handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                host = f'127.0.0.1:{server.server_port}'
                response = urllib.request.urlopen(f'http://{host}/sample/site/index.html')
                self.assertEqual(response.read(), b'site-index')
                self.assertNotEqual(urlparse(response.url).netloc, host)
                origin = server_module.Handler.site_routes['/sample/site/']
                self.assertEqual(urllib.request.urlopen(origin + 'assets/app.js').read(), b'site-asset')
            finally:
                server.shutdown()
                server.server_close()
                thread.join()
                for site in sites:
                    site.shutdown()
                    site.server_close()
