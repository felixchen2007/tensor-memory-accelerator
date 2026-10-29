# Initial 50 MHz SDR-SDRAM board constraints. PCB delays below are assumptions,
# not measured trace delays; a pass is conditional on this external timing budget.
create_clock -name ref_clk -period 20.000 [get_ports MAX10_CLK1_50]
derive_pll_clocks
# Forwarded clock at the board pin, including the PLL and output path. Its edge
# is 5.0 ns after the reference/core edge in the functional clock model.
create_generated_clock -name sdram_clk \
    -source [get_pins {clocks|pll|auto_generated|pll1|clk[1]}] \
    -divide_by 1 [get_ports DRAM_CLK]
derive_clock_uncertainty

# IS42S16320F -7: tAC=5.4ns max, tOH=2.5ns min (CL3).
# Allow 0.5ns max / 0.1ns min for EACH external clock/data PCB path.
set_input_delay -clock sdram_clk -max 6.400 [get_ports {DRAM_DQ[*]}]
set_input_delay -clock sdram_clk -min 2.700 [get_ports {DRAM_DQ[*]}]
# SDRAM setup 1.5ns, hold 0.8ns; add relative PCB skew and margin.
set sdram_outputs [get_ports {DRAM_ADDR[*] DRAM_BA[*] DRAM_DQ[*] DRAM_CAS_N DRAM_RAS_N DRAM_WE_N DRAM_CS_N DRAM_CKE DRAM_LDQM DRAM_UDQM}]
set_output_delay -clock sdram_clk -max 2.000 $sdram_outputs
set_output_delay -clock sdram_clk -min -1.300 $sdram_outputs
# Human-visible status outputs have no external synchronous receiver.
set_false_path -to [get_ports {LEDR[*]}]

# In-System Sources and Probes adds only the dedicated JTAG pins. Altera's
# sld_hub creates a 10 MHz TCK clock and declares it asynchronous to the core.
# Model TDI/TMS changing after falling TCK, with a conservative 20 ns I/O budget;
# TDO is sampled at the following rising TCK. These assumptions concern debug
# access only and do not exclude or relax any SDRAM path.
set debug_inputs [get_ports -nowarn {altera_reserved_tdi altera_reserved_tms}]
if {[get_collection_size $debug_inputs] > 0} {
    set_input_delay -clock altera_reserved_tck -clock_fall -max 20.000 $debug_inputs
    set_input_delay -clock altera_reserved_tck -clock_fall -min 0.000 $debug_inputs
    set_output_delay -clock altera_reserved_tck -max 20.000 [get_ports altera_reserved_tdo]
    set_output_delay -clock altera_reserved_tck -min 0.000 [get_ports altera_reserved_tdo]
}
