# Four-word SDRAM read prefetch

`READ_BURST_WORDS=4` selects a four-word SDRAM read burst and an eight-byte,
single-line read buffer. The default value 1 retains the single-word baseline.
Both use the same sixteen-bit ready/valid interface, CL3, 50 MHz clocks, closed
rows, descriptor engines, scratchpad layout, pins, and external timing budgets.

## Executed result: 2026-10-29 UTC

The burst image passed two fresh configurations at **5,735 descriptor cycles**
for the 32x32 transpose: **114.70 us** at nominal 50 MHz. The matched serialized
and pipelined BL1 images passed twice at 16,525 and 13,541 cycles. Thus BL4
prefetch is **2.88x over serialized** and **2.36x over pipelined BL1** for this
2 KiB tile. All six runs verified both preflights and all destination words.
[Raw evidence and image hashes](../evidence/hardware/2026-10-29/results.json)
are preserved with source snapshots. Current fitted usage is 2,856 LEs and
1,953 registers, with the same 65,536 RAM bits and one PLL as the BL1 profiles.

The independent descriptor simulations show both gains and costs:

| Pipelined workload | BL1 cycles | BL4 cycles | READ commands, BL1 / BL4 | Data beats, BL1 / BL4 |
| --- | --- | --- | --- | --- |
| 32x32 copy/transpose | 13,539 | 5,733 | 1,024 / 256 | 1,024 / 1,024 |
| Padded 8x16 | 1,693 | 721 | 128 / 32 | 128 / 128 |
| Column gather | 3,387 | 4,167 | 256 / 256 | 256 / 1,024 |
| Broadcast, 32 words | 427 | 83 | 32 / 1 | 32 / 4 |
| One last word | 18 | 21 | 1 / 1 | 1 / 4 |

The column gather is **23.0% slower** with four times the fetched data. Broadcast
gains reflect reuse as well as burst fetching. The standalone simulations use a
different initial refresh phase from the board harness; their cycle counts differ
by two for the large tiles. [Generated metrics](../evidence/simulation/2026-10-29/burst_comparison.md)
retain all cases. All 52 Python tests and 26 focused simulations passed, including
393,216 destination comparisons and nine deliberate fault controls.

## What changes

A miss rounds the column down to a four-word boundary, issues ACTIVATE and one
READ, and captures four consecutive sixteen-bit beats. The requested offset is
returned after PRECHARGE/recovery. The other three words stay in the buffer.
Later reads in that line use the buffered word without another SDRAM command.
A miss to another line replaces it. The tag includes bank, row, and column bits.
Aligned lines cannot cross a row or exceed the final device address.

Every accepted write invalidates the entire buffer, including writes that later
return an address error. The controller owns this SDRAM interface; coherence
with independent writers is not provided. Refresh retains buffered data and
continues through response stalls. Reset invalidates the buffer; the existing
cold-start-only SDRAM reset contract still applies.

Mode register `0x232` programs sequential BL4 reads, CL3, and M9=1 for
single-location writes. Thus host seeding retains the existing one-word WRITE
protocol. This combination and burst wrapping follow the
[ISSI mode-register specification, pages 24–26](https://www.mouser.com/datasheet/2/198/42-45R-S_86400F-16320F-706495.pdf).
The baseline remains mode `0x030`. Write bursts and open-row scheduling are not
implemented by this change.

## Why it can help, and when it costs more

A contiguous 1,024-word tile needs 256 READ commands instead of 1,024, with the
same 1,024 data beats. ACTIVATE/PRECHARGE overhead is amortized across four words.
A transpose still benefits because this engine reads its source sequentially
and changes destination strides. Broadcasts can reuse a buffered word.

A scattered load can miss on every word, fetching four beats while using one.
It then pays extra data latency and traffic. The mode is selected at build time;
there is no adaptive stride-based policy. The comparison includes single-word,
contiguous, padded, column-gather, and broadcast cases to expose these tradeoffs.

## Verification contract

The independent pin-level model decodes the mode register and generates every
burst beat with sequential wrapping. Unseeded neighboring words have unspecified
data; the logical scoreboard checks only requested, initialized words. This
allows a last-word or sparse read to prefetch legal neighbors without assuming
their contents. The model rejects PRECHARGE before burst completion and rejects
an incorrect write-burst mode.

Controller tests cover all address bits, bank/row ends, every offset, response
stalls, refresh stress, one burst reused by four requests, write invalidation,
and replacement. Twelve descriptors run in both engines and both bank layouts,
checking all 4,096 destination words per case. CSV metrics count READ commands
and data beats during each descriptor, excluding maintenance.

The board test reads back every source and destination word. Its nominal BL4
simulation must show 512 READ commands and 2,048 beats across source preflight
plus transpose; BL1 uses 2,048 commands for those same 2,048 words. Hardware
latency is measured by the descriptor counter; physical traffic counts come
from simulation, not an on-chip bus analyzer.

Format 4 identifies the BL4 board image: it preserves format-3 fields but sets
the version byte to 4 and low-nibble bit 2 to 1. The decoder rejects an image
whose mode tag differs from its build record. The read trace now records the
last physical miss, not subsequent buffered hits; sample `8 + requested offset`
contains the requested miss word.

## Build and measure

```powershell
python scripts/run_sdram_tests.py
python scripts/build_board.py --engine serialized --read-burst 1
python scripts/build_board.py --engine pipelined --read-burst 1
python scripts/build_board.py --engine pipelined --read-burst 4
python scripts/benchmark_board.py --hardware --include-burst
```

The last command requires a connected board and explicit hardware authorization.
It checks current validation hashes before temporary SOF configuration. It runs
each of the three variants twice and leaves the burst image loaded. Configuration
flash is not written. See [benchmark methodology](hardware_benchmark.md) for
refresh alignment, payload-rate definitions, and clock-routing limitations.
