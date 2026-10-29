# Architecture and address-generator specification

## Engineering question

How much can a small FPGA improve useful tensor-processing throughput by
changing data movement and local storage, while holding the compute workload
and external memory interface constant?

The implemented project is the memory subsystem. A future compute consumer
would expose memory reuse and load/compute overlap; it is not part of the current
hardware result.

## Implemented scope and extension plan

- SystemVerilog RTL with explicit ready/valid interfaces.
- A single 50 MHz core domain; a related PLL output clocks external SDRAM.
- 2D descriptors, unsigned byte addresses and unsigned byte strides.
- Naturally aligned 16-bit elements in the implemented data path.
- Row-major descriptor traversal; destination strides can express a transpose.
- A serialized copy baseline and a separate pipelined engine. Automatic
  ping-pong tile ownership is an extension.
- An implemented 8 KiB scratchpad with four 1024x16 banks. The address space
  contains two possible 4 KiB tile buffers, each using 512 rows per bank.
  Quartus infers M9K RAM. Automatic buffer ownership remains planned work.
- Selectable linear/XOR bank mapping, with shift 3/4/5 RTL comparisons. The bank
  choice is static at elaboration time and must agree for writes and reads.
- Optional extension: a small signed 16-bit matrix workload, with accumulator
  width and reduction bounds specified before implementation.
- Implemented SDRAM source with selectable single-word or four-word read prefetch;
  tensor loads target the banked scratchpad. Three variants pass repeated board
  tests and a controlled 32x32 latency comparison.

Arbitrary gather/scatter lists, virtual addresses, cache coherence, PCIe, and a
full neural-network runtime are outside version 1.

## Data path

1. A controller validates a descriptor and starts a transfer.
2. The address generator produces source/destination address pairs.
3. A scheduler groups compatible accesses and accounts for outstanding memory
   operations. The source adapter can fetch four-word aligned lines and reuse
   buffered words behind the existing ordered request interface.
4. A memory adapter connects the scheduler to local RAM or the SDRAM controller.
   Its contract defines read latency, ordering, and errors.
5. A banked scratchpad provides a logical address space independent of physical
   bank layout. Initial mapping uses low word-address bits for bank selection.
6. Planned extension: ping-pong ownership would allow a consumer to read one
   buffer while the loader fills the other, publishing ownership only after
   completed writes.
7. Counters measure payload bytes, elapsed cycles, and relevant stall causes.

Transpose can create bank conflicts with low-bit banking. The implemented XOR
mapping and [layout study](swizzle.md) quantify a 32-word column improvement and
diagonal/boundary regressions. Mapping is workload-specific. The generator's
ability to express a transpose does not itself guarantee conflict-free access
or efficient SDRAM bursts.

The implemented scratchpad and two-memory local integration are specified in
[scratchpad.md](scratchpad.md). A directed four-lane read test demonstrates
single-cycle service for adjacent row words and four-cycle service for four
column words with stride 32. The full copy engine currently uses one lane and
can select either the preserved serialized baseline or the pipelined engine.
The pipeline overlaps a read stream with a write stream using a four-entry FIFO;
it does not change bank mapping or use four read lanes. See [pipeline.md](pipeline.md).

The local system separately selects `SWIZZLE=0/1`, keeping the transfer engine
fixed for a layout comparison. This adds no read lanes to the copy engine; its
ideal cycle count is unchanged. The parallel bank-layout results and the pipeline
copy results describe different workloads, with no combined speedup measured.

The external-source variant uses a 64 MiB SDRAM endpoint and an 8 KiB banked
destination. It retains engine/layout selection and the maintenance port. The
first controller issues ACTIVATE, one READ/WRITE, and explicit PRECHARGE for each
word, with periodic refresh independent of held responses. See [sdram.md](sdram.md)
for geometry, timing, board constraints, and the autonomous test. BL4 read
prefetch is implemented; write bursts and a compute consumer are extensions.

## Implemented module: `tma_addr_gen`

Defaults: `ADDR_W=32`, `COUNT_W=16`. Both parameters must be positive.
All ports are sampled on the rising edge of `clk`. `rst` is synchronous and
active high. There are no inferred clocks or asynchronous crossings.

### Descriptor input

| Port | Width | Meaning |
| --- | --- | --- |
| `desc_valid` / `desc_ready` | 1 each | Accept a descriptor when both are high |
| `desc_src_base`, `desc_dst_base` | ADDR_W | First element's byte addresses |
| `desc_rows`, `desc_cols` | COUNT_W | Number of rows and columns |
| `desc_src_row_stride`, `desc_src_col_stride` | ADDR_W | Source byte increments |
| `desc_dst_row_stride`, `desc_dst_col_stride` | ADDR_W | Destination byte increments |

For `r=0..rows-1` and then `c=0..cols-1`, the output is:

