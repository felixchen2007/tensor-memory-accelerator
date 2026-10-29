# Verification strategy

The additive [C++17/DPI-C oracle](cpp_reference.md) is cross-checked against the
preserved Python models and can run alongside or independently of the original
SV scoreboard. [Recorded performance](reference_performance.md) separates pure
prediction, DPI overhead and complete RTL runtime. Protocol SVA and broader
coverage-driven closure remain follow-up work.

## Address-generator milestone

The Python reference computes each address directly from the coordinate formula.
RTL uses incremental row bases and running column addresses. Those different
implementations help catch row-transition and stride-update mistakes.

`scripts/run_tests.py` runs model unit tests, writes deterministic descriptor and
expected-address vectors, compiles the RTL/testbench, and runs Questa. A missing
simulator is an error in a full run. `--model-only` explicitly limits the run to
Python and vector generation; it is not an RTL pass.

The scoreboard compares every accepted address and `last` flag. Separate checks
verify stable output during stalls, ready/busy behavior, completion/error pulse
semantics, descriptor isolation while busy, and reset cancellation. A watchdog
turns deadlock into a failure. Testbench random stalls use a fixed PRNG seed.

Directed cases include 1x1, one row, one column, padded rows, transpose, zero
counts, zero strides, address wrap, and the maximum default row/column count
on one axis at a time. Additional descriptors use a fixed random seed. The
runner records vector counts, tool paths, timestamp, and source hashes in
`build/sim/results.json` after a successful RTL run.

To regenerate a different deterministic sample:

```powershell
python scripts/run_tests.py --seed 57 --random-cases 500
```

## Data-transfer milestone

The full runner also executes `tb_tma_copy_engine`. Python supplies separate
source/destination memory images, the entire expected destination, and ordered
read and write traces. The bench checks every accepted request (including data
for writes), all 4,096 destination words per case, completion/error behavior,
completed-element counts, and all three performance counters.

Default coverage comprises 27 directed and 100 random copy descriptors. Directed
cases include padded rows, 2x3 and 32x32 transposes, source broadcasts, repeated
destination writes, empty shapes, alignment errors, initial and later bounds
errors, and first/middle/final read/write errors. The memory endpoints introduce
independent request stalls and response delays. Recovery is checked by executing
further cases after errors.

Separate reset scenarios interrupt all six active FSM stages; the endpoint
models flush outstanding operations on reset. Request stability is checked while
stalled. The test requires all six status codes to have been exercised, both
read/write wait counters to be nonzero over the run, and all reset scenarios to
complete. The runner cross-checks exported metrics against the vector manifest.

Use `--copy-random-cases` to change the copy suite's sample count. Per-case cycle
results live in `build/sim/copy_metrics.csv` and `copy_metrics.json`. Whole-memory
checking also verifies that padding and unrelated destination words are intact.

## Scratchpad and integrated RAM milestone

`tb_tma_scratchpad` checks storage against a flat memory oracle. Directed tests
exercise four parallel reads, stride-32 column conflicts with exact counter
expectations, word/buffer boundaries, same-edge read/write forwarding, later
writes while a response is held, and reset without clearing RAM. A sustained
stream checks 256 read acceptances in 64 request cycles. Deterministic random
traffic adds per-lane response stalls, writes, and conflicting reads.

`tb_tma_local_copy_system` loads source and destination memories through a
maintenance request/response interface, executes the descriptor, and reads the
entire destination back through that same public interface. No RAM arrays are
initialized or inspected hierarchically. The default suite contains 21 directed
non-injected-fault cases and 12 random non-fault cases, giving 135,168 destination
word comparisons. The original synthetic-fault suite is also retained.

Integration additionally checks maintenance response backpressure, invalid
accesses, descriptor priority, and an accepted write surviving a reset that
cancels its acknowledgement. Local timings are in `build/sim/local_metrics.csv`
and `local_metrics.json`. Both new benches require explicit pass markers; their
summaries are saved in `results.json`. Source hashes are captured before testing
and checked again before a pass is recorded.

## Synthesis check

`quartus/synth.tcl` performs analysis and synthesis for `10M50DAF484C7G` in
`build/quartus/`. Passing `tma_copy_engine` as its argument selects the complete
baseline engine and writes to `build/quartus/copy_engine/`. Check for errors and
inferred latches, and retain the resource report. It does not run fitting, board
timing closure, power analysis, or hardware programming. The engine's standalone
logical interface is wider than board IO; a future board wrapper connects these
signals internally and exposes only actual board ports.

The `tma_scratchpad` and `tma_local_copy_system` targets write reports to
`build/quartus/scratchpad/` and `build/quartus/local_copy/`. Inspect the RAM
summary for four/eight 1024x16 simple dual-port memories with Type M9K. This
confirms dedicated RAM inference; it is not a fitted physical block count.

## Pipelined engine and paired comparison

