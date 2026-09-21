from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

from jev_astra_bench.tasks import load_manifest


class TaskManifestTests(unittest.TestCase):
    def test_manifest_loads_guard_requirements_and_review_threshold(self) -> None:
        manifest = Path(__file__).parents[1] / "tasks" / "manifest.json"

        tasks = {task.task_id: task for task in load_manifest(manifest)}

        self.assertEqual(
            tasks["code-write-001"].requirements,
            ("slug-lowercase", "slug-separators", "slug-trim"),
        )
        self.assertEqual(tasks["code-write-001"].review_changed_lines_above, 30)
        self.assertEqual(tasks["browser-001"].requirements, ("browser-submitted",))
        self.assertIsNone(tasks["browser-001"].review_changed_lines_above)


if __name__ == "__main__":
    unittest.main()
