# Controlled hardware engine comparison

The benchmark compares a 32x32 sixteen-bit SDRAM-to-scratchpad transpose using
the preserved serialized engine and the pipelined engine. The useful tile is
2,048 bytes. Initialization, source seeding, both 1,024-word memory preflights,
and destination readback are outside the descriptor counter.

## 2026-10-29 UTC: measured on the board

The completed comparison includes four-word read prefetch. Each of the three
images passed two fresh configurations, with matching counters and verified
data. All use the same source revision and constraints.

| Variant | Cycles | Tile latency at nominal 50 MHz | Useful tile payload rate | Fitted LEs / registers |
| --- | --- | --- | --- | --- |
| Serialized, BL1 | 16,525 | 330.50 us | 6.197 MB/s | 2,477 / 1,652 |
| Pipelined, BL1 | 13,541 | 270.82 us | 7.562 MB/s | 2,703 / 1,863 |
| Pipelined, BL4 prefetch | 5,735 | 114.70 us | 17.855 MB/s | 2,856 / 1,953 |

BL4 prefetch measures **2.88143x** over serialized BL1 and **2.36112x** over
pipelined BL1. It adds 153 LEs and 90 registers over pipelined BL1. All three
use 65,536 RAM bits and one PLL. BL4 setup/hold slacks are +1.584/+0.147 ns.
The final recorded configuration used the burst image.

The [six-run record](../evidence/hardware/2026-10-29/results.json)
contains image hashes and measurements. Adjacent numbered folders include build
records and programming/probe logs; source hashes bind the current RTL. Original
binary/source archives remain local. This is a 2 KiB tile result. Physical command counts
come from simulation; the board reports verified data and descriptor cycles.
Scattered-access penalties are recorded in [the burst study](bursts.md).

The BL1 pipelining comparison measures **1.22037x**, or **18.057% lower descriptor
latency**. Both fits use 65,536 RAM bits and one PLL. Worst setup/hold slacks
were +1.578/+0.148 ns serialized and +1.584/+0.148 ns pipelined.
The earlier 13,545-cycle smoke test used a different refresh start phase; its
four-cycle difference is not an optimization gain.

The earlier four-run checkpoint and original binary/source archives remain
local; the published evidence is the final six-run comparison. Payload rates are derived from the tile
counter, not measurements of sustained streaming bandwidth.

Both images use identical controller, clock, pin, data-pattern, layout, and
timing-constraint sources. For BL1, `PIPELINED` is the only build selection.
The third image selects `READ_BURST_WORDS=4`. Each descriptor is submitted two core edges after a runtime refresh
launch; the board testbench checks that refresh age is one before that edge's
timer increment. This prevents a different initial refresh phase from favoring
one implementation. Refresh continues throughout the transfer.

The format-3 status packet identifies the engine and workload. It retains all
format-2 fields, changes the version byte to 3, and assigns the low nibble:
bit 3 enables refresh alignment, bit 2 is reserved zero, bit 1 identifies the
32x32 transpose, and bit 0 selects pipelined (1) or serialized (0). Format 4 sets
bit 2 and identifies four-word reads. The current
reader accepts old format-2 records without assigning them an engine identity;
those records cannot enter the controlled hardware comparison. State 14 means
waiting for the refresh boundary; terminal state remains 13.

## Reproduce

```powershell
python -m unittest discover -s tests -v
python scripts/run_sdram_tests.py
python scripts/build_board.py --engine serialized
python scripts/build_board.py --engine pipelined
python scripts/build_board.py --engine pipelined --read-burst 4
```

The fits go to `build/quartus/de10_lite_serialized` and
`build/quartus/de10_lite`; the third goes to `build/quartus/de10_lite_burst4`.
Each must pass setup/hold at all reported corners,
pin checks, and constraint coverage. These commands do not access the board.

With the board connected and hardware testing authorized:

```powershell
python scripts/benchmark_board.py --hardware
python scripts/benchmark_board.py --hardware --include-burst
```

The default command checks source/image hashes and the expected USB-Blaster/10M50
chain, then loads serialized, pipelined, serialized, and pipelined SOFs in that
order. It writes only volatile FPGA configuration and leaves the pipelined
image loaded. With `--include-burst`, the order is serialized, pipelined, burst,
repeated twice, leaving the burst image loaded. Each run must pass both preflights and all 1,024 transpose checks;
three consistent passive JTAG packets provide the result. A mismatch stops the
benchmark. Each engine must reproduce its counter with the same image twice.

The benchmark folder under `build/hardware/*_engine_benchmark/` contains raw
programming/probe logs, both image/build records, the simulation record, source
snapshots, four or six `run.json` records, and `results.json`. Saved records can be
reanalyzed without hardware:

```powershell
python scripts/benchmark_board.py --records path/to/0_serialized/run.json path/to/1_pipelined/run.json path/to/2_serialized/run.json path/to/3_pipelined/run.json
```

## Interpretation and limits

Cycle speedup is serialized cycles divided by pipelined cycles. Tile latency
uses the nominal 50 MHz clock. Tile payload rate counts 2,048 useful bytes once,
uses decimal MB/s, and includes the whole descriptor interval. It does not
represent sustained bandwidth across a stream of tiles, the raw SDRAM bus rate,
or twice the payload for the source and destination transactions.

This is a tile test in one region crossing a row boundary in bank 1. It does
not establish full-memory coverage, retention, temperature margins, or clock
jitter tolerance. Quartus warning 15064 for the direct PLL output's
non-dedicated routing remains visible. Fitted counts describe the whole
constant-descriptor test image, including diagnostics, rather than generic IP
core area. Initial board passes are retained in [the board record](board_runs.md).
