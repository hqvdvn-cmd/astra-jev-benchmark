from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

from jev_astra_bench.browser import BrowserChoice, FakeBrowserAdapter, PlaywrightBrowserAdapter
from jev_astra_bench.tasks import copy_fixture, load_manifest


class BrowserAndFixtureTests(unittest.TestCase):
    def test_manifest_loads_three_task_kinds(self):
        manifest = Path(__file__).parents[1] / "tasks" / "manifest.json"
        tasks = load_manifest(manifest)
        self.assertEqual([task.kind for task in tasks], ["code_write", "bug_fix", "browser"])

    def test_fixture_copy_is_independent(self):
        manifest = Path(__file__).parents[1] / "tasks" / "manifest.json"
        task = load_manifest(manifest)[0]
        with tempfile.TemporaryDirectory() as first, tempfile.TemporaryDirectory() as second:
            a = copy_fixture(task, 1, Path(first))
            b = copy_fixture(task, 1, Path(second))
            (a / "slugify.py").write_text("changed", encoding="utf-8")
            self.assertNotEqual((a / "slugify.py").read_text(), (b / "slugify.py").read_text())

    def test_fake_browser_rejects_unknown_target_and_requires_email(self):
        adapter = FakeBrowserAdapter()
        self.assertFalse(adapter.perform(BrowserChoice("click", "delete-account")).success)
        self.assertFalse(adapter.perform(BrowserChoice("click", "submit")).success)
        self.assertTrue(adapter.perform(BrowserChoice("fill", "email", "test@example.com")).success)
        self.assertTrue(adapter.perform(BrowserChoice("click", "submit")).success)
        self.assertIn("state=submitted", adapter.snapshot().state)

    def test_live_adapter_requires_preflight_page(self):
        with self.assertRaises(RuntimeError):
            PlaywrightBrowserAdapter()


if __name__ == "__main__":
    unittest.main()
