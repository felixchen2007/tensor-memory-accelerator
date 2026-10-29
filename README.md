# Tensor Memory Accelerator

[![Model and evidence checks](https://github.com/felixchen2007/tensor-memory-accelerator/actions/workflows/checks.yml/badge.svg)](https://github.com/felixchen2007/tensor-memory-accelerator/actions/workflows/checks.yml)

**SystemVerilog tensor data movement on a Terasic DE10-Lite / MAX 10 FPGA.**
Descriptor-driven 16-bit copies and transposes from external SDRAM into a banked
scratchpad, with a preserved serialized baseline, pipelined transfers, and
four-word burst read prefetch.

**Measured on hardware: 2.88× cycle speedup for a 32×32 transpose**, from
16,525 to 5,735 cycles at nominal 50 MHz. Three implementations each passed two
fresh FPGA configurations and complete tile readback. Native UVM verification
passed 368 descriptors across eight configurations and detected injected data
corruption. [Results and evidence](docs/results.md) · [Reproduce](docs/reproduce.md)

## Hardware result

Same 2 KiB tensor, data pattern, clock, destination layout, and refresh start
phase. Seeding, memory preflights, and final readback are outside the descriptor
counter. Recorded on **2026-10-29 UTC**.

| Implementation | Descriptor cycles | Latency at 50 MHz | Speedup vs baseline | Logic elements | Registers |
| --- | ---: | ---: | ---: | ---: | ---: |
| Serialized, single-word reads | 16,525 | 330.50 µs | 1.00× | 2,477 | 1,652 |
| Pipelined, single-word reads | 13,541 | 270.82 µs | 1.22× | 2,703 | 1,863 |
| Pipelined, four-word prefetch | **5,735** | **114.70 µs** | **2.88×** | 2,856 | 1,953 |

All fits use 65,536 RAM bits and one PLL. Counts include the complete board test
and diagnostics. The BL4 image's worst reported setup/hold slacks are
+1.584 / +0.147 ns under the documented external-delay assumptions.
[Six hardware runs and image hashes](evidence/hardware/2026-10-29/results.json).

This result covers one 2 KiB tile crossing a row boundary in SDRAM bank 1.
Sustained bandwidth, full-memory coverage, retention, and temperature/jitter
qualification remain open. Quartus warning 15064 for non-dedicated SDRAM clock
routing remains documented in [the hardware methodology](docs/hardware_benchmark.md).

## Implemented architecture

```mermaid
flowchart LR
    D[2D descriptor] --> A[Address generator]
    A --> E[Serialized / pipelined engine]
    M[64 MiB x16 SDRAM] <--> C[Refresh-capable SDRAM controller]
    C --> B[Optional 4-word read buffer]
    B --> E
    E --> P[8 KiB / 4-bank scratchpad]
    T[Onboard self-test / maintenance port] --> C
    T --> P
    E --> S[Status and cycle counters]
    T --> J[Passive JTAG diagnostics]
    S --> J
```

- **Addressing:** 32-bit byte addresses, 16-bit row/column counts and element
  data, independent source/destination byte strides, transpose and broadcast.
- **Pipeline:** separate ordered read/write channels and a four-entry FIFO;
  stable stalled requests, completion tracking, and error draining.
- **SDRAM:** project-authored IS42S16320F-7TL controller, initialization, refresh
  during held responses, closed rows, BL1 or BL4 reads, and single-word writes.
- **Scratchpad:** four inferred M9K banks, four read lanes, linear/XOR mapping,
  response backpressure and defined read/write collision behavior. The copy
  engine itself uses one 16-bit stream.
- **Diagnostics:** scratchpad/source preflights, full tile readback, stage/error
  records, passive read capture and versioned JTAG status decoding.

## Verification

The native **UVM 1.2** environment uses sequences, a sequencer/driver, passive
host and DMA monitors, an independent data/address/commit scoreboard, and a
scenario subscriber. It drives the real tensor-system RTL and an independent
SDRAM pin model through public maintenance/descriptor interfaces.

| Recorded check | Result |
| --- | --- |
| UVM configuration matrix | 2 engines × 2 read modes × 2 layouts; 368 descriptors |
| UVM data checks | 23,496 DMA reads, 23,496 DMA writes, 206,376 maintenance readbacks |
| UVM nominal severity counts | Zero warnings, errors, or fatals in every profile |
| Corruption control | Deliberately wrong SDRAM data detected by the scoreboard |
| Focused simulation regression | 35 invocations, including 10 expected-failure controls |
| Python reference/decoder/report tests | 52 tests passed |

The tested Questa Starter license runs UVM base classes with seeded procedural
stimulus and explicit scenario counters. SV constrained randomization and
covergroups require a suitable license; that optional branch compiled but was
not executed. See [UVM scope and reports](docs/uvm.md) and
[verification strategy](docs/verification.md). Hosted CI runs Python model and
evidence checks; RTL simulation and FPGA fitting run locally with vendor tools.

## Reproduce

Python 3.10+; no third-party Python packages are needed. From a fresh checkout:

```sh
python -m unittest discover -s tests -v
python scripts/check_portfolio.py
```

For Windows with Questa and Quartus Prime Lite installed:

```powershell
python scripts/run_uvm_tests.py
python scripts/run_sdram_tests.py
python scripts/build_board.py --engine serialized
python scripts/build_board.py --engine pipelined
python scripts/build_board.py --engine pipelined --read-burst 4
```

These commands do not program a board. Tool setup, the full regression,
volatile hardware configuration, and offline replay are in
[the reproduction guide](docs/reproduce.md).

## Engineering tradeoffs

Burst prefetch amortizes ACTIVATE/PRECHARGE overhead across neighboring words.
It also regresses on sparse loads: the simulated column-gather case rises from
3,387 to 4,167 cycles while fetching four times as much data.
[Burst study](docs/bursts.md).

In the separate four-lane scratchpad study, XOR banking reduces a stride-32
column batch from four issue cycles to one; a stride-33 diagonal regresses from
one to four. This is distinct from the single-stream engine benchmark.
[Bank-layout study](docs/swizzle.md).

## Explore the project

| Path | Contents |
| --- | --- |
| [rtl/](rtl) | Address generator, two engines, scratchpads, SDRAM controller and board top |
| [tb/uvm/](tb/uvm) | Native UVM environment |
| [tb/](tb) | Directed benches, paired timing models and independent SDRAM model |
| [model/](model) and [tests/](tests) | Mathematical references, status decoders and Python tests |
| [quartus/](quartus) | MAX 10 synthesis, pin assignments, constraints and JTAG scripts |
| [scripts/](scripts) | Regressions, fitted builds, hardware benchmark and evidence checks |
| [evidence/](evidence) | Portable measured records, transcripts, source hashes and provenance |
| [Architecture](docs/architecture.md) | Descriptor/interface contract and design decisions |
| [Board debugging](docs/board_runs.md) | Failed read, diagnostic trace, working change and remaining limit |
| [Demo](docs/demo.md) | Repeatable demonstration and result interpretation |
| [Roadmap](docs/milestones.md) | Current release scope and optional extensions |

The memory-accelerator prototype is implemented. Runtime host control, a compute
consumer, automatic double buffering, SDRAM tensor writeback and open-row
scheduling are extensions. This independent educational design does not imply
compatibility with NVIDIA's Tensor Memory Accelerator. Vendor dependencies and
attribution are listed in [THIRD_PARTY.md](THIRD_PARTY.md).
