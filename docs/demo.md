# Demonstrate the accelerator

The repository contains recorded results and an offline replay. A video has not
yet been recorded; the following steps define a reproducible hardware demo.

## Offline review · no FPGA required

1. Read the three hardware measurements in the README: serialized BL1,
   pipelined BL1, and pipelined BL4. Explain what changed between them.
2. Run `python scripts/check_portfolio.py` to validate evidence integrity,
   current hardware/UVM source identity and all six hardware results.
3. Decode the repeated burst run:

   ```sh
   python scripts/read_board_status.py --transcript evidence/hardware/2026-10-29/5_pipelined_burst4/probe.log
   ```

   Expected: `status=pass`, `engine=pipelined`, `read_burst_words=4`,
   `elapsed_cycles=5735`, and 1,024 checked words in all three check stages.
4. Inspect the [UVM corruption-control report](../evidence/uvm/2026-10-29/data_fault_control.log).
   The expected error shows actual `a55b` versus predicted `a55a`; nominal
   profiles have zero UVM errors/fatals.
5. Show the [sparse-load regression](bursts.md). Explain why fetching unused
   burst words can cost more than it saves.

## Hardware recording

Follow [tool setup and build instructions](reproduce.md). Connect the DE10-Lite,
run `python scripts/benchmark_board.py --hardware --include-burst`, and capture
the board plus decoded result for each freshly configured variant. The runner
uses volatile configuration, not configuration flash.

Passing autonomous tests light LEDR0 and LEDR1, leave LEDR2/LEDR3 off, and blink
LEDR4. The saved JTAG packets provide stronger evidence than LEDs alone:
both memory preflights, transfer completion and every output word must pass.

A concise recording should show the board identity, three cycle counts, matching
tensor dimensions/data checks, the implementation diagram, and the remaining
clock-routing limitation. Report the result as **tile latency at nominal
50 MHz**, with seeding/readback excluded, rather than sustained bandwidth.
