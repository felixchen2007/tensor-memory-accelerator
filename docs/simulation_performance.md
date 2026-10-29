# Simulator launch optimization

The C++ predictor is a small part of the complete RTL/UVM runtime. The earlier
interleaved measurement found no complete-test improvement from replacing the
SV predictor with C++. Those [measurements remain unchanged](reference_performance.md).

The normal XSim logs report about seven seconds inside `run all`, while the
complete process takes roughly twelve seconds. This identifies substantial
launch/control overhead alongside actual simulation work. It does not identify
which RTL process, UVM component or SDRAM-model operation dominates the remaining
simulation time. The C++ API itself takes approximately eleven milliseconds
across all 44,673 calls in a representative complete test.

The new [standalone launcher](../scripts/run_xsim_standalone.py) compiles the
same design with XSim's `--standalone` option and runs its generated `axsim.exe`
directly. Vivado's runtime DLL paths apply only to that child process. The
existing runner, RTL, sequences, drivers, passive monitors, pin-level SDRAM model
and independent SV/C++ scoreboards retain their original source hashes.
[AMD documents standalone simulation](https://docs.amd.com/r/2025.2-English/ug900-vivado-logic-simulation/xelab-xvhdl-and-xvlog-xsim-Command-Options)
as a way to avoid Vivado IDE launch overhead.

## Matched complete-test measurement

Five interleaved pairs on Windows / XSim 2025.2:

| Launch mode | Median wall seconds | Range, seconds |
| --- | ---: | ---: |
| Normal XSim batch | 12.943 | 12.148–13.945 |
| Standalone executable | 7.913 | 7.252–8.671 |

The median decreases by **38.86%**, or **1.636x** as many identical runs per
unit time. This is a separate simulator launch improvement, not a performance
claim for the C++ predictor. These measurements use the current matched pairs;
the older checker-backend comparison used separate runs on the same workstation.

Every nominal sample uses `p1_b4_s0`, seed `20261029`, both independent
scoreboards, 34 directed and 12 procedural generated descriptors. Each checks
2,937 DMA reads, 2,937 DMA writes and 25,797 maintenance readbacks, and finishes
at 4,654,430 ns of simulated time. No readbacks or response-stall tests are
removed. Normal and standalone runs alternate order for each pair and execute
sequentially, with no other project simulator running. Compilation is outside
the wall sample; process launch, complete simulation and log capture are inside.

The deliberate-corruption control is also compared in both launch modes and
must retain both `TMA_CPP_READ_DATA` and `TMA_READ_DATA` diagnoses. It is not
included in the nominal speed calculation.

This measures verification throughput on one Windows workstation and one RTL
configuration. It does not change the FPGA design or its separately measured
2.88x hardware result. The remaining runtime still includes event scheduling,
SDRAM timing, UVM transactions and public-interface memory readbacks; their
individual contributions require further profiling.

## Verification and reproduction

Standalone XSim separately passed native UVM constrained randomization and the
defined descriptor covergroup in `p1_b4_s0`, using seeds `20261029`, `57` and
`991`. Each seed completed 46 descriptors with zero UVM warnings/errors/fatals
and 100% of that descriptor covergroup. Both independent scoreboards detected
the deliberate data corruption. This scope does not imply coverage closure of
the entire design. The original Questa seeded-procedural eight-configuration
suite and its corruption control were also rerun.

```powershell
# Same native UVM suite, faster launch, procedural stimulus:
python scripts/run_xsim_standalone.py --checker dual --profile p1_b4_s0

# Reproduce the matched launch comparison; one configuration/seed/checker mode:
python scripts/run_xsim_standalone.py --checker dual --profile p1_b4_s0 --seed 20261029 --repeat 5 --launch-compare

# Executed SV randomize and descriptor covergroup; XSim 2025.2:
python scripts/run_xsim_standalone.py --full --checker dual --profile p1_b4_s0 --seed 20261029 --seed 57 --seed 991

# Original acceptance suite and offline record validation:
python scripts/run_uvm_tests.py
python scripts/check_simulation_launch.py
```

The adapter currently targets Windows and the installed XSim 2025.2 runtime.
Use the existing interactive runner for waveform/debug sessions and the existing
mutation runners for the archived fault campaign. The optional constrained-random
mode remains separate from Questa Starter's procedural stimulus and licensing.

[Recorded comparisons, source hashes and raw logs](../evidence/simulation_launch/2026-10-29/index.json)