`tb_tma_pipeline_comparison` runs both engines together with identical source,
initial destination, descriptor, and fault position. Memory service costs are
assigned by transaction/channel index and seed, so corresponding requests see
the same acceptance gaps and response delays even when issued at different times.

The suite contains 134 paired cases: the 127 existing copy-oracle cases plus
four minimum-latency shape sweeps, an ideal 32x32 transpose, and two adverse
error/stall combinations. It checks both complete destination images for
1,097,728 word comparisons, ordered write addresses/data, all six status codes,
counter values, legal ordered prefetch, stable stalled requests, and completion
only after memory activity drains. Four reset scenarios cover offered reads,
pending responses, full FIFO backpressure, and outstanding writes.

Fault cases permit extra prefetched reads along the legal address prefix; they
require the same writes, completed count, error result, and final RAM contents
as the serialized oracle. A read error must preserve queued earlier writes;
a write error must prevent later writes and drain an offered stalled read.

The full runner also executes the 33-case local integration suite twice, with
`PIPELINED=0` and `PIPELINED=1`, checking 135,168 destination words per version
through the maintenance port. `pipeline_metrics.json` records paired results;
`local_pipeline_metrics.json` records integration timing for the optimized core.
`pipeline_comparison.md` is the generated summary. `--pipeline-only` records a
focused-suite result separately and does not establish a full-regression pass.

Synthesis targets `tma_copy_engine_pipelined` and `tma_local_copy_pipelined`
write to `build/quartus/pipeline/` and `build/quartus/local_copy_pipelined/`.
The latter selects the local-system top with `PIPELINED=1`. Compare integrated
variants to hold RAM and externally observed counters constant.

## Bank swizzling and comparison

Eight new Python tests cover the mapping inverse, all 4,096 addresses for the
linear map and enabled shifts 2-10, invalid configurations, tuned columns,
aligned rows, and diagonal regressions. This brought the suite to 23 model tests;
later decoder, report and benchmark tests bring the recorded Python total to 52.

`tb_tma_swizzle_comparison` instantiates four independent RTL memories with linear
mapping and XOR shifts 3/4/5. Every variant receives the same logical requests,
word-write schedule, and response-ready schedule. The 3,657 batches check 58,512
read responses against a flat memory oracle. Full 4,096-word readbacks before
and after workload writes check aliasing and decode consistency in every map.
Padded rows, diagonal/stride probes, repeated words, boundaries, and 32 stalled
response batches are included.

For all-ready batches the runner independently checks issue span, complete-batch
latency, conflict cycles, and denied requests against the bank-occupancy oracle.
It exports named measurements and a comparison table. The existing random memory
bench additionally runs with shift 5, checking forwarding, snapshots, reset
persistence, and response backpressure. Its random request sequence can depend
on handshake timing; those unit-run totals are correctness evidence, not a paired
performance comparison. The fixed-vector four-layout bench supplies that comparison.

The local subset runs three configurations: serialized/linear,
pipelined/linear, and pipelined/shift-5. Each checks 33 descriptors and 135,168
destination words through the same maintenance port. The optimized copy's
1,030-cycle ideal 32x32 result is unchanged by bank mapping. There are nine total
simulation runs in that earlier local/address/pipeline/layout subset. `--swizzle-only` writes a focused result
separately and does not establish a full-regression pass.

Synthesis targets `tma_scratchpad_swizzled` and `tma_local_copy_swizzled` select
shift 5 and write reports to `build/quartus/scratchpad_swizzled/` and
`build/quartus/local_copy_swizzled/`. Shifts 3/4 are RTL-simulated in the comparison;
only shift 5 is included in the current area comparison.

## UVM acceptance environment

RTL acceptance uses the native UVM 1.2 environment
in [tb/uvm](../tb/uvm/tma_uvm_pkg.sv) is now part of both standard RTL entry points.
It uses a sequencer/driver, separate passive host and DMA monitors, an independent
data/address/commit scoreboard and a scenario subscriber. See [the UVM guide](uvm.md)
for the matrix, license boundary and replay commands. Existing directed benches
and pin checks remain complementary; older runs are not relabeled as UVM.

Starter mode exercises UVM with seeded procedural stimulus. Its scenario counters
are reported separately from the optional licensed SV covergroups and constraint
solver. The latter branch has been compiled but cannot be executed with the
currently available `svverification` license. Physical board tests remain RTL
self-tests and JTAG readback.

