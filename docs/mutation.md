# Testing the verification environment with RTL defects

A passing regression establishes that the tested design matches its checks.
Mutation testing asks a different question: do those checks fail when plausible
implementation mistakes are introduced? This campaign changes one RTL behavior
at a time and requires the intended checker to diagnose the resulting fault.

## Executed result · 2026-10-29 UTC

**21/21 selected RTL mutants were detected**: 20 by the native UVM scoreboard
or passive monitors, and one by the independent SDRAM refresh checker inside
the UVM simulation. No mutant survived, failed compilation or required a
simulator failure to count as detection in the accepted run.

Both unmodified controls passed 34 descriptors each with zero UVM warnings,
errors and fatals. Each checked 2,686 DMA reads, 2,686 DMA writes and 25,352
maintenance readbacks, including the added cache probes. Production RTL and
existing UVM sources retained their recorded hashes.

After the campaign, the standard UVM suite passed again: eight configurations,
368 descriptors and the expected data-corruption control. The
[fresh nominal result](../evidence/mutation/2026-10-29/nominal_matrix/results.json)
and adjacent logs are retained separately from the earlier release evidence.

The [complete result and exact edits](../evidence/mutation/2026-10-29/results.json)
and [per-fault reports](../evidence/mutation/2026-10-29) retain the first checker
diagnosis, source identities, compiler output and raw simulation logs.
The rejected [pilot shutdown failure](../evidence/mutation/2026-10-29/pilot_shutdown_failure.log)
is retained separately and contributes nothing to the detection count.

## Method and scope

[`scripts/run_mutation_tests.py`](../scripts/run_mutation_tests.py) uses native
UVM 1.2 with the existing agent, passive monitors and independent scoreboard.
The configuration is **pipelined engine, BL4 reads, linear scratchpad**, seed
`20261029`. Each nominal control runs the original 34 directed descriptors and
additional maintenance-port cache probes; generated descriptors are disabled.
The unchanged standard UVM suite separately covers all eight configurations.

The [catalog](../scripts/mutation_catalog.py) specifies each exact source edit,
the requirement it violates and the permitted first checker diagnosis. Every
anchor must occur exactly once. A separate source copy is compiled for each
case under `build/mutation/<timestamp>/`; production RTL is never overwritten.
Unmodified controls run before and after the mutants. Source hashes are checked
again before the campaign can pass. No FPGA is accessed or programmed.

| Defect family | Injected mistakes | Required diagnosis |
| --- | --- | --- |
| FIFO payload and ordering | Flip data/destination bit, skip an entry, reuse an entry, offer an empty FIFO | DMA write address/data or unexpected-write checker |
| Completion and bounds | Double-count acknowledgements, finish before draining, disable late bounds checks | Status/count, incomplete work, stalled-request stability or unexpected transaction checker |
| Stride arithmetic | Substitute row/column strides in each source/destination update | DMA read address or write address/data checker |
| Burst buffer | Return offset zero, omit bank/row from tag, retain stale data after a write, select the wrong miss beat | Maintenance data scoreboard |
| Protocol and refresh | Suppress invalid-write errors, drop held valid, change held data, block refresh behind a held response | Address-error scoreboard, response stability monitor or independent pin-model refresh deadline |

Cache-tag probes seed distinct values at the same column in different banks and
rows, then read them without intervening writes. This is necessary because the
existing per-descriptor source seeding invalidates the cache and could mask a
truncated tag. Further probes overwrite a cached word and read all four offsets.
They use public maintenance transactions; expected values come from the passive
scoreboard's record of acknowledged writes.

Only the **first designated checker failure** counts as detection. Compile,
elaboration, licensing and simulator errors, unrelated failures and external
timeouts do not count. A mutant that reaches the normal pass marker survives.
Python unit tests exercise these result-classification boundaries.

The campaign top stops at the next falling clock edge after a UVM error, retaining
the original error severity and report summary. The simulator uses
`-onfinish exit`: Questa Starter 2024.3 crashed with `-onfinish stop` when a
failure ended an active transfer. Those pilot results were rejected. Nominal
runs still finish through normal UVM phases; any simulator crash remains an
infrastructure failure.

## Reproduce

With the same Windows Questa/UVM installation used by the standard regression:

```powershell
# Validate all patch anchors without a simulator
python scripts/run_mutation_tests.py --list
# All mutants, with unmodified controls before and after
python scripts/run_mutation_tests.py
# Focused investigation, still with both nominal controls
python scripts/run_mutation_tests.py --mutant burst_tag_ignores_bank
```

Each timestamped directory contains results, original/mutated source hashes,
exact patch definitions, generated top, compiler reports and simulator logs.
`build/mutation/current_results.json` points to the latest completed campaign;
it is cleared at the start so a failed rerun cannot advertise an earlier pass.

## Interpretation limits

This is a manually selected fault set in one configuration, not exhaustive
mutation coverage, formal proof or a design bug rate. Closely related edits are
listed individually, and are not independent statistical samples. It does not
establish arbitrary reset, endpoint-error injection, every FIFO occupancy,
all parameter combinations or board timing correctness. The refresh failure
comes from the complementary pin model inside the UVM simulation.

The installed license executes UVM base classes with procedural stimulus and
scenario counters. This campaign does not execute SV constrained randomization
or covergroups. [UVM environment and license scope](uvm.md).