```text
src(r,c) = src_base + r * src_row_stride + c * src_col_stride
dst(r,c) = dst_base + r * dst_row_stride + c * dst_col_stride
```

Arithmetic wraps modulo `2**ADDR_W`. This is the primitive's explicit hardware
contract, not permission to wrap physical memory accesses. The later command
validator must reject out-of-range and misaligned transfers before issuance.
Zero strides and overlapping addresses are supported by the generator. Copy
ordering and overlap safety remain the transfer controller's responsibility.

### Address output and status

| Port | Meaning |
| --- | --- |
| `addr_valid`, `addr_ready` | Transfer an address pair when both are high |
| `src_addr`, `dst_addr` | Current pair; meaningful only when `addr_valid=1` |
| `addr_last` | Marks the final pair; meaningful only when `addr_valid=1` |
| `busy` | A nonempty descriptor is active; equals `addr_valid` |
| `done` | One-cycle pulse after final address acceptance, or an empty descriptor |
| `error` | One-cycle pulse alongside `done` for a zero row or column count |

- Only one descriptor is active. `desc_ready = !busy`.
- Descriptor values are latched on acceptance; later input changes have no effect.
- A nonempty descriptor makes the first pair valid immediately after its
  acceptance edge. A consumer can accept it at the following rising edge.
- Sustained throughput is one pair per clock while `addr_ready=1`.
- While stalled, `addr_valid`, the address pair, and `addr_last` remain stable.
- An empty descriptor produces no address pairs and pulses `done` and `error`.
- Reset cancels an active descriptor, clears pulses and state, and emits no
  completion. No handshakes are honored on a reset edge.
- The final pair and the next descriptor cannot be accepted on the same edge.
  A new descriptor can be accepted on the next edge. With no stalls, a nonempty
  R-by-C descriptor completes R*C clocks after its acceptance edge.
- `done` here means all **addresses** have been accepted. System-level completion
  must additionally wait for all reads, writes, and responses to complete.

### Transpose example

Move a 2x3 row-major 16-bit tile into a 3x2 row-major destination:

```text
rows = 2, cols = 3
src_base = 0x1000, src_row_stride = 6, src_col_stride = 2
dst_base = 0x2000, dst_row_stride = 2, dst_col_stride = 4

source:      1000 1002 1004 1006 1008 100A
destination: 2000 2004 2008 2002 2006 200A
```

This specifies the address traversal. The serialized copy engine now uses these
pairs to move and transpose real 16-bit values in simulation. Banked tile storage
and burst read prefetch are implemented. Write bursts and open rows remain
planned. The copy engine also
adds bounds/alignment restrictions beyond this standalone generator's contract;
see [the data-transfer specification](copy_engine.md).

## Decision record

| Decision | Reason | Evidence to revisit it |
| --- | --- | --- |
| Address generator before SDRAM | Isolate descriptor and handshake bugs | Verified local transfer path |
| 2D before higher dimensions | Covers tiles, row padding, and transpose | A concrete workload needing another dimension |
| 16-bit elements | Natural match for the x16 external interface | Packing/bandwidth study for 8-bit inputs |
| Adders and counters in address RTL | Avoid multipliers in the address loop | Synthesis mapping and timing reports |
| Single domain initially | Keeps first verification tractable | Measured need for an independent memory clock |
| Small compute consumer | Exposes memory reuse and overlap | Measured balance of compute and transfer cycles |

## Performance study

Use the same memory controller, clock, tensor values, and compute kernel for
baseline and optimized modes. Include contiguous copies, padded rows,
transposes, small and large tiles, and compute with and without overlap.

Report useful payload bytes / measured elapsed time and total workload latency.
Also publish bus traffic, resource utilization, achieved timing, and workload
dimensions. For a hypothetical 16-bit SDR interface running at 50 MHz, the raw
data-rate ceiling is 100 MB/s (decimal) before commands, refresh, or turnaround.
This is a calculation, not a board measurement or an achieved clock claim.

If a transfer reads and writes the same external bus, account for both bus
directions. Do not compare a payload-only metric against a traffic-inclusive
metric or claim CPU/GPU speedups from unrelated software timings.

## Board integration decisions and remaining evidence

The physical SDRAM chip is identified as IS42S16320F-7TL. The controller and SDRAM model are
project-authored; Altera supplies PLL/probe primitives. Clock, LED, and SDRAM
pins were checked against the Terasic manual, and the board build checks fitted
timing using the documented external-delay assumptions. Board revision remains
unknown; repeated physical results are recorded in [the hardware comparison](hardware_benchmark.md).
The deterministic onboard test sequencer
is implemented; evaluate JTAG-based control or a GPIO UART afterward. The
onboard USB-Blaster must not be assumed to provide a USB serial port.
