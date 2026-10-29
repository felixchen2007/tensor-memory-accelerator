# Initial core target only. Board IO and generated clocks are a later milestone.
create_clock -name core_clk -period 20.000 [get_ports {clk}]
