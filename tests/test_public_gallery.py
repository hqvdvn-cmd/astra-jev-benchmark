import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('gallery_publish', ROOT / 'scripts/publish-react-gallery.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class GalleryPublicationTests(unittest.TestCase):
    def test_relocation_changes_only_declared_static_urls(self):
        source = '<script src="/assets/app.js"></script><a href="#work">Work</a>const p="/orbit-loop.mp4";const regex=/assets/;'
        result = module.relocate(source, {'/assets/app.js': '/bench/gallery/id/site/assets/app.js',
                                         '/orbit-loop.mp4': '/bench/gallery/id/site/orbit-loop.mp4'})
        self.assertIn('src="/bench/gallery/id/site/assets/app.js"', result)
        self.assertIn('p="/bench/gallery/id/site/orbit-loop.mp4"', result)
        self.assertIn('const regex=/assets/', result)
        self.assertIn('href="#work"', result)

    def test_curated_metadata_never_contains_workspace_or_raw_logs(self):
        row = {'attempt_id': 'a', 'model': 'm', 'mode': 'baseline', 'repeat': 1, 'success': False,
               'model_timed_out': True, 'verification': {'checks': {'build': True}},
               'workspace': 'PRIVATE', 'final_text': 'PRIVATE', 'command': 'PRIVATE'}
        result = module.public_row(row, 'a', False)
        self.assertNotIn('PRIVATE', str(result))
        self.assertEqual(result['status'], 'TIME LIMIT')


if __name__ == '__main__':
    unittest.main()
