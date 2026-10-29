# Four-bank scratchpad and local copy integration

The scratchpad is synthesizable storage, implemented by `tma_ram_bank.sv` and
`tma_scratchpad.sv`. `tma_scratchpad_endpoint.sv` adapts it to the copy engine's
byte-addressed request/response channels. `tma_local_copy_system.sv` connects a
selectable serialized or pipelined engine to separate source/destination scratchpads.

## Capacity and mapping

Each default scratchpad stores **4,096 words x 16 bits = 8 KiB** in four logical
banks. Each bank is 1,024 words x 16 bits. There is one write port shared across
the banks and four independent logical read lanes.

The equations/table below describe the default `SWIZZLE=0` layout. Setting
`SWIZZLE=1` selects an XOR bank permutation, with `SWIZZLE_SHIFT=5` by default;
physical row and capacity remain unchanged. See the [layout study](swizzle.md)
for the inverse mapping, configuration constraints, and measured tradeoffs.

```text
logical word index = byte address / 2
bank               = word index % 4
row within bank    = word index / 4
```

| Word indices | Banks | Rows within banks |
| --- | --- | --- |
| 0, 1, 2, 3 | 0, 1, 2, 3 | 0, 0, 0, 0 |
| 4, 5, 6, 7 | 0, 1, 2, 3 | 1, 1, 1, 1 |
| 0, 32, 64, 96 | 0, 0, 0, 0 | 0, 8, 16, 24 |

Words 0-2,047 form a possible 4 KiB buffer A; words 2,048-4,095 form buffer B.
Each half contains 512 rows per bank. These are address regions only: ownership
and automatic ping-pong scheduling are not implemented yet.

The local integration instantiates **two** such scratchpads, for 16 KiB total.
This preserves the existing oracle's independent 8 KiB source/destination spaces.
The [SDRAM-source system](sdram.md) instead instantiates one destination
scratchpad and uses external memory as its source.

## Read lanes and bank arbitration

All ports use the core clock. `ROW_W=10` is the tested default; a logical word
address is `ROW_W+2` bits. The primitive has no byte-address/alignment interface;
every representable word index is in range.

Each lane has a request valid/ready pair and a response valid/ready pair.
Requests targeting different banks can be accepted on the same edge. When
requests compete for one bank, the lowest-numbered eligible lane wins. Losing
requests remain pending at their senders until accepted. Fixed priority does
not guarantee fairness under continuously competing traffic.

Each lane and each bank can hold at most one unconsumed response. A request
accepted at an edge makes data and response-valid available immediately after
that edge, for acceptance at the next rising edge. Response acceptance and a new
request can occur together, sustaining one read per bank per clock.

A bank keeps its read result until the owning lane accepts the response. Other
lanes cannot overwrite that result while it is stalled. A sender must hold its
request/payload until accepted. Request-ready can depend on request-valid.

### Write and collision semantics

The single word-addressed write port accepts one word on every rising edge with
`wr_en=1` and `rst=0`. It can operate concurrently with reads, including reads
from the same bank.

- A read and write of the **same word on the same edge returns the new value**.
  An explicit forwarding path implements this independently of the underlying
  RAM primitive's collision output.
- A later write does not change an already pending read response. The response
  is a snapshot from its acceptance edge, including any same-edge forwarding.
- Reset clears response ownership and counters, cancels unconsumed responses,
  and suppresses writes on reset edges. It **preserves stored data**.
- Initial RAM contents are unspecified by this interface. Initialize words
  before reading them. No reset loop clears the memory array.

The RAM attribute requests M9K storage and declares primitive collision output
irrelevant; the parent implements the observable collision rule. Quartus's RAM
summary confirms four simple dual-port M9K memories, each 1,024 x 16 bits.
This standalone comparison is synthesis evidence. The later
[board smoke-test top](sdram.md) has a fitted report and uses eight physical M9Ks
for its one scratchpad; physical-board memory behavior remains untested.

