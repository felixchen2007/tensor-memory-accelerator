# Passive JTAG diagnostics

The board top instantiates Altera In-System Sources and Probes nodes `TMAD`
(instance 0) and `RTRC` (instance 1), both 256 bits. Their source outputs do not
control the memory engine. Readout uses the onboard USB-Blaster and the installed
Quartus tools; no extra GPIO connection is needed.

## TMAD packet

| Bits | Field |
| --- | --- |
| 255:240 | Signature `0x544d` |
| 239:232 | Format version: 2 legacy, 3 aligned BL1, 4 aligned BL4 |
| 231:224 | Flags: bit7 transfer completed successfully, bit6 SDRAM preflight passed, bit5 scratchpad preflight passed, bit4 PLL locked, bit3 reset, bit2 failed, bit1 passed, bit0 initialized |
| 223:220 | Sequencer state; 13 is terminal, 14 waits for refresh alignment |
| 219:216 | Failure reason |
| 215:204 | Checked tensor destination words |
| 203:192 | Checked SDRAM source words |
| 191:180 | Checked scratchpad preflight words |
| 179:148 | Failing word index in the selected test region |
| 147:132 / 131:116 | Expected / observed data |
| 115:84 | Completed transfer elements |
| 83:20 | Descriptor elapsed core cycles |
| 19:4 | Low refresh-counter bits; live and not an atomic performance sample |
| 3:0 | Version-dependent workload/mode metadata |

Format 2 reserves the low nibble as zero. Formats 3/4 set bit3 for refresh
alignment and bit1 for the 32×32 transpose; bit0 selects pipelined versus
serialized. Format 4 sets bit2 for BL4 reads; format 3 requires bit2 zero.
Legacy packets have no engine identity and cannot enter the controlled comparison.

| Reason | Meaning |
| --- | --- |
| 0 | No failure |
| 1 | SDRAM seed write response error |
| 2 | Tensor transfer status/count error |
| 3 | Destination read response error |
| 4 | Tensor data mismatch |
| 5 | SDRAM preflight read response error |
| 6 | SDRAM preflight data mismatch |
| 7 | Scratchpad seed write response error |
| 8 | Scratchpad preflight read response error |
| 9 | Scratchpad preflight data mismatch |

The fixed board tile's source byte address is `0x010007f0 + 2*word`;
scratchpad byte address is `2*word`. A PASS requires both preflights, a successful
transfer and 1,024 checked destination words. A preflight failure stops before
descriptor submission. The decoder checks stage flags, counts, failure reason
and three snapshots that agree apart from the live refresh field.

## RTRC read capture

| Bits | Field |
| --- | --- |
| 255:240 | Signature `0x5254` |
| 239:232 | Trace version 1 |
| 231:228 / 227:224 | Consumed sample index / sample count |
| 223:192 | Requested byte address |
| 191:0 | Twelve 16-bit input samples; sample zero occupies bits 15:0 |

Sample zero is the input capture from the edge before request acceptance. The
registered BL1 controller consumes sample 8; BL4 consumes sample `8 + word offset`.
BL4 traces rearm on a physical buffer miss, not a buffered hit. A zero count and
empty payload mean no read has occurred. Intermediate/inconsistent traces are
rejected. These are sampled digital input values, not analog pad measurements.

## Read or replay

```sh
python scripts/read_board_status.py --transcript evidence/hardware/2026-10-29/5_pipelined_burst4/probe.log
```

With a project image already running, `python scripts/read_board_status.py
--hardware` reads and records three samples without programming. Protocol
decoding is in [the model](../model/board_status.py); transport is in
[the Tcl reader](../quartus/read_board_probe.tcl).

[Board debugging](board_runs.md) · [Reproduction](reproduce.md).
