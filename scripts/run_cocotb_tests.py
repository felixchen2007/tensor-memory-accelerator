"""Launches the pytest and cocotb acceptance matrix.

It collects the per-configuration results and keeps the simulator artifacts with the run.
"""

import json
from pathlib import Path
import subprocess
import sys
from tempfile import mkdtemp

from scripts.run_uvm_tests import PROFILES

ROOT = Path(__file__).resolve().parents[1]
PYTEST_ENTRY = 'tb/cocotb/test_regression.py'
COCOTB_SOURCES = [PYTEST_ENTRY, 'tb/cocotb/tma_regression.py', 'tb/cocotb/tb_tma_cocotb.sv',
                  'requirements-verification.txt', 'scripts/run_cocotb_tests.py']


def run_cocotb_suite(output: Path) -> dict:
    output.mkdir(parents=True, exist_ok=True)
    run_dir = Path(mkdtemp(prefix='run-', dir=output.resolve()))
    completed = subprocess.run([sys.executable, '-m', 'pytest', '-x', '-q', PYTEST_ENTRY,
                                '--basetemp', str(run_dir / 'pytest')], cwd=ROOT)
    if completed.returncode:
        raise RuntimeError(f'cocotb regression failed. Logs and results: {run_dir}')
    profiles = {}
    for name in [*PROFILES, 'data_fault_control']:
        paths = list((run_dir / 'pytest').glob(f'questa*/{name}.json'))
        if len(paths) != 1:
            raise RuntimeError(f'Expected one cocotb report for {name} in {run_dir}')
        record = json.loads(paths[0].read_text(encoding='utf-8'))
        if record['status'] != 'pass' or record['profile'] != name:
            raise RuntimeError(f'Unexpected cocotb report for {name} in {run_dir}')
        profiles[name] = record
    return {'status': 'pass', 'framework': 'pytest/cocotb',
            'artifact_directory': run_dir.relative_to(ROOT).as_posix(), 'profiles': profiles}
