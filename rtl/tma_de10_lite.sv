`default_nettype none

module tma_de10_lite #(
    parameter bit PIPELINED=1,
    parameter int unsigned READ_BURST_WORDS=1
) (
    input wire MAX10_CLK1_50,
    output wire [9:0] LEDR,
    output wire [12:0] DRAM_ADDR,
    output wire [1:0] DRAM_BA,
    output wire DRAM_CAS_N,DRAM_CKE,DRAM_CLK,DRAM_CS_N,
    output wire DRAM_LDQM,DRAM_UDQM,DRAM_RAS_N,DRAM_WE_N,
    inout wire [15:0] DRAM_DQ
);
    // Power-on-only reset. Rerun by volatile reconfiguration or power cycle.
    // MAX 10 supports register power-up values; there is no asynchronous button
    // reset that could interrupt an SDRAM transaction in this first board test.
    wire core_clk,pll_locked;
    tma_board_clocks clocks (.ref_clk(MAX10_CLK1_50),.core_clk(core_clk),.sdram_clk(DRAM_CLK),.locked(pll_locked));
    (* altera_attribute = "-name SYNCHRONIZER_IDENTIFICATION FORCED_IF_ASYNCHRONOUS" *)
    logic [1:0] lock_sync_q=0;
    always_ff @(posedge core_clk) lock_sync_q<={lock_sync_q[0],pll_locked};
    logic [7:0] startup_q=0;
    wire rst=!(&startup_q);
    always_ff @(posedge core_clk)
        if(!lock_sync_q[1]) startup_q<=0;
        else if(rst) startup_q<=startup_q+1'b1;
    wire [15:0] dq_out;
    wire dq_oe,init_done,passed,failed;
    wire [11:0] checked_words,source_checked_words,scratch_checked_words;
    wire [2:0] passed_stages;
    wire [3:0] stage_code;
    wire [31:0] refresh_count;
    wire [31:0] failure_word,completed_elements;
    wire [15:0] expected_data,observed_data;
    wire [3:0] failure_reason;
    wire [63:0] elapsed_cycles;
    wire [255:0] read_trace;
    // Format 3 identifies the fitted engine and the refresh-aligned workload.
    wire [255:0] debug_value={16'h544d,(READ_BURST_WORDS==4 ? 8'h04 : 8'h03),
        passed_stages,pll_locked,rst,failed,passed,init_done,stage_code,failure_reason,
        checked_words,source_checked_words,scratch_checked_words,failure_word,expected_data,observed_data,
        completed_elements,elapsed_cycles,refresh_count[15:0],1'b1,(READ_BURST_WORDS==4),1'b1,PIPELINED};
    // Passive observation only; the source output cannot control this design.
    altsource_probe #(.probe_width(256),.source_width(1),.instance_id("TMAD"),
        .sld_auto_instance_index("NO"),.sld_instance_index(0),.enable_metastability("NO"))
        diagnostic_probe (.probe(debug_value),.source(),.source_clk(core_clk),
        .source_ena(1'b0),.clr(1'b0)
        // Unused virtual-JTAG ports are tied only in simulation. Quartus
        // connects the synthesized debug node to its on-chip JTAG hub.
        // synthesis translate_off
        ,.jtag_state_sdr(1'b0),.ir_in(4'b0),.jtag_state_cir(1'b0),
        .jtag_state_udr(1'b0),.jtag_state_e1dr(1'b0),.ir_out(),
        .jtag_state_cdr(1'b0),.jtag_state_tlr(1'b0),.tdi(1'b0),
        .jtag_state_uir(1'b0),.tdo(),.raw_tck(1'b0),.usr1(1'b0),.ena(1'b0)
        // synthesis translate_on
    );
    altsource_probe #(.probe_width(256),.source_width(1),.instance_id("RTRC"),
        .sld_auto_instance_index("NO"),.sld_instance_index(1),.enable_metastability("NO"))
        read_trace_probe (.probe(read_trace),.source(),.source_clk(core_clk),
        .source_ena(1'b0),.clr(1'b0)
        // synthesis translate_off
        ,.jtag_state_sdr(1'b0),.ir_in(4'b0),.jtag_state_cir(1'b0),
        .jtag_state_udr(1'b0),.jtag_state_e1dr(1'b0),.ir_out(),
        .jtag_state_cdr(1'b0),.jtag_state_tlr(1'b0),.tdi(1'b0),
        .jtag_state_uir(1'b0),.tdo(),.raw_tck(1'b0),.usr1(1'b0),.ena(1'b0)
        // synthesis translate_on
    );
    logic [25:0] heartbeat_q=0;
    always_ff @(posedge core_clk) heartbeat_q<=heartbeat_q+1'b1;
    assign DRAM_DQ=dq_oe ? dq_out : 16'hzzzz;
    assign LEDR={checked_words[9:5],heartbeat_q[25],!passed && !failed,failed,passed,init_done};
    tma_sdram_selftest #(.PIPELINED(PIPELINED),.READ_BURST_WORDS(READ_BURST_WORDS)) test (
        .clk(core_clk),.rst(rst),.init_done(init_done),.passed(passed),.failed(failed),
        .checked_words(checked_words),.source_checked_words(source_checked_words),
        .scratch_checked_words(scratch_checked_words),.passed_stages(passed_stages),.stage_code(stage_code),
        .failure_word(failure_word),.expected_data(expected_data),.observed_data(observed_data),
        .failure_reason(failure_reason),.completed_elements(completed_elements),
        .refresh_count(refresh_count),.elapsed_cycles(elapsed_cycles),
        .dram_cke(DRAM_CKE),.dram_cs_n(DRAM_CS_N),.dram_ras_n(DRAM_RAS_N),
        .dram_cas_n(DRAM_CAS_N),.dram_we_n(DRAM_WE_N),.dram_addr(DRAM_ADDR),
        .dram_ba(DRAM_BA),.dram_dqm({DRAM_UDQM,DRAM_LDQM}),
        .dram_dq_out(dq_out),.dram_dq_oe(dq_oe),.dram_dq_in(DRAM_DQ),.read_trace(read_trace)
    );
endmodule
`default_nettype wire
