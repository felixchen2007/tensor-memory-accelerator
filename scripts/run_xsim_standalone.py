"""Run the existing native UVM suite using XSim's standalone executable.

The RTL, stimulus, monitors and both scoreboards are unchanged. Add
--launch-compare --repeat 3 to interleave normal and standalone launches of
identical compiled sources, seeds and public-interface transactions.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import statistics
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import run_dpi_uvm_tests as runner
from scripts import run_xsim_full as launcher
from scripts.reference_tools import vivado


def read_options(path):
    lines = Path(path).read_text().splitlines()
    if any(len(line) < 2 or line[0] != '"' or line[-1] != '"' for line in lines):
        raise ValueError('Expected one quoted simulator option per line')
    return [line[1:-1] for line in lines]


def write_options(path, values):
    if any('"' in str(value) or '\n' in str(value) for value in values):
        raise ValueError('Unsupported character in simulator option')
    Path(path).write_text('\n'.join('"' + str(v).replace('\\', '/') + '"' for v in values) + '\n')


def signature(text):
    """Compare executed work and diagnoses; exclude timings and object addresses."""
    def message(name):
        match = re.search(r'\[' + name + r'\] ([^\r\n]+)', text)
        return match[1] if match else None
    return {
        'summary': message('TMA_UVM_PASS'),
        'scenarios': message('TMA_SCENARIOS'),
        'covergroup': message('TMA_COVERGROUP'),
        'finish_time_ns': re.findall(r'\$finish called at time\s*:\s*(\d+) ns', text),
        'uvm_counts': {s: re.findall(r'UVM_' + s + r'\s*:\s*(\d+)\b', text)
                       for s in ('WARNING', 'ERROR', 'FATAL')},
        'diagnoses': sorted(set(re.findall(r'UVM_(?:ERROR|FATAL).*?\[(TMA_\w+)\]', text))),
    }


def standalone_call(executable, options, output, name, timeout):
    tool = vivado()
    env = os.environ.copy()
    env['XILINX_VIVADO'] = str(tool.parent)
    # The documented standalone snapshot uses Vivado DLLs directly. Scope these
    # paths to this child, keeping the user's environment and compiler intact.
    paths = [tool.parent / 'lib/win64.o', tool.parent / 'tps/mingw/6.2.0/win64.o/nt/bin']
    env['PATH'] = os.pathsep.join([*(str(p) for p in paths), env.get('PATH', '')])
    start = time.perf_counter()
    process = subprocess.run([str(executable), *options], cwd=output, env=env,
                             text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                             errors='replace', timeout=timeout)
    (output / name).write_text(process.stdout, encoding='utf-8')
    elapsed = time.perf_counter() - start
    if process.returncode:
        raise RuntimeError(f'{name}: standalone exit {process.returncode}\n{process.stdout[-5000:]}')
    return process.stdout, elapsed


def main():
    if os.name != 'nt':
        raise RuntimeError('This standalone launcher is currently validated on Windows only')
    compare = '--launch-compare' in sys.argv
    if compare:
        sys.argv.remove('--launch-compare')
        if '--compare' in sys.argv or sys.argv.count('--profile') != 1 or sys.argv.count('--seed') > 1:
            raise ValueError('A launch comparison requires one --profile, at most one --seed and one checker mode')
    original_call = runner.call
    pairs = []
    work = None

    def call(command, output, name, timeout=300):
        nonlocal work
        work = output
        program = Path(command[0]).name.lower()
        if program == 'xelab.bat':
            if compare:
                original_call(command, output, name + '.normal.log', timeout)
            options = read_options(command[command.index('-f') + 1])
            snapshot = options.index('-s') + 1
            options[snapshot] += '_standalone'
            options += ['--standalone']
            argfile = output / (name + '.standalone.args')
            write_options(argfile, options)
            return original_call([command[0], '-f', argfile], output, name, timeout)
        if program != 'xsim.bat':
            return original_call(command, output, name, timeout)
        options = read_options(command[command.index('-f') + 1])
        batch = options.index('-tclbatch')
        del options[batch:batch + 2]
        options.insert(0, '-R')
        executable = output / 'xsim.dir' / (command[1] + '_standalone') / 'axsim.exe'
        normal_name = str(Path(name).with_name('baseline_console.log'))
        if not compare:
            return standalone_call(executable, options, output, name, timeout)
        # Reverse order each pair to avoid giving one launcher all warm runs.
        order = ['normal', 'standalone'] if len(pairs) % 2 == 0 else ['standalone', 'normal']
        samples = {}
        for mode in order:
            samples[mode] = (original_call(command, output, normal_name, timeout) if mode == 'normal'
                             else standalone_call(executable, options, output, name, timeout))
        before, after = (signature(samples[mode][0]) for mode in ('normal', 'standalone'))
        if before != after:
            raise RuntimeError('Normal and standalone UVM workloads/diagnoses differ: ' + name)
        pairs.append({'case': str(Path(name).parent), 'order': order, 'signature': after,
                      'normal_wall_seconds': samples['normal'][1],
                      'standalone_wall_seconds': samples['standalone'][1],
                      'normal_log': (output / normal_name).relative_to(runner.ROOT).as_posix(),
                      'standalone_log': (output / name).relative_to(runner.ROOT).as_posix()})
        print(f'LAUNCH_PAIR_MATCH normal={samples["normal"][1]:.3f}s '
              f'standalone={samples["standalone"][1]:.3f}s', flush=True)
        return samples['standalone']

    runner.call = call
    try:
        launcher.main()
    finally:
        runner.call = original_call
        if work is not None and (work / 'results.json').is_file():
            path = work / 'results.json'
            result = json.loads(path.read_text())
            result['runtime_adapter'] = {
                'source': 'scripts/run_xsim_standalone.py',
                'sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                'standalone': True, 'windows_only': True,
                'scope': 'Identical native UVM; simulator process launch and log writing timed; compilation excluded',
                'rtl_stimulus_monitors_scoreboards_unchanged': True,
                'paired_launches': pairs,
            }
            # Restrict the headline comparison to successful, identical nominal
            # tests. The separately matched corruption control is not a speed sample.
            nominal = [p for p in pairs if p['signature']['summary'] is not None]
            if nominal:
                normal = statistics.median(p['normal_wall_seconds'] for p in nominal)
                standalone = statistics.median(p['standalone_wall_seconds'] for p in nominal)
                result['runtime_adapter']['comparison'] = {
                    'nominal_pairs': len(nominal), 'normal_median_seconds': normal,
                    'standalone_median_seconds': standalone, 'normal_over_standalone': normal / standalone,
                    'wall_time_reduction_percent': 100 * (1 - standalone / normal),
                    'note': 'Only compare like configurations, seeds and checker modes; use one profile/seed/mode per benchmark.',
                }
            path.write_text(json.dumps(result, indent=2) + '\n')
    print('XSIM_STANDALONE_SUITE_PASS', flush=True)


if __name__ == '__main__':
    main()
