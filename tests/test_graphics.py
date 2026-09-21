from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).parents[1]))

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

    def test_render_dashboard_set_creates_three_readme_pngs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            outputs = render_dashboard_set(self.REPORT, Path(directory))

            self.assertEqual(
                {path.name for path in outputs},
                {
                    "jev-benchmark-overview.png",
                    "jev-benchmark-savings.png",
                    "jev-browser-benchmark.png",
                },
            )
            for output in outputs:
                with Image.open(output) as image:
                    self.assertEqual(image.size, (1600, 900))
                    self.assertEqual(image.mode, "RGB")


if __name__ == "__main__":
    unittest.main()
