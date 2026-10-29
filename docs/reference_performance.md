# Reference-model and verification performance

Measured on 2026-10-29 UTC on a shared Windows 11 laptop, using Python 3.12.14, GCC 15.1.0 (`-std=c++17 -O2`) and Vivado XSim 2025.2. The original SV scoreboard and production RTL are unchanged.

**Result:** C++ substantially reduces isolated model computation. The full RTL verification workflow did not improve: its C++ median was slightly slower, with overlapping timing ranges. Retaining the SV baseline and optional dual checking provides independent validation without claiming a simulation speedup.

## Correctness before timing

- 21 standalone C++ directed tests; 387 exact Python/C++ comparisons covering complete destination images and read/write traces; 8,192 bank mappings; 100 C API create/reset/destroy lifecycles.
- Eight engine/burst/layout configurations passed with both UVM scoreboards; 368 descriptors. Six completed before a laptop power interruption and two completed afterward with identical source hashes. The partial run retains its `incomplete` status; individual completed logs were revalidated.
- C++-only checking plus existing monitors/pin model detected 21/21 selected mutations: 17 C++ scoreboard diagnoses, three UVM protocol diagnoses and one pin-level refresh deadline. Clean before/after controls passed.
- XSim executed constrained randomization and covergroups for seeds `20261029`, `57` and `991` in `p1_b4_s0`: 138 descriptors; 100% of the defined descriptor covergroup in each run. This is scoped coverage, not exhaustive proof.
- Full DPI integration and dual corruption diagnoses also passed on Questa; the unchanged original eight-profile Questa suite passed independently.

## Complete-copy public API

Both implementations validate all input memory values and materialize full read/write traces and destination copies. Each runs in a separate fresh process without retained cross-validation corpora. Input initialization, compilation and process launch are outside timed computation. Three warmups and seven repetitions are used. Numbers below are medians; raw min/max and samples are retained.

| Tensor | Endpoint words | Python (us/descriptor) | C++ (us/descriptor) | Python / C++ | Python peak process MiB | C++ peak process MiB |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 1x1 | 4,096 | 1,563.48 | 21.29 | 73.44x | 22.43 | 4.38 |
| 8x8 | 4,096 | 1,616.39 | 23.52 | 68.72x | 22.64 | 4.38 |
| 16x16 | 4,096 | 2,214.69 | 25.70 | 86.17x | 22.79 | 4.49 |
| 32x32 | 4,096 | 3,427.43 | 31.80 | 107.77x | 23.13 | 4.52 |
| 64x64 | 4,096 | 8,183.15 | 120.71 | 67.79x | 24.63 | 4.61 |
| 128x128 * | 16,384 | 32,518.88 | 518.00 | 62.78x | 31.60 | 5.16 |

Small tensor cases still validate two complete 4,096-word endpoint arrays; their ratios include this public-API cost. Process peaks include language runtimes and are cumulative across ascending sizes, not model allocation alone. Python traced allocation is recorded separately. The 128x128 case (*) uses synthetic larger endpoints beyond the physical 8 KiB scratchpad.

## Prediction-only comparison

Every backend builds the same ordered `(source address, destination address, data)` table. SV uses the unchanged `tma_scoreboard.predict`; Python composes the existing address oracle with memory lookup. Initialized memory and result readback are outside timing; all predicted beats are compared. Each sample contains 100 predictions, after three warmups, for seven repetitions. No backend copies the full destination in this experiment.

| Tensor | Python (us) | Native C++ (us) | C++ through DPI (us) | SV scoreboard (us) | SV / DPI |
| --- | ---: | ---: | ---: | ---: | ---: |
| 1x1 | 3.19 | 0.16 | 0.72 | 0.66 | 0.92x |
| 8x8 | 33.81 | 0.99 | 1.57 | 27.10 | 17.26x |
| 16x16 | 149.58 | 3.52 | 4.17 | 106.82 | 25.62x |
| 32x32 | 818.27 | 13.99 | 14.73 | 455.22 | 30.90x |
| 64x64 | 3,431.22 | 54.20 | 55.05 | 2,014.60 | 36.60x |

The additional dispatch estimate was **486.1 ns/call** (range 476.1..539.2) across seven million-call trials. Both paths execute an equivalent body and a checked stateful checksum. The native-call baseline is retained in the raw log. At 1x1, dispatch cost outweighs the C++ prediction advantage over SV.

## Complete RTL/UVM workflow

Pipelined engine, BL4, linear scratchpad, seed `20261029`, 34 directed plus 12 procedural generated descriptors. Each run checks 2,937 DMA reads, 2,937 DMA writes and 25,797 maintenance readbacks. The three modes are interleaved for three repetitions. Every run has identical checked work and zero UVM warnings/errors/fatals. Compilation is excluded; simulator startup, execution and log capture are included.

| Checker | Median wall seconds [min, max] | Tool-reported simulation CPU ms [min, max] | Peak process MiB [min, max] | Checked DMA elements/s |
| --- | --- | --- | --- | ---: |
| sv | 11.301 [11.151, 12.250] | 6,843 [6,780, 6,905] | 170.28..171.26 | 259.90 |
| cpp | 11.749 [11.404, 11.999] | 7,093 [6,953, 7,468] | 171.89..172.00 | 249.97 |
| dual | 11.952 [11.686, 12.256] | 7,249 [7,171, 7,358] | 172.39..172.42 | 245.73 |

SV median / C++ median = **0.962x**. The observed C++ median was **4.0% slower**, and the ranges overlap. Three repetitions on a shared workstation do not establish a causal slowdown, but they provide no evidence of end-to-end acceleration.

Native C++ API/prediction nanoseconds and call counts are also recorded per simulation. Their small cost relative to wall time is consistent with startup and simulator/UVM event work dominating this workload. This is an inference from the measurements, not a complete per-layer profile. Simulation checked-elements/s is a verification metric, not hardware bandwidth.

## Records and reproduction

[Architecture, API and build instructions](cpp_reference.md) · [Published records and log index](../evidence/cpp_reference/2026-10-29/index.json) · [Standalone measurements](../evidence/cpp_reference/2026-10-29/standalone/results.json) · [Prediction/DPI measurements](../evidence/cpp_reference/2026-10-29/microbenchmark/results.json) · [Interleaved RTL measurements](../evidence/cpp_reference/2026-10-29/runtime_benchmark/results.json)

Regenerate these tables with `python scripts/report_reference_performance.py`. Validate the archived records with `python scripts/check_cpp_evidence.py`. This report does not change the measured FPGA result of 2.88x for the original 32x32 transpose.
