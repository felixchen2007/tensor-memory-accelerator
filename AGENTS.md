# Project verification

The owner requires UVM for RTL verification. New simulation acceptance work must
use the native UVM environment under `tb/uvm`, with sequences, drivers, passive
monitors and the independent scoreboard. Run `scripts/run_uvm_tests.py` for a
verification-only change; the normal `scripts/run_tests.py` and
`scripts/run_sdram_tests.py` entry points also require this suite.

Keep the existing directed benches and pin-level SDRAM model as complementary
checks. Physical FPGA self-tests and JTAG results are separate hardware evidence.

The installed Questa Starter runs UVM 1.2 base classes but denies the
`svverification` feature for `randomize` and covergroups. Its default UVM mode
uses an explicit seeded PRNG and procedural scenario counters. Report those
accurately; do not claim SV constrained-random execution or covergroup closure.
`--full` enables those optional features and requires a suitable simulator
license. Compilation alone is not a verification pass.

Record the tested configuration, seed, source hashes, UVM error/fatal counts,
scenario results and corruption-control result. Do not relabel the earlier
procedural or hardware runs as UVM tests.

The C++17/DPI path is additive: `scripts/run_cpp_reference.py` validates the
standalone model; `scripts/run_dpi_uvm_tests.py --checker dual` retains independent
SV and C++ checking. Use `--checker cpp` for C++ mutation acceptance so the SV
scoreboard cannot mask a missing C++ diagnosis. Keep the original SV baseline.

XSim 2025.2 has separately executed constrained randomization and the descriptor
covergroup in `p1_b4_s0` across three seeds. Use `scripts/run_xsim_full.py --full`
for the verified Windows short-path launcher when the checkout contains spaces.
These results do not change the older Questa Starter feature/license boundary.

`scripts/run_xsim_standalone.py` is an additive Windows/XSim launch adapter.
Use `--launch-compare --repeat 5 --checker dual --profile p1_b4_s0 --seed 20261029`
for matched, interleaved complete-test timings. Do not remove memory readbacks,
stall scenarios, monitors or either scoreboard to claim an equivalent-work
speedup. Simulator throughput and FPGA bandwidth are separate measurements.
