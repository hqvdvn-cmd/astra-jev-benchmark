from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('react_chart', ROOT / 'scripts/render-react-pilot.py')
chart = importlib.util.module_from_spec(spec)
spec.loader.exec_module(chart)


class ReactChartTests(unittest.TestCase):
    def test_data_preserves_both_series_and_missing_timing(self):
        data = chart.load_data(ROOT / 'evidence/2026-10-23-react-pilot')
        self.assertEqual(sum(g['success'] for g in data['original']), 16)
        self.assertEqual(sum(g['success'] for g in data['revised']), 17)
        self.assertEqual(sum(g['timeout'] for g in data['revised']), 2)
        self.assertEqual(sum(g['failure'] for g in data['revised']), 1)
        self.assertEqual([g['success'] for g in data['revised']], [4, 4, 4, 5])
        sol_jev = data['revised'][3]
        self.assertEqual(sol_jev['unknown_timing'], 1)
        self.assertIsNone(sol_jev['median_model_duration_s'])
        self.assertEqual(len(sol_jev['samples']), 5)
        self.assertEqual(sum(s['model_duration_s'] is None for s in sol_jev['samples']), 1)

    def test_export_has_two_charts_per_language_with_machine_readable_values(self):
        from PIL import Image
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            chart.render(ROOT / 'evidence/2026-10-23-react-pilot', output)
            for language in ('en', 'ru'):
                for name in ('react-pilot-outcomes.png', 'react-pilot-generation.png'):
                    with Image.open(output / language / name) as image:
                        self.assertEqual(image.size, (1600, 900))
            self.assertTrue((output / 'react-pilot-chart-data.json').is_file())


if __name__ == '__main__':
    unittest.main()