### Conflict counters

`bank_conflict_cycles` increments once per cycle when at least one otherwise
eligible read lane is denied access to its requested bank. A bank can be occupied
by a held response or allocated to another lane in that cycle.
`bank_conflict_requests` counts the number of such denied lane requests.
Requests blocked by their own unconsumed response are excluded. Both counters
are 32-bit modulo counters cleared by reset.

## Why transpose needs attention

Four adjacent row values at word indices 0, 1, 2, and 3 use four banks and take
one request-service cycle. Four values down a column of a 32-wide row-major tile
use indices 0, 32, 64, and 96. They all use bank 0 and take four service cycles.
The directed test observes three conflict cycles and six denied lane requests
(3 + 2 + 1).

The selectable shift-5 XOR map spreads those column words across four banks,
reducing issue span from four to one and batch completion from five to two
cycles. It can worsen other patterns: word indices 0/33/66/99 issue in one cycle
under linear mapping but four with shift 5. See [swizzle.md](swizzle.md).
Transpose staging and consumer access order remain other options to evaluate.

## Byte-addressed endpoint

The endpoint adapter uses lane 0 and ties the other three lanes off. It presents
the existing independent read/write ready/valid channels with 32-bit byte
addresses and 16-bit payloads.

- Even addresses from 0 to 8,190 are valid in the default instance.
- Invalid reads return a zero data word and an error response without reading RAM.
- Invalid writes return an error response without modifying RAM.
- Writes commit when accepted; their acknowledgement is available in the next
  cycle and remains valid until consumed. Reset can cancel that acknowledgement
  after the write has already committed.
- Read and write channels each have one response slot. They support response
  replacement on an acceptance edge and can operate concurrently.
- The adapter's current one-lane client does not use four-lane read bandwidth.

## Integrated local copy system

The maintenance port loads and inspects either source or destination memory
without hierarchical testbench access. Its request contains `write`, `dst`,
byte address, and write data; its response contains data/error and ready/valid.
Only one maintenance command is outstanding at once.

A descriptor has priority over a simultaneous maintenance offer. An outstanding
maintenance response prevents descriptor acceptance, and the copy engine's busy
state prevents maintenance acceptance. This avoids changing memory behind an
active copy. Responses must be consumed to make progress. The shared synchronous
reset flushes protocol state in the engine and both endpoints while retaining
memory contents.

The wrapper connects one read lane and one write stream to either transfer
engine. With `PIPELINED=0` (the default), a 32x32 copy or transpose takes 5,121
core cycles. With `PIPELINED=1`, it takes 1,030 cycles through the same RAMs.
The [pipeline specification](pipeline.md) describes that separate optimization.
The four-lane unit test measures memory parallelism independently; selectable
bank mapping is now implemented, while a parallel compute consumer remains
future work. Enabling shift 5 in the one-stream pipelined wrapper leaves its
ideal copy/transpose cycle count unchanged at 1,030.

## Verification and reproduction

The memory-unit bench uses a flat word array as its oracle; it does not duplicate
bank decomposition. It checks parallel reads, same-bank conflicts, buffer and
capacity boundaries, collision forwarding, response snapshots, random writes,
per-lane backpressure, continuous four-bank traffic, and reset persistence.

The integration bench selects 21 directed non-injected-fault descriptors and up
to 12 random non-fault descriptors from the existing Python copy oracle. It loads
both entire memories and checks every destination word through maintenance
transactions. Synthetic read/write error injection remains in the existing copy
bench, since the actual RAM adapter has no such fault-injection feature.

```powershell
python scripts/run_tests.py
quartus_sh -t quartus/synth.tcl tma_scratchpad
quartus_sh -t quartus/synth.tcl tma_local_copy_system
```

`--local-random-cases` changes the requested integration sample count, limited by
the available non-fault cases generated by `--copy-random-cases`. The runner
exports local per-case measurements and source hashes, and refuses to record a
successful result if source files change while verification is running.
