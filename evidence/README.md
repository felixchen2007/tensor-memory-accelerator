# Published engineering evidence

These files are a portable selection from recorded local runs. No new hardware
measurement is implied by exporting them. Generated workspaces, FPGA binaries,
license files, vendor libraries and the Terasic reference image are excluded.

| Directory | Meaning |
| --- | --- |
| [hardware/2026-10-29](hardware/2026-10-29) | Six physical configurations, decoded/raw JTAG, programming reports and fitted build records |
| [uvm/2026-10-29](uvm/2026-10-29) | Eight native UVM profiles, corruption control, source hashes and license/compile-only records |
| [simulation/2026-10-29](simulation/2026-10-29) | Current focused directed-plus-UVM regression and burst metrics |
| [simulation/2026-10-27](simulation/2026-10-27) | Historical full/local-memory studies; not a new full-suite pass |

## Provenance

[manifest.json](manifest.json) records the local input path and original SHA-256,
plus the SHA-256 of every published export. Project/home/host paths are replaced
with placeholders and JSON is formatted consistently. Measurements, status
packets, source/SOF hashes, warnings and severity reports retain their meaning.
The raw on-board packet hex strings are unchanged. Exported-file hashes differ
when these presentation transformations alter bytes.

References to `build/` inside historical records identify original local
artifacts; they are provenance strings, not promised downloadable files. The
documentation links point to included evidence instead. SOF hashes identify the
tested images; build the RTL locally to produce a new image. A new fit can have
a different image hash even with matching source.

Fitted `board_results.json` records deliberately retain `board_tested=false`:
they describe a build at its creation time. Later physical `run.json` and probe
records establish the hardware result separately.

## Verification of this publication

```sh
python scripts/check_portfolio.py
```

The checker validates exported hashes, matches current hardware/UVM source bytes
to their recorded hashes, decodes every three-packet hardware sample, recomputes
the benchmark comparison, and checks nominal/negative UVM reports. It also checks
local Markdown file links. This is evidence validation, not fresh RTL simulation
or a fresh hardware run. Hosted CI runs it and the Python unit tests.
