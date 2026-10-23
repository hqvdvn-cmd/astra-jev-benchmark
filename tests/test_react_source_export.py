import tempfile
import unittest
import zipfile
from pathlib import Path

from jev_astra_bench.react_export import export_source_archive


class SourcePrivacyTests(unittest.TestCase):
    def test_browser_profiles_and_crash_dumps_are_omitted_without_changing_code(self):
        with tempfile.TemporaryDirectory() as directory:
            raw, exported = Path(directory) / 'raw.zip', Path(directory) / 'source.zip'
            files = {'src/App.jsx': b'actual source', 'src/Profile/index.jsx': b'legitimate component',
                     'src/.orbit-qa-profile/Variations': b'browser data',
                     'src/.orbit-qa-profile/Crashpad/reports/process.dmp': b'process memory'}
            with zipfile.ZipFile(raw, 'w') as archive:
                for name, data in files.items():archive.writestr(name, data)
            original = raw.read_bytes()
            record = export_source_archive(raw, exported)
            self.assertEqual(raw.read_bytes(), original)
            self.assertEqual(record['excluded_members'], 2)
            with zipfile.ZipFile(exported) as archive:
                self.assertEqual(set(archive.namelist()), {'src/App.jsx', 'src/Profile/index.jsx'})
                self.assertEqual(archive.read('src/App.jsx'), files['src/App.jsx'])
                self.assertEqual(archive.read('src/Profile/index.jsx'), files['src/Profile/index.jsx'])

    def test_archive_without_browser_data_is_copied_byte_for_byte(self):
        with tempfile.TemporaryDirectory() as directory:
            raw, exported = Path(directory) / 'raw.zip', Path(directory) / 'source.zip'
            with zipfile.ZipFile(raw, 'w') as archive:archive.writestr('src/App.jsx', 'code')
            record = export_source_archive(raw, exported)
            self.assertEqual(record['excluded_members'], 0)
            self.assertEqual(raw.read_bytes(), exported.read_bytes())

    def test_unclassified_profile_or_crash_memory_blocks_export(self):
        with tempfile.TemporaryDirectory() as directory:
            raw, exported = Path(directory) / 'raw.zip', Path(directory) / 'source.zip'
            with zipfile.ZipFile(raw, 'w') as archive:
                archive.writestr('src/unknown-data/Local State', 'private data')
                archive.writestr('src/unknown-data/Variations', 'browser data')
            with self.assertRaises(ValueError):
                export_source_archive(raw, exported)
            self.assertFalse(exported.exists())

    def test_legitimate_source_named_like_a_browser_marker_is_not_removed(self):
        with tempfile.TemporaryDirectory() as directory:
            raw, exported = Path(directory) / 'raw.zip', Path(directory) / 'source.zip'
            with zipfile.ZipFile(raw, 'w') as archive:
                archive.writestr('src/Crashpad/Panel.jsx', 'legitimate source')
                archive.writestr('src/Variations', 'legitimate asset')
                archive.writestr('src/App.jsx', 'code')
            record = export_source_archive(raw, exported)
            self.assertEqual(record['excluded_members'], 0)
            self.assertEqual(raw.read_bytes(), exported.read_bytes())
