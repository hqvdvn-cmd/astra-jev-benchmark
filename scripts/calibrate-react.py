"""Check that the external verifier rejects the starter and accepts a functional calibration fixture."""
from __future__ import annotations
import argparse
import json
import shutil
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from jev_astra_bench.react_pilot import TASK, ROOT, verify

parser = argparse.ArgumentParser()
parser.add_argument('--output', type=Path, required=True)
parser.add_argument('--playwright-module', required=True)
args = parser.parse_args()
args.output.mkdir(parents=True, exist_ok=True)
work = args.output / 'positive-workspace'
if work.exists():
    raise SystemExit('Choose an empty calibration output directory')
starter = TASK / 'starter'
shutil.copytree(starter, work, ignore=lambda folder, names: [n for n in names if n in {'.vite', '.vite-temp'} or (Path(folder) == starter and n == 'dist')])
shutil.copy2(ROOT / 'tests/react-verifier-positive.jsx', work / 'src/App.jsx')
result = verify(work, args.output / 'positive-artifacts', args.playwright_module, 'chrome')
print('POSITIVE_CALIBRATION', json.dumps(result))
raise SystemExit(0 if result['success'] else 1)
