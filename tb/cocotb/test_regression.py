"""Defines the eight pytest configurations and the injected-corruption test.

Each case launches cocotb and saves its result and source hashes.
"""

import ctypes
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import cocotb
from cocotb_tools.config import lib_name_path, libs_dir
from cocotb_tools.runner import get_results
from find_libpython import find_libpython
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from scripts.run_tests import find_questa
from scripts.run_uvm_tests import PROFILES, RTL_SOURCES

TOP = 'tb_tma_cocotb'
SOURCES = RTL_SOURCES + ['tb/tma_sdram_model.sv', f'tb/cocotb/{TOP}.sv']
HASHED = SOURCES + ['tb/cocotb/tma_regression.py', 'tb/cocotb/test_regression.py',
                    'model/address_model.py', 'model/copy_model.py', 'requirements-verification.txt',
                    'scripts/run_tests.py', 'scripts/run_uvm_tests.py']
SEED = 20261029


@pytest.fixture(scope='session')
def simulator(tmp_path_factory):
    build = tmp_path_factory.mktemp('questa')
    hashes = {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in HASHED}
    tool_dir = find_questa()
    suffix = '.exe' if os.name == 'nt' else ''

    def run(tool, args, log, env=None):
        # Pass raw argv so Windows paths with spaces work with this Questa release.
        with log.open('w', encoding='utf-8') as stream:
            process = subprocess.run([str(tool_dir / (tool + suffix)), *args], cwd=build,
                                     env=env, stdout=stream, stderr=subprocess.STDOUT, timeout=240)
        assert process.returncode == 0, log.read_text(encoding='utf-8', errors='replace')[-6000:]

    run('vlib', ['work'], build / 'library.log')
    run('vlog', ['-sv', '-work', 'work', *[str(ROOT / name) for name in SOURCES]], build / 'compile.log')
    run('vsim', ['-version'], build / 'version.log')
    (build / 'run.do').write_text('onerror {quit -code 1}\nrun -all\nquit -code 0\n', encoding='ascii')
    vpi = str(lib_name_path('vpi', 'questa'))
    if os.name == 'nt' and ' ' in vpi:
        # Questa splits -pli on spaces. Keep the library beside its dependencies.
        short_path = ctypes.create_unicode_buffer(32768)
        size = ctypes.windll.kernel32.GetShortPathNameW(vpi, short_path, len(short_path))
        assert 0 < size < len(short_path) and ' ' not in short_path.value, (
            'Install the verification dependencies in a Python environment with a space-free path'
        )
        vpi = short_path.value
    yield run, build, hashes, vpi
    assert hashes == {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in HASHED}


@pytest.mark.parametrize('profile', [*PROFILES, 'data_fault_control'])
def test_tensor_system(simulator, profile):
    run, build, hashes, vpi = simulator
    corrupt = profile == 'data_fault_control'
    pipelined, burst, swizzle = PROFILES['p1_b4_s0' if corrupt else profile]
    parameters = dict(PIPELINED=pipelined, READ_BURST_WORDS=burst, SWIZZLE=swizzle, READ_XOR_MASK=int(corrupt))
    report_path = build / f'{profile}.json'
    result = build / f'{profile}.xml'
    libpython = find_libpython()
    assert libpython, 'Cannot locate the Python runtime for cocotb'
    env = dict(os.environ, LIBPYTHON_LOC=libpython, PYGPI_PYTHON_BIN=sys.executable,
               COCOTB_TOPLEVEL=TOP, COCOTB_TEST_MODULES='tma_regression', TOPLEVEL_LANG='verilog',
               COCOTB_RESULTS_FILE=str(result), COCOTB_RANDOM_SEED=str(SEED),
               TMA_SEED=str(SEED), TMA_CORRUPT=str(int(corrupt)), TMA_REPORT=str(report_path))
    env['PATH'] = os.pathsep.join((str(libs_dir), env.get('PATH', '')))
    env['PYTHONPATH'] = os.pathsep.join([str(ROOT), str(ROOT / 'tb/cocotb'), *filter(None, sys.path)])
    log = build / f'{profile}.log'
    run('vsim', ['-c', '-onfinish', 'exit', '-voptargs=+acc', '-pli', vpi,
                 '-sv_seed', str(SEED), *[f'-g{name}={value}' for name, value in parameters.items()],
                 f'work.{TOP}', '-do', 'do run.do'], log, env)
    assert result.is_file() and get_results(result) == (1, 0), log.read_text(encoding='utf-8', errors='replace')[-6000:]
    report = json.loads(report_path.read_text(encoding='utf-8'))
    if corrupt:
        assert report['corruption_detected'].startswith('TMA_READ_DATA')
    report.update(status='pass', profile=profile, seed=SEED, parameters=parameters,
                  sha256=hashes, cocotb_version=cocotb.__version__, pytest_version=pytest.__version__,
                  simulator_version=(build / 'version.log').read_text(encoding='utf-8').strip())
    report_path.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
