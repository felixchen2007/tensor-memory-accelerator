# Tool dependencies and attribution

The tensor RTL, Python reference models, verification environment and SDRAM pin
model are project-authored. The design uses the following external tools and
device documentation; their licenses and trademarks remain with their owners.

- **Altera / Intel Quartus Prime Lite 24.1std** and **Questa Intel Starter
  2024.3** were used for implementation and simulation. `altpll` and the passive
  in-system probe primitives are linked from the installed vendor libraries.
- **Accellera UVM 1.2**, supplied with Questa, is compiled from the local
  installation and linked to its DPI library. Vendor/UVM library sources and
  binaries are not redistributed here. [UVM reference](https://www.accellera.org/downloads/standards/uvm).
- **Terasic DE10-Lite** documentation supplied board pin/device information.
  Its original prebuilt SDRAM test was used as a bring-up comparison only;
  its HDL/bitstream is not included. [Board resources](https://www.terasic.com.tw/cgi-bin/page/archive.pl?CategoryNo=218&Language=English&No=1021&PartNo=4).
- **ISSI IS42S16320F** documentation defines SDRAM commands, mode registers and
  timing. [Device datasheet](https://www.mouser.com/datasheet/2/198/42-45R-S_86400F-16320F-706495.pdf).
- Hosted model/evidence checks use the official GitHub
  [checkout](https://github.com/actions/checkout) and
  [setup-python](https://github.com/actions/setup-python) actions.

Selected tool-generated reports retain tool attribution. No tool installers,
license keys or device configuration binaries are included in the publication.
The project name is descriptive and does not imply NVIDIA TMA compatibility.
