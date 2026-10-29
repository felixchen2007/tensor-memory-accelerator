`default_nettype none
// Vendor PLL primitive; project-authored wrapper. 50 MHz core and a phase-shifted
// 50 MHz SDRAM clock. Reset release waits for lock in tma_de10_lite.
module tma_board_clocks (
    input wire ref_clk,
    output wire core_clk,sdram_clk,locked
);
    wire [4:0] clocks;
    altpll #(
        .intended_device_family("MAX 10"),.operation_mode("NORMAL"),
        .compensate_clock("CLK0"),.inclk0_input_frequency(20000),
        .clk0_multiply_by(1),.clk0_divide_by(1),.clk0_phase_shift("0"),
        .clk1_multiply_by(1),.clk1_divide_by(1),.clk1_phase_shift("5000"),
        .width_clock(5),.port_clk0("PORT_USED"),.port_clk1("PORT_USED"),
        .port_locked("PORT_USED"),.port_inclk0("PORT_USED"),.port_areset("PORT_USED"),
        .port_fbin("PORT_UNUSED"),.port_clkswitch("PORT_UNUSED"),
        .port_scanclk("PORT_UNUSED"),.port_scanaclr("PORT_UNUSED"),
        .port_scanclkena("PORT_UNUSED"),.port_scanread("PORT_UNUSED"),
        .port_scanwrite("PORT_UNUSED"),.port_scandata("PORT_UNUSED"),
        .port_configupdate("PORT_UNUSED"),.port_phasecounterselect("PORT_UNUSED"),
        .port_phasestep("PORT_UNUSED"),.port_phaseupdown("PORT_UNUSED"),.port_phasedone("PORT_UNUSED")
    ) pll (
        .inclk({1'b0,ref_clk}),.areset(1'b0),.clk(clocks),.locked(locked),
        .clkena(6'b111111),.extclkena(4'b1111),.pfdena(1'b1),.pllena(1'b1),
        .fbin(1'b1),.clkswitch(1'b0),.scanclk(1'b0),.scanaclr(1'b0),
        .scanclkena(1'b1),.scanread(1'b0),.scanwrite(1'b0),.scandata(1'b0),
        .phasecounterselect(4'b0),.phaseupdown(1'b1),.phasestep(1'b0),.configupdate(1'b0),
        .fbmimicbidir(),.extclk(),.clkbad(),.enable0(),.enable1(),.activeclock(),
        .clkloss(),.scandataout(),.scandone(),.sclkout0(),.sclkout1(),.phasedone(),
        .vcooverrange(),.vcounderrange(),.fbout(),.fref(),.icdrclk()
    );
    assign core_clk=clocks[0];
    // Diagnostic: direct PLL forwarding, matching the topology in Terasic's
    // working reference. Fitted timing must include this actual output path.
    assign sdram_clk=clocks[1];
endmodule
`default_nettype wire
