# Project verification

Use pytest and cocotb for new RTL acceptance work. The normal
`scripts/run_tests.py` and `scripts/run_sdram_tests.py` entry points run the
cocotb matrix. Run `python -m pytest tb/cocotb/test_regression.py` for focused
acceptance and `python -m pytest tests` for the portable Python checks.

Keep the directed benches and pin-level SDRAM model as complementary checks.
The native UVM suite and mutation campaign reproduce the archived UVM evidence.
Physical FPGA self-tests and JTAG results are separate hardware evidence.

Record the tested configuration, seed, source hashes, scenario results and
corruption-control result. Compilation alone is not a verification pass.
Describe the Python scenario bins as observed scenarios. Preserve the original
framework labels on archived runs.
