"""Validate archived normal/standalone UVM comparisons without a simulator."""
import hashlib
import json
from pathlib import Path
import re
import statistics
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.run_xsim_standalone import signature


def require(condition, message):
    if not condition:
        raise ValueError(message)


def validate():
    folder = ROOT / 'evidence/simulation_launch/2026-10-29'
    index = json.loads((folder / 'index.json').read_text())

    def local(name):
        path = (folder / name).resolve()
        require(path.is_relative_to(folder.resolve()), 'Launch evidence path escaped its folder')
        return path

    def log(original):
        return local(index['logs'][original]).read_text(encoding='utf-8')

    def sources(record):
        for name, digest in record['sha256'].items():
            require(hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == digest,
                    'Launch evidence source changed: ' + name)

    def nominal(text):
        require('[TMA_UVM_PASS]' in text, 'Missing executed native UVM pass')
        require(not re.search(r'(?mi)^\s*(?:#\s*)?(?:ERROR:|FATAL:|\*\* (?:Error|Fatal):)', text),
                'Simulator error in nominal launch')
        for severity in ('WARNING', 'ERROR', 'FATAL'):
            require(re.search(rf'UVM_{severity}\s*:\s*0\b', text), 'Nonzero UVM severity: ' + severity)

    def corruption(text):
        require('[TMA_UVM_PASS]' not in text and set(signature(text)['diagnoses']) ==
                {'TMA_CPP_READ_DATA', 'TMA_READ_DATA'}, 'Corruption must exercise both independent scoreboards')
        require(not re.search(r'(?mi)^\s*(?:ERROR:|FATAL:|Fatal:|\*\* (?:Error|Fatal):)', text),
                'Tool failure does not count as corruption detection')
        require(signature(text)['uvm_counts'] == {'WARNING': ['0'], 'ERROR': ['2'], 'FATAL': ['0']},
                'Unexpected corruption-control severity counts')

    def uvm(name):
        record = json.loads(local(index['records'][name]).read_text())
        require(record['status'] == 'pass' and record['source_files_unchanged'], 'Unaccepted launch record')
        sources(record)
        adapter = record['runtime_adapter']
        require(adapter['standalone'] and adapter['rtl_stimulus_monitors_scoreboards_unchanged'],
                'Expected standalone launch with unchanged verification')
        require(hashlib.sha256((ROOT / adapter['source']).read_bytes()).hexdigest() == adapter['sha256'],
                'Standalone adapter changed since measurement')
        path_adapter = record['launch_adapter']
        require(hashlib.sha256((ROOT / path_adapter['source']).read_bytes()).hexdigest() == path_adapter['sha256'],
                'Path adapter changed since measurement')
        for run in record['runs']:
            text = log(run['log'])
            nominal(text)
            fields = dict((key, int(value)) for key, value in
                          (field.split('=', 1) for field in signature(text)['summary'].split()))
            require(fields == run['summary'] and fields['descriptors'] == 46, 'Executed workload mismatch')
        corruption(log(record['corruption_control']['log']))
        return record

    benchmark = uvm('benchmark')
    require(benchmark['checker'] == 'dual' and benchmark['mode'] == 'seeded-procedural',
            'Unexpected benchmark mode')
    pairs = benchmark['runtime_adapter']['paired_launches']
    clean = [p for p in pairs if p['signature']['summary'] is not None]
    require(len(clean) == 5 and len(pairs) == 6, 'Expected five comparisons plus corruption control')
    require(len(benchmark['runs']) == 5 and all(r['profile'] == 'p1_b4_s0' and r['seed'] == 20261029
                                              for r in benchmark['runs']), 'Changed benchmark configuration/seed')
    for number, pair in enumerate(pairs):
        before, after = (log(pair[name + '_log']) for name in ('normal', 'standalone'))
        require(signature(before) == signature(after) == pair['signature'], 'Paired launches changed checked work')
        require(pair['order'] == (['normal', 'standalone'] if number % 2 == 0 else ['standalone', 'normal']),
                'Launch order was not interleaved')
        require(pair['normal_wall_seconds'] > 0 and pair['standalone_wall_seconds'] > 0, 'Invalid wall sample')
        if pair in clean:
            nominal(before)
            nominal(after)
            require(pair['signature']['finish_time_ns'] == ['4654430'], 'Changed simulated cycles')
        else:
            corruption(before)
            corruption(after)
    require(len({p['signature']['summary'] for p in clean}) == 1, 'Benchmark counts differ')
    normal = statistics.median(p['normal_wall_seconds'] for p in clean)
    standalone = statistics.median(p['standalone_wall_seconds'] for p in clean)
    comparison = benchmark['runtime_adapter']['comparison']
    require(comparison['normal_median_seconds'] == normal and
            comparison['standalone_median_seconds'] == standalone and
            comparison['normal_over_standalone'] == normal / standalone and
            comparison['wall_time_reduction_percent'] == 100 * (1 - standalone / normal) and
            comparison['nominal_pairs'] == len(clean), 'Incorrect launch performance arithmetic')
    full = uvm('full_features')
    require(full['sv_constrained_randomization_executed'] and full['sv_covergroups_executed'],
            'Full features were not executed')
    require({r['seed'] for r in full['runs']} == {20261029, 57, 991} and len(full['runs']) == 3,
            'Missing full-feature seeds')
    require(all(r['profile'] == 'p1_b4_s0' and r['functional_covergroup_percent'] == 100.0 and
                '[TMA_COVERGROUP] functional_coverage=100.0' in log(r['log']) for r in full['runs']),
            'Expected defined descriptor covergroup closure in the tested configuration')
    original = json.loads(local(index['records']['original_questa']).read_text())
    sources(original)
    require(original['status'] == 'pass' and len(original['profiles']) == 9, 'Original suite missing cases')
    for profile in original['profiles']:
        text = log('build/uvm/starter/' + profile + '_console.log')
        if profile == 'data_fault_control':
            require('[TMA_READ_DATA]' in text and '[TMA_UVM_PASS]' not in text, 'Original corruption control missed')
        else:
            nominal(text)
    return comparison


if __name__ == '__main__':
    report = validate()
    print(f'SIMULATION_LAUNCH_EVIDENCE_PASS pairs={report["nominal_pairs"]} '
          f'normal_over_standalone={report["normal_over_standalone"]:.3f}x')
