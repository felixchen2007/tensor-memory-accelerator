# Selectable bank mapping and measured tradeoffs

The four-bank scratchpad now supports compile-time linear or XOR bank mapping.
The default remains linear. Both maps present the same logical word/byte
addresses, tensor values, capacity, read latency, and ready/valid contracts.

## Mapping and reversibility

With logical word index `w` (byte address divided by two):

```text
physical row  = w >> 2
linear bank   = w & 3
swizzled bank = (w & 3) XOR ((w >> SWIZZLE_SHIFT) & 3)
```

Parameters on `tma_scratchpad`, its byte adapter, and the local copy system:

| Parameter | Default | Meaning |
| --- | --- | --- |
| `SWIZZLE` | 0 | 0 selects linear mapping; 1 selects XOR mapping |
| `SWIZZLE_SHIFT` | 5 | Selects two higher word-address bits for the XOR |

When enabled, the shift must be between 2 and `ROW_W`, inclusive. An elaboration
assertion fails at time zero for values outside that range. Higher bits stay in the physical row,
so the mapping is reversible:

```text
mask          = (physical_row >> (SWIZZLE_SHIFT - 2)) & 3
logical_low   = physical_bank XOR mask
logical_word  = (physical_row << 2) | logical_low
```

The inverse and exhaustive mapping checks establish that the 4,096 logical
words map to 4,096 distinct bank/row locations. Both read arbitration and write
decoding call the same RTL mapping function; row addressing is unchanged.
Same-edge forwarding still compares the selected physical bank and row.

This is an elaboration-time choice, not a runtime switch. Data must be written
and read using the same mapping. Switching the physical interpretation of a
populated RAM would require relocating its data or tracking layout per buffer.
The maintenance port hides the physical map, so its logical commands are unchanged.

## Why the shift matters

For a row-major tile with a power-of-two pitch of `2**s` words, shift `s` spreads
four consecutive row positions in one column across all four banks. This is a
property of the physical row stride, including padding, not merely the tensor's
column count. A 16-bit word is two bytes: a 32-word pitch is a 64-byte stride.

The default shift 5 is tuned for a 32-word pitch. Shifts 3 and 4 target pitches
8 and 16. The engine does not automatically derive this parameter from a descriptor.

## Controlled comparison

Four parallel RTL instances use linear mapping and XOR shifts 3, 4, and 5.
They receive the same data, four logical requests, write schedule, clock, and
response-ready schedule. Only bank mapping differs. A flat-memory scoreboard
checks values independently of physical bank decoding.

Each benchmark batch contains one request per lane. With responses always ready,
the expected request-issue span is the largest number of requests targeting any
one bank. The batch completes one cycle later, after the final response is
accepted. These two measurements are deliberately reported separately.

| Four-word access pattern | Linear issue cycles | XOR 3 | XOR 4 | XOR 5 |
| --- | --- | --- | --- | --- |
| Aligned row of a 32x32 tile | 1 | 1 | 1 | 1 |
| Column, pitch 8 words | 4 | 1 | 2 | 4 |
| Column, pitch 16 words | 4 | 2 | 1 | 2 |
| Column, pitch 32 words | 4 | 4 | 2 | 1 |
| Diagonal, word indices 0/33/66/99 | 1 | 1 | 1 | 4 |
| Across words 2046/2047/2048/2049 | 1 | 2 | 2 | 2 |

For 32-word columns, shift 5 changes **request issue span 4 -> 1**, and
**complete-batch latency 5 -> 2**. That is fourfold request service for this batch
but a 2.5x improvement in isolated four-word batch completion latency. It is not
a fourfold speedup of the single-stream copy engine.

The diagonal counterexample reverses the tradeoff: shift 5 changes issue span
1 -> 4 and completion latency 2 -> 5. A row/column-friendly map is not a universal
best layout. Padded rows and misaligned groups also produce mixed results. The
generated report includes mean spans for pitches 12, 20, and 36 words.

## Correctness and instrumentation

The layout model tests every logical address and inverse for the linear map and
all legal default-capacity shifts 2-10. The RTL comparison directly exercises
shifts 3, 4, and 5 with 3,657 batches across full-memory readback, multiple tile
shapes, padded rows, stride probes, diagonals, boundaries, repeated addresses,
random requests, and 32 batches with response backpressure.

All 4,096 words are read before and after workload writes for every layout.
Initialization uses distinct 16-bit word values, and workload writes are applied
through public ports. The scoreboard checks 58,512 read responses overall.
Ready/valid snapshots and request/response conservation are checked. For all-ready
batches, exported conflict cycles and denied-request counts are checked against
the independent bank-occupancy oracle, in addition to issue/completion spans.

The full regression also runs the collision/reset/random-traffic memory bench
with linear and shift-5 maps. It runs the local copy suite with the pipeline and
shift-5 mapping, using the same Python destination images and public maintenance
loading/readback as the linear configuration. Earlier transfer/error/pipeline
suites remain in the regression.

The four-bank scheduler still has fixed lane priority. Swizzling reduces some
conflicts but does not add fairness or more than one read port per bank. Read
snapshot, same-edge write forwarding, and reset-preserves-RAM rules are unchanged.

## What remains unchanged

The copy pipeline uses one 16-bit read stream and one write stream. It does not
issue a four-lane column gather. Its ideal 32x32 copy remains 1,030 cycles under
either layout. End-to-end swizzle benefits need a parallel consumer or transfer
schedule that actually exercises the banked read lanes.

Memory capacity and M9K inference are unchanged. Synthesis of the default shift-5
scratchpad uses 585 logic elements versus 576 for linear mapping, with 144
registers and 65,536 RAM payload bits in either case. These are pre-fit estimates;
timing closure and physical-board behavior have not been measured.

## Reproduce

```powershell
python scripts/run_tests.py
quartus_sh -t quartus/synth.tcl tma_scratchpad
quartus_sh -t quartus/synth.tcl tma_scratchpad_swizzled
quartus_sh -t quartus/synth.tcl tma_local_copy_pipelined
quartus_sh -t quartus/synth.tcl tma_local_copy_swizzled
```

`--swizzle-only` runs the layout comparison for focused debugging and writes
`swizzle_only_results.json`; it does not claim a full regression pass. The full
run exports `swizzle_manifest.json`, `swizzle_metrics.csv/json`, and
`swizzle_comparison.md` inside `build/sim/`. Synthesis targets ending in
`swizzled` select shift 5; shifts 3 and 4 are RTL-simulated in the comparison.
