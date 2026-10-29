# SDRAM board debugging

## Observed failure

The first project image configured successfully on 2026-10-28 but reported a
failed self-test. Programming success only established FPGA configuration.
Passive diagnostics later isolated the failure to the first SDRAM preflight
read, after a successful 1,024-word scratchpad test and before tensor execution.

Expected: `0xa55a` at byte address `0x010007f0`. Observed: `0x86ed`, the value
written to the last source word. A twelve-sample read trace retained that stale
value throughout the capture window. This observation narrowed the investigation
to the external-memory path; it did not establish whether commands had been
accepted by the SDRAM or identify the analog cause.

## Experiments and result

| Experiment | Observation |
| --- | --- |
| Register command/address/DQM/output enable together | Same first-read failure |
| Move DQ capture from the IOE to a fabric register | Same failure |
| Change DDR-forwarded clock phase from +7.5 to +5.0 ns | Same failure |
| Run Terasic's original prebuilt memory test | User-observed PASS indication |
| Keep +5.0 ns and forward the PLL output directly | Project test PASS, repeated |

The manufacturer test was a diagnostic comparison using its original bitstream.
Its controller HDL and bitstream are not included here and are not project
implementation work. The final design retains the project-authored controller.

The working change replaced `altddio_out` forwarding with direct PLL output 1
forwarding while retaining the preceding +5.0 ns controller pipeline, pin and
timing settings. Two fresh configurations of that first working image each
verified both 1,024-word preflights and the entire transpose. They measured
13,545 cycles before later refresh-start alignment.

The controlled comparison then rebuilt all three variants from the same RTL
and constraints, aligned descriptor starts to refresh, and measured
16,525 / 13,541 / 5,735 cycles twice each. The four-cycle difference between
13,545 and 13,541 comes from the changed refresh start phase; it is not credited
as an architectural optimization.

## Evidence in this repository

The publication includes the final six-run comparison and its raw digital JTAG
packets, programming reports, decoded status, source/image hashes and fitted
records. Earlier exploratory images and complete working-directory archives
remain local; the table above is a diagnostic narrative rather than a claim
that all those intermediate artifacts are published.

- [Six-run result](../evidence/hardware/2026-10-29/results.json)
- [Repeated burst run](../evidence/hardware/2026-10-29/5_pipelined_burst4/run.json)
- [Raw JTAG report](../evidence/hardware/2026-10-29/5_pipelined_burst4/probe.log)
- [Decoded packets and twelve-sample trace](../evidence/hardware/2026-10-29/5_pipelined_burst4/probe.json)
- [Fitted record and retained warnings](../evidence/hardware/2026-10-29/2_pipelined_burst4/board_results.json)

## Remaining clock limitation

Quartus warning **15064** identifies non-dedicated routing from PLL output 1 to
the SDRAM clock pin and potential jitter from other switching activity. That
warning remains in the recorded fit. Reported timing passes under the external
delay assumptions in `quartus/de10_lite.sdc`, and the tested tile passes on the
board. Neither result establishes jitter tolerance, temperature/voltage margins
or an electrical root cause for the earlier DDR-forwarded failure.

Next validation should investigate legal clock-forwarding/routing options,
phase margin and sustained switching stress, followed by broader address/bank,
stride and retention tests. Oscilloscope measurements would be required for
claims about the actual off-chip clock waveform.

## Diagnostics and replay

`TMAD` exposes versioned status and counters; `RTRC` exposes twelve captured
16-bit DQ samples for the last physical read miss. They are passive probes over
the onboard USB-Blaster. The low refresh-counter bits continue changing, so the
decoder requires three snapshots with all other result fields stable.

```sh
python scripts/read_board_status.py --transcript evidence/hardware/2026-10-29/5_pipelined_burst4/probe.log
```

The decoder rejects malformed frames, incomplete PASS states and inconsistent
snapshots. The pin-level board simulation checks injected preflight and tensor
readback faults. [Controller/clock contract](sdram.md) ·
[Benchmark methodology](hardware_benchmark.md) · [Hardware demo](demo.md).
