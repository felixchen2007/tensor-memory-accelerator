# Reproduce the project

## Requirements

- Python **3.10+**; all project Python checks use the standard library.
- For RTL simulation: Questa with SystemVerilog support. Tested on Windows
  with Questa Intel Starter FPGA Edition **2024.3** and its UVM **1.2** sources/DPI.
- For fitting: Quartus Prime Lite **24.1std**, MAX 10 device support,
  target **10M50DAF484C7G**.
- For physical checks: Terasic **DE10-Lite**, onboard USB-Blaster and
  **IS42S16320F-7TL** SDRAM. PCB revision has not been recorded.

Questa/Quartus and their vendor simulation libraries must be installed separately.
They are not downloaded or redistributed by this repository. The UVM runner
currently targets the Windows Questa installation layout. Reference-model and
evidence checks work without FPGA tools on Windows or Linux.

## Checks without a board or simulator

From the repository root:

```sh
python -m unittest discover -s tests -v
python scripts/check_portfolio.py
python scripts/read_board_status.py --transcript evidence/hardware/2026-10-29/5_pipelined_burst4/probe.log
```

The first command runs the 52 Python tests. The second checks the published
record hashes, actual source bytes, hardware packet decoding/ratios, UVM reports
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
The observed Starter license runs native UVM components, but denies the
`svverification` feature for `randomize` and covergroups. Default runs use seeded
procedural stimulus and scenario counters. [UVM details](uvm.md).

## RTL verification

```powershell
# Native UVM: eight configurations plus a corruption control
python scripts/run_uvm_tests.py
# Single profile and explicit stimulus seed
python scripts/run_uvm_tests.py --profile p1_b4_s0 --seed 20261029 --random-cases 12
# Focused SDRAM/board regression, including UVM: 35 invocations
python scripts/run_sdram_tests.py
# Full project regression, including local studies and UVM: 44 invocations
python scripts/run_tests.py
```

`p1_b4_s0` means pipelined engine, four-word reads and linear scratchpad layout.
Each default UVM profile runs 34 directed plus 12 generated descriptors. A fault
control succeeds only when the designated checker detects the intended fault.
Logs and hashes are written under `build/`; a failed run cannot retain a stale
successful summary. The published current focused result is separate from the
historical full-project run.

Optional licensed features:

```powershell
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
