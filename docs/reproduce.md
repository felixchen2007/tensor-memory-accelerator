# Reproduce the project

## Requirements

- Python **3.10+** and the packages in [requirements-verification.txt](../requirements-verification.txt).
- For RTL simulation: Questa with SystemVerilog support. Tested on Windows
  with Questa Intel Starter FPGA Edition **2024.3**. Historical UVM replay also
  uses the simulator's UVM **1.2** sources and DPI library.
- For fitting: Quartus Prime Lite **24.1std**, MAX 10 device support,
  target **10M50DAF484C7G**.
- For physical checks: Terasic **DE10-Lite**, onboard USB-Blaster and
  **IS42S16320F-7TL** SDRAM. PCB revision has not been recorded.

Questa/Quartus and their vendor simulation libraries must be installed separately.
They are not downloaded or redistributed by this repository. The UVM runner
currently targets the Windows Questa installation layout. Reference-model and
evidence checks work without FPGA tools on Windows or Linux.

## Checks without a board or simulator

From the root of a Git clone with history:

```sh
python -m pip install -r requirements-verification.txt
python -m pytest tests -q
python scripts/check_portfolio.py
python scripts/read_board_status.py --transcript evidence/hardware/2026-10-29/5_pipelined_burst4/probe.log
```

Pytest runs the 58 portable Python tests. The evidence checker checks the published
record hashes, archived source bytes, hardware packet decoding/ratios, UVM reports
and local documentation links. The third decodes saved digital JTAG evidence.
These checks do not establish a fresh RTL or physical-board pass.

## Tool discovery

The runners search PATH and common Windows installations. Override discovery
with directories containing the relevant executables:

```powershell
$env:QUESTA_BIN = 'C:/altera_lite/24.1std/questa_fse/win64'
$env:QUARTUS_BIN = 'C:/altera_lite/24.1std/quartus/bin64'
```

Questa licensing must already be configured using the simulator's normal setup.
If Questa cannot load cocotb from a path with spaces, install the verification
dependencies in a Python environment whose path contains no spaces.
The observed Starter license runs native UVM components, but denies the
`svverification` feature for `randomize` and covergroups. The archived UVM runs
use seeded procedural stimulus and scenario counters. [UVM details](uvm.md).

## RTL verification

```powershell
# Eight cocotb configurations plus a corruption control
python -m pytest tb/cocotb/test_regression.py -q
# Single profile
python -m pytest tb/cocotb/test_regression.py -q -k p1_b4_s0
# Focused SDRAM/board regression, including cocotb
python scripts/run_sdram_tests.py
# Full project regression, including local studies and cocotb
python scripts/run_tests.py
```

`p1_b4_s0` means pipelined engine, four-word reads and linear scratchpad layout.
Each cocotb profile runs 34 directed plus 12 seeded descriptors. The corruption
control succeeds when the DMA data checker detects the injected bit flip.
Pytest's temporary directory holds per-profile simulator logs, XML results and
JSON reports with the seed, profile, observed scenarios and source hashes.
The standard scripts retain these files under `build/` and include the per-profile
reports in their result JSON. Use `pytest --basetemp` with a fresh directory
to retain files from a direct run.

The archived [RTL mutation campaign](mutation.md) uses UVM in `p1_b4_s0` with
34 directed descriptors plus cache probes. It compiles temporary source copies,
requires a specific checker diagnosis for every defect and verifies unchanged
canonical source hashes. It is separate from the eight-profile nominal matrix.

Historical UVM replay and optional licensed features:

```powershell
python scripts/run_uvm_tests.py
python scripts/run_mutation_tests.py
python scripts/run_uvm_tests.py --full --compile-only
# Requires the simulator's SV verification license:
python scripts/run_uvm_tests.py --full
```

Compilation alone is reported as `compiled-only`, never as verification or
coverage closure. The published optional branch was compiled, not executed.

## Build all three board variants

```powershell
python scripts/build_board.py --engine serialized
python scripts/build_board.py --engine pipelined
python scripts/build_board.py --engine pipelined --read-burst 4
```

The builder runs analysis, synthesis, fitting and timing analysis; checks corner
slacks, constraint coverage and all 50 user pins; then records sources, resources,
warnings and SOF hashes. Outputs are in `build/quartus/de10_lite_serialized`,
`build/quartus/de10_lite`, and `build/quartus/de10_lite_burst4`. No board is accessed.
Vendor tools and implementation seeds can affect fitted results and binary hashes.

The recorded images retain Quartus warning 15064 for non-dedicated PLL-to-SDRAM
clock routing. Timing uses documented PCB-delay assumptions. Read
[the clock contract](sdram.md) and [hardware limitations](hardware_benchmark.md)
when interpreting a passing build.

## Physical demonstration

Run the focused simulation and three fits from the current sources before the
hardware benchmark. With the board connected:

```powershell
python scripts/benchmark_board.py --hardware --include-burst
```

This explicitly programs **volatile SOF configuration** over USB-Blaster. It
checks the expected chain, validation/source/image hashes, alternates the three
variants twice, requires complete preflight/transpose success and leaves the
burst image loaded. Configuration flash is not written. Results are recorded
under `build/hardware/`; the baseline comparison uses a common refresh phase.

To read the currently loaded project's probes without programming:

```powershell
python scripts/read_board_status.py --hardware
```

For offline comparison, supply the six published `run.json` records to
`python scripts/benchmark_board.py --records` in their numbered order.
[Demo walkthrough](demo.md) · [Results](results.md).

## Source identity and publication

`evidence/manifest.json` hashes the exported report files. Those reports retain
the tested RTL/UVM/build source hashes. Git attributes preserve source bytes and
original line endings so Windows/Linux checkouts can verify those hashes.
When implementation sources change, old measurements stay historical; rerun
the relevant simulation/fits and publish a new dated evidence set.