On 2026-10-29 UTC, all eight UVM profiles passed with zero UVM warnings, errors
and fatals: 368 descriptors, 23,496 checked DMA reads, 23,496 checked DMA writes
and 206,376 checked maintenance readbacks. A separate injected-data-corruption
run produced the required scoreboard error. These nine runs are included in the
current focused SDRAM acceptance result; see [executed results](uvm.md#executed-acceptance-result).

## SDRAM and fitted-board milestone

On 2026-10-29 UTC, all **52 Python tests and 35 focused simulation invocations**
passed. The focused suite combines 17 nominal directed runs, nine directed fault
controls, eight nominal UVM profiles and one UVM corruption control. The full
runner is configured for 44 invocations; its earlier full-run record is historical.
The 26 directed runs cover four BL1 controller configurations, two BL4
configurations, five deliberate fatal mode/protocol/timing controls, eight
engine/layout/memory-mode combinations, three nominal board profiles and four
injected board-data failures. Board simulation links Altera's PLL/probe models.
The Python tests include eight build-report
checks, which reject negative timing, missing reports, unconstrained paths, user
SDC warnings, broken clock constraints, and unassigned/aliased user pins. Dedicated
configuration/JTAG pins are correctly excluded from the user-port count.
Fourteen decoder tests cover malformed/old packets, incomplete PASS, inconsistent
snapshots, read traces and engine/burst identity. Seven benchmark tests reject
wrong images, changed sources/clocks, missing repetitions, incomplete checks,
and unstable counters. RTL-produced probe frames are decoded by the runner.
Three read-trace tests check sample ordering, malformed metadata, and the empty
trace before any SDRAM access. An injected read fault also checks that the trace
sample selected by the FSM matches its reported incorrect value.
The board sequence checks scratchpad and SDRAM separately before issuing the
tensor descriptor. Three injected corruptions distinguish scratchpad preflight,
SDRAM preflight, and final tensor readback, with expected stage/count evidence.

The SDRAM model observes pins and reconstructs physical bank/row/column storage;
it cannot inspect controller state. BL1 controller runs check 713 read responses
and 688 writes each; BL4 runs check 721 responses and 697 writes, adding offset
selection, four requests reusing one burst, write invalidation, and replacement.
Both cover invalid requests, concurrent offers, walking bits, all 25 word-address
bits, row boundaries, and long response stalls during refresh. The tensor subset
checks 49,152 destination words in each of eight configurations: 393,216 total
across 96 descriptors. Descriptors start at an equal refresh phase. Command and
data-beat counts expose overfetch on sparse accesses. This covers BL1 and BL4
read prefetch; analog behavior, all locations, and arbitrary warm reset remain outside the model.
See [the detailed contract](sdram.md).
Pin-level checks require 1.5 ns setup and 0.8 ns hold on sampled command/write
signals. They are digital protocol checks; physical FPGA/PCB delays are not
included. The delayed-clock testbench schedules every edge and preserves clocks
whose phase shift exceeds a half-period.

`scripts/build_board.py` separately performs the full Quartus flow and checks
all reported corner slacks, constraint coverage, and all 50 fitted user pins.
The evidence includes source and SOF hashes and retains reviewed vendor warnings.
Only the two known empty dynamic-phase PLL filter/exception pairs from Quartus's
internal script are reviewed automatically; unmatched user constraints fail.
The board timing result depends on the external-delay assumptions in the SDC.
Physical execution is a separate completion gate and is recorded as false in
the fitted-build result, which describes that image at build time. Later physical
attempts are separate records. Each of three images passed twice on hardware:
16,525 cycles serialized, 13,541 pipelined, and 5,735 pipelined with BL4 prefetch.
All six verified both 1,024-word preflights and the 1,024-word transpose. Earlier
failures and the working clock-forwarding change are in [board_runs.md](board_runs.md).
This is a tile smoke test, not a full-memory, retention, temperature, or jitter
qualification. The direct PLL output's non-dedicated-routing warning is retained.

## Remaining coverage

The [native UVM mutation campaign](mutation.md) exercises selected FIFO,
addressing, completion, cache, protocol and refresh defects against the current
checkers. That fault set measures checker sensitivity in one configuration; it
does not close the remaining coverage items below.

- Parameter-width sweeps beyond the default 32-bit address / 16-bit count build.
- Formal safety/liveness properties and formal assumptions on the interfaces.
- Coverage-driven closure; randomized simulation is not proof of correctness.
- Multiple pending reads/writes per channel, response reordering, and write bursts.
- Nondefault FIFO-depth sweeps and formal proof of pipeline error-drain invariants.
- Formal proof that the conservative address checks prevent all illegal accesses.
- Shared physical source/destination aliasing and arbitrary in-place overlaps.
- Other RTL swizzle shifts/capacities, fairness guarantees, and automatic buffer ownership.
- Post-synthesis RAM simulation and board confirmation of inferred-memory behavior.
- Wider physical SDRAM readback/retention, board revision, and validation of PCB timing assumptions.
- Longer SDRAM bursts, open rows, tensor writeback, arbitrary warm reset, and a vendor/electrical memory model.

When the system grows, preserve this unit regression and add data-level
scoreboards and assertions at each new interface. Test failures should be
reproduced with a recorded seed before changing the architecture.
