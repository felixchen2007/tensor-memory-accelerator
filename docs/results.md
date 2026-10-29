# Recorded results

The current release preserves the tested RTL and publishes selected evidence
alongside the source. Paths and host identifiers in exported records are
sanitized; numeric measurements, source/image hashes, packets and outcomes are
retained. [Evidence provenance](../evidence/README.md).

## Physical DE10-Lite benchmark · 2026-10-29 UTC

Same 32×32 sixteen-bit SDRAM-to-scratchpad transpose, 2,048 useful bytes, nominal
50 MHz and an equal refresh start phase. Two fresh configurations per variant;
each verified 1,024 scratchpad words, 1,024 source words, successful transfer
status/count and all 1,024 destination words.

| Variant | Cycles | Latency | LEs / registers | Worst setup / hold |
| --- | ---: | ---: | ---: | ---: |
| Serialized BL1 | 16,525 | 330.50 µs | 2,477 / 1,652 | +1.578 / +0.148 ns |
| Pipelined BL1 | 13,541 | 270.82 µs | 2,703 / 1,863 | +1.584 / +0.148 ns |
| Pipelined BL4 | 5,735 | 114.70 µs | 2,856 / 1,953 | +1.584 / +0.147 ns |

BL4 plus pipelining gives **2.88143× cycle speedup** over serialized BL1 and
**2.36112×** over pipelined BL1. All images use 65,536 RAM bits and one PLL.
Counters exclude initialization, maintenance, preflights and final readback.
Tile payload rates are derived from descriptor latency, not sustained streaming.

- [Comparison summary](../evidence/hardware/2026-10-29/results.json)
- [Serialized run](../evidence/hardware/2026-10-29/0_serialized/run.json)
- [Pipeline run](../evidence/hardware/2026-10-29/1_pipelined/run.json)
- [Burst run and complete fitted report](../evidence/hardware/2026-10-29/2_pipelined_burst4/board_results.json)
- [Repeated burst run and raw packets](../evidence/hardware/2026-10-29/5_pipelined_burst4/probe.log)
- [Methodology and limits](hardware_benchmark.md)

The clock-routing warning remains open. This test does not establish full
64 MiB coverage, long retention, temperature margins, jitter tolerance or
power-cycle reliability. Whole-image resource counts include diagnostics.

## Native UVM · 2026-10-29 UTC

Eight configurations: serialized/pipelined × BL1/BL4 × linear/XOR layout.
Each executes 34 directed and 12 generated descriptors with seed `20261029`.

| Check | Result across the nominal matrix |
| --- | ---: |
| Descriptors | 368 |
| DMA reads / writes checked | 23,496 / 23,496 |
| Maintenance readbacks checked | 206,376 |
| Required bank/access-family combinations | 20 per profile |
| UVM warnings / errors / fatals | 0 / 0 / 0 per profile |

The ninth UVM run intentionally changes an SDRAM read value from `a55a` to
`a55b`. It must report `TMA_READ_DATA` and no pass marker. It does so.

These results use genuine UVM classes with seeded procedural stimulus and
scenario counters. SV constrained randomization and covergroups were not
executed: the installed license denied `svverification`. The optional branch
compiled with zero errors/warnings, which establishes syntax compatibility only.

- [UVM result and source hashes](../evidence/uvm/2026-10-29/results.json)
- [Nominal report and topology](../evidence/uvm/2026-10-29/p1_b4_s0.log)
- [Injected-corruption report](../evidence/uvm/2026-10-29/data_fault_control.log)
- [Environment and scenario plan](uvm.md)

## Complementary directed simulation · 2026-10-29 UTC

The focused run passed **35 invocations**: 26 directed simulations/controls and
nine UVM runs. Ten controls deliberately fail and require the specified checker
to detect the injected fault. The directed tensor subset checks 393,216
destination words across 96 descriptors. The pin model checks refresh deadlines,
mode registers, burst beats, turnaround, setup and hold. It is a digital model;
it does not include fitted PCB delays or prove electrical behavior.

All **52 Python tests** passed. The fitted build gate checks reported corner
slacks, constraint coverage, all 50 user pins and image/source hashes. Physical
execution is recorded separately from a successful build.

- [Focused regression](../evidence/simulation/2026-10-29/results.json)
- [Burst tradeoffs](../evidence/simulation/2026-10-29/burst_comparison.md)
- [Verification details and remaining gaps](verification.md)

## Historical local-memory studies · 2026-10-27 UTC

The earlier full-project simulation record predates the current SDRAM and UVM
acceptance changes. Its hashes identify that revision; it is not a fresh
full-project pass for this publication.

| Controlled simulation | Serialized / optimized | Ratio |
| --- | ---: | ---: |
| 32×32 local transfer, minimum latency | 5,121 / 1,030 cycles | 4.972× |
| Same shape, transaction-indexed variable delays | 15,385 / 6,227 cycles | 2.471× |
| Four-lane stride-32 scratchpad batch | 4 / 1 issue cycles | 4× issue-span reduction |
| Stride-33 diagonal, linear / XOR shift 5 | 1 / 4 issue cycles | Regression |

The banking experiment and the single-stream pipeline experiment use different
interfaces/workloads. Their ratios are not multiplied and are not physical
SDRAM speedups.

- [Historical full-regression record](../evidence/simulation/2026-10-27/results.json)
- [Paired engine measurements](../evidence/simulation/2026-10-27/pipeline_comparison.md)
- [Bank-layout measurements](../evidence/simulation/2026-10-27/swizzle_comparison.md)

Run `python scripts/check_portfolio.py` to verify published evidence integrity,
current hardware/UVM source hashes, decoded packets, ratios and document links.
Fresh simulation and fitting commands are in [the reproduction guide](reproduce.md).
