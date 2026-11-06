# Sets a 50 MHz clock target for standalone address-generator synthesis.
# The board project has a separate constraints file for external SDRAM timing.

create_clock -name core_clk -period 20.000 [get_ports {clk}]
