# Release scope and roadmap

The current release is a working memory-accelerator prototype with a measured
board comparison. A compute consumer is an optional extension to this release.

## Implemented and demonstrated

| Area | Evidence |
| --- | --- |
| Strided 2D addressing | Independent mathematical oracle; stalls, boundaries, counts and reset checks |
| Serialized and pipelined engines | Paired correctness/error-prefix tests; ordered channels and FIFO |
| Banked scratchpad | M9K inference; collisions, four-lane service and layout tradeoffs |
| SDRAM source | Project controller; initialization, refresh, BL1/BL4 and pin model |
| Board implementation | Constraints, 50 fitted user pins, positive reported corner slacks |
| Physical comparison | Three variants, two fresh configurations each, full tile checks |
| UVM acceptance | Eight configurations, 368 descriptors, independent scoreboard and corruption control |
| Checker sensitivity | 21/21 selected RTL mutants detected in native UVM; clean before/after controls and source hashes |
| C++17 reference model | 21 directed tests, 387 exact Python/C++ cases, 8,192 bank mappings and 100 API lifecycles |
| DPI-C interoperability | Separate Questa/XSim ABI proofs; eight XSim dual-scoreboard configurations and C++-only mutations |
| Executed constrained randomization | XSim p1_b4_s0, three seeds, 138 descriptors and the defined descriptor covergroup |
| Reproducibility | Source/image hashes, published records, offline replay and model/evidence CI |

[Results](results.md) · [Reproduction](reproduce.md) · [UVM plan](uvm.md).

## Finish-up validation

- Investigate the non-dedicated SDRAM clock route and characterize timing margin.
- Test more physical addresses and all banks, additional patterns/strides, longer
  runs and retention. Current physical evidence covers one 2 KiB tile.
- Capture a short video of a freshly configured board and decoded counters.
- Extend constrained-random/covergroup runs beyond the currently executed
  `p1_b4_s0` three-seed set, and add protocol SVA. Preserve the earlier Starter
  procedural results as distinct evidence.

## Optional extensions

- Runtime descriptor control through a defined host interface.
- A small matrix kernel with bit-exact reference outputs.
- Automatic double-buffer ownership and measured load/compute overlap.
- SDRAM tensor writeback, write bursts and open-row scheduling.
- Sustained multi-tile throughput, resource/frequency sweeps and power measurements.

Each extension needs its own UVM acceptance, implementation reports and matched
benchmark. Preserve the serialized baseline and existing evidence.

## Evidence-supported project description

> Designed a SystemVerilog tensor mover on a MAX 10 FPGA with strided 2D
> addressing, banked SRAM, pipelined transfers and burst read prefetch; measured
> 2.88× cycle speedup over a serialized baseline for a 32×32 sixteen-bit
> SDRAM-to-SRAM transpose at nominal 50 MHz, with repeated hardware readback and
> native UVM verification.

The 2.88× result is a tile-latency comparison. The separate 4.97× local-memory
result is simulated. Neither is a comparison against a commercial DMA or GPU.
