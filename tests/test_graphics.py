from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).parents[1]))

from jev_astra_bench import graphics
from jev_astra_bench.graphics import load_dashboard_data, render_dashboard_set


class BenchmarkGraphicsTests(unittest.TestCase):
    REPORT = (
        Path(__file__).parents[1]
        / "evidence"
        / "2026-09-21-five-mode"
        / "combined-report.json"
    )

    def test_dashboard_data_comes_from_the_canonical_report(self) -> None:
        data = load_dashboard_data(self.REPORT)

        self.assertEqual(data["astra_only"].success_label, "9/9")
        self.assertAlmostEqual(data["astra_jev_offload"].mean_duration_s, 44.10, places=2)
        self.assertAlmostEqual(data["astra_jev_guarded"].cost_per_success_usd, 0.58397, places=5)
        self.assertEqual(data["astra_jev_guarded"].success_label, "8/9")

    def test_task_breakdown_contains_every_task_and_mode(self) -> None:
        data = graphics.load_task_breakdown_data(self.REPORT)

        self.assertEqual(
            set(data),
            {"code-write-001", "bug-fix-001", "browser-001"},
        )
        for task in data.values():
            self.assertEqual(set(task), set(graphics.MODE_ORDER))
        self.assertEqual(data["bug-fix-001"]["astra_jev_guarded"].success_label, "2/3")
        self.assertAlmostEqual(
            data["browser-001"]["astra_jev_observe"].cost_per_success_usd,
            0.359492964,
            places=9,
        )

    def test_render_dashboard_set_creates_localized_readme_pngs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            english_outputs = render_dashboard_set(self.REPORT, root / "en", locale="en")
            russian_outputs = render_dashboard_set(self.REPORT, root / "ru", locale="ru")

            self.assertEqual(
                {path.name for path in english_outputs},
                {
                    "benchmark-overview.png",
                    "benchmark-savings.png",
                    "task-breakdown.png",
                },
            )
            self.assertEqual(
                {path.name for path in russian_outputs},
                {path.name for path in english_outputs},
            )
            for output in english_outputs + russian_outputs:
                with Image.open(output) as image:
                    self.assertEqual(image.size, (1600, 900))
                    self.assertEqual(image.mode, "RGB")
            for english, russian in zip(english_outputs, russian_outputs):
                self.assertNotEqual(english.read_bytes(), russian.read_bytes())


if __name__ == "__main__":
    unittest.main()
