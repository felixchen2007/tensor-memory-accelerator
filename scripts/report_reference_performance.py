"""Regenerate the portfolio performance tables from published measured records."""
import json
from pathlib import Path
import re
import statistics
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.check_cpp_evidence import validate


def main():
    validate()
    folder=ROOT/'evidence/cpp_reference/2026-10-29'
    index=json.loads((folder/'index.json').read_text())
    def record(label):return json.loads((folder/index['records'][label]).read_text())
    standalone=record('standalone');micro=record('microbenchmark');runtime=record('runtime_benchmark')
    lines=['# Reference-model and verification performance\n',
           'Measured on 2026-10-29 UTC on a shared Windows 11 laptop, using '
           f"Python {standalone['python']}, GCC 15.1.0 (`-std=c++17 -O2`) and Vivado XSim 2025.2. "
           'The original SV scoreboard and production RTL are unchanged.\n',
           '**Result:** C++ substantially reduces isolated model computation. The full RTL '
           'verification workflow did not improve: its C++ median was slightly slower, with '
           'overlapping timing ranges. Retaining the SV baseline and optional dual checking '
           'provides independent validation without claiming a simulation speedup.\n',
           '## Correctness before timing\n',
           '- 21 standalone C++ directed tests; 387 exact Python/C++ comparisons covering '
           'complete destination images and read/write traces; 8,192 bank mappings; '
           '100 C API create/reset/destroy lifecycles.\n'
           '- Eight engine/burst/layout configurations passed with both UVM scoreboards; '
           '368 descriptors. Six completed before a laptop power interruption and two '
           'completed afterward with identical source hashes. The partial run retains its '
           '`incomplete` status; individual completed logs were revalidated.\n'
           '- C++-only checking plus existing monitors/pin model detected 21/21 selected '
           'mutations: 17 C++ scoreboard diagnoses, three UVM protocol diagnoses and one '
           'pin-level refresh deadline. Clean before/after controls passed.\n'
           '- XSim executed constrained randomization and covergroups for seeds '
           '`20261029`, `57` and `991` in `p1_b4_s0`: 138 descriptors; 100% of the defined '
           'descriptor covergroup in each run. This is scoped coverage, not exhaustive proof.\n'
           '- Full DPI integration and dual corruption diagnoses also passed on Questa; '
           'the unchanged original eight-profile Questa suite passed independently.\n',
           '## Complete-copy public API\n',
           'Both implementations validate all input memory values and materialize full '
           'read/write traces and destination copies. Each runs in a separate fresh process '
           'without retained cross-validation corpora. Input initialization, compilation '
           'and process launch are outside timed computation. Three warmups and seven '
           'repetitions are used. Numbers below are medians; raw min/max and samples are retained.\n',
           '| Tensor | Endpoint words | Python (us/descriptor) | C++ (us/descriptor) | Python / C++ | Python peak process MiB | C++ peak process MiB |',
           '| --- | ---: | ---: | ---: | ---: | ---: | ---: |']
    for r in standalone['benchmark']:
        p,c=r['python'],r['cpp'];side=r['side']
        lines.append(f"| {side}x{side}{' *' if side>64 else ''} | {max(4096,side*side):,} | {p['median_ns']/1000:,.2f} | {c['median_ns']/1000:,.2f} | {r['pure_model_ratio']:.2f}x | {p['process_peak_bytes']/1048576:.2f} | {c['process_peak_bytes']/1048576:.2f} |")
    lines += ['\nSmall tensor cases still validate two complete 4,096-word endpoint arrays; '
              'their ratios include this public-API cost. Process peaks include language '
              'runtimes and are cumulative across ascending sizes, not model allocation '
              'alone. Python traced allocation is recorded separately. The 128x128 case '
              '(*) uses synthetic larger endpoints beyond the physical 8 KiB scratchpad.\n',
              '## Prediction-only comparison\n',
              'Every backend builds the same ordered `(source address, destination address, data)` '
              'table. SV uses the unchanged `tma_scoreboard.predict`; Python composes the '
              'existing address oracle with memory lookup. Initialized memory and result '
              'readback are outside timing; all predicted beats are compared. Each sample '
              'contains 100 predictions, after three warmups, for seven repetitions. '
              'No backend copies the full destination in this experiment.\n',
              '| Tensor | Python (us) | Native C++ (us) | C++ through DPI (us) | SV scoreboard (us) | SV / DPI |',
              '| --- | ---: | ---: | ---: | ---: | ---: |']
    for r in micro['predictions']:
        b=r['backends'];keys=('python','cpp_native','cpp_dpi','sv_scoreboard')
        times=[b[k]['median_ns']/1000 for k in keys]
        lines.append(f"| {r['side']}x{r['side']} | "+' | '.join(f'{n:,.2f}' for n in times)+f" | {times[3]/times[2]:.2f}x |")
    overhead=[(r['dpi_body_ns']-r['sv_body_ns'])/r['calls'] for r in micro['dpi_dispatch']]
    lines += [f"\nThe additional dispatch estimate was **{statistics.median(overhead):.1f} ns/call** "
              f"(range {min(overhead):.1f}..{max(overhead):.1f}) across seven million-call trials. "
              'Both paths execute an equivalent body and a checked stateful checksum. '
              'The native-call baseline is retained in the raw log. At 1x1, dispatch cost '
              'outweighs the C++ prediction advantage over SV.\n',
              '## Complete RTL/UVM workflow\n',
              'Pipelined engine, BL4, linear scratchpad, seed `20261029`, 34 directed plus '
              '12 procedural generated descriptors. Each run checks 2,937 DMA reads, '
              '2,937 DMA writes and 25,797 maintenance readbacks. The three modes are '
              'interleaved for three repetitions. Every run has identical checked work '
              'and zero UVM warnings/errors/fatals. Compilation is excluded; simulator '
              'startup, execution and log capture are included.\n',
              '| Checker | Median wall seconds [min, max] | Tool-reported simulation CPU ms [min, max] | Peak process MiB [min, max] | Checked DMA elements/s |',
              '| --- | --- | --- | --- | ---: |']
    table=runtime['runtime_comparison'][0]
    for mode in ('sv','cpp','dual'):
        stats=table['backends'][mode];cpus=[]
        for run in runtime['runs']:
            if run['checker']==mode:
                text=(folder/index['logs'][run['log']]).read_text()
                match=re.search(r'Simulation CPU Usage: (\d+) ms',text)
                if match:cpus.append(int(match[1]))
        peaks=[p/1048576 for p in stats['process_peak_bytes']]
        cpu=f'{statistics.median(cpus):,.0f} [{min(cpus):,}, {max(cpus):,}]' if cpus else 'unavailable'
        lines.append(f"| {mode} | {stats['median_seconds']:.3f} [{stats['min_seconds']:.3f}, {stats['max_seconds']:.3f}] | {cpu} | {min(peaks):.2f}..{max(peaks):.2f} | {stats['checked_elements_per_second']:.2f} |")
    ratio=table['sv_over_cpp_wall_ratio']
    lines += [f'\nSV median / C++ median = **{ratio:.3f}x**. The observed C++ median '
              f'was **{(1/ratio-1)*100:.1f}% slower**, and the ranges overlap. Three '
              'repetitions on a shared workstation do not establish a causal slowdown, '
              'but they provide no evidence of end-to-end acceleration.\n',
              'Native C++ API/prediction nanoseconds and call counts are also recorded '
              'per simulation. Their small cost relative to wall time is consistent '
              'with startup and simulator/UVM event work dominating this workload. '
              'This is an inference from the measurements, not a complete per-layer profile. '
              'Simulation checked-elements/s is a verification metric, not hardware bandwidth.\n',
              '## Records and reproduction\n',
              '[Architecture, API and build instructions](cpp_reference.md) · '
              '[Published records and log index](../evidence/cpp_reference/2026-10-29/index.json) · '
              '[Standalone measurements](../evidence/cpp_reference/2026-10-29/standalone/results.json) · '
              '[Prediction/DPI measurements](../evidence/cpp_reference/2026-10-29/microbenchmark/results.json) · '
              '[Interleaved RTL measurements](../evidence/cpp_reference/2026-10-29/runtime_benchmark/results.json)\n',
              'Regenerate these tables with `python scripts/report_reference_performance.py`. '
              'Validate the archived records with `python scripts/check_cpp_evidence.py`. '
              'This report does not change the measured FPGA result of 2.88x for the '
              'original 32x32 transpose.\n']
    target=ROOT/'docs/reference_performance.md'
    target.write_bytes(('\n'.join(lines).rstrip()+'\n').encode())
    print('REFERENCE_PERFORMANCE_REPORT',target)


if __name__=='__main__':main()
