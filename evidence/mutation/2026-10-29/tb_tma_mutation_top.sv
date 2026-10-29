`timescale 1ns/1ps
`include "uvm_macros.svh"
module tb_tma_uvm #(
    parameter bit PIPELINED=1,SWIZZLE=0,
    parameter int READ_BURST_WORDS=4,
    parameter logic [15:0] READ_XOR_MASK=0
);
    import uvm_pkg::*;
    import tma_uvm_pkg::*;
    import tma_mutation_pkg::*;
    logic clk=0,rst=1,dram_clk=0;
    always #10 clk=~clk;
    always @(clk) dram_clk <= #5 clk;
    initial begin repeat(4) @(posedge clk);@(negedge clk);rst=0;end
    tma_uvm_if vif(clk,rst);
    wire dram_cke,dram_cs_n,dram_ras_n,dram_cas_n,dram_we_n,dram_dq_oe;
    wire [12:0] dram_addr;
    wire [1:0] dram_ba,dram_dqm;
    wire [15:0] dram_dq_out;
    tri [15:0] dq;
    assign dq=dram_dq_oe ? dram_dq_out : 16'hzzzz;
    wire [31:0] refresh_count;
    integer reads,writes,refreshes,max_refresh_gap;
    tma_sdram_copy_system #(.PIPELINED(PIPELINED),.SWIZZLE(SWIZZLE),.READ_BURST_WORDS(READ_BURST_WORDS)) dut (
        .clk(clk),.rst(rst),.desc_valid(vif.desc_valid),.desc_ready(vif.desc_ready),
        .desc_src_base(vif.desc_src_base),.desc_dst_base(vif.desc_dst_base),
        .desc_rows(vif.desc_rows),.desc_cols(vif.desc_cols),
        .desc_src_row_stride(vif.desc_src_row_stride),.desc_src_col_stride(vif.desc_src_col_stride),
        .desc_dst_row_stride(vif.desc_dst_row_stride),.desc_dst_col_stride(vif.desc_dst_col_stride),
        .maint_req_valid(vif.maint_req_valid),.maint_req_ready(vif.maint_req_ready),
        .maint_req_write(vif.maint_req_write),.maint_req_dst(vif.maint_req_dst),
        .maint_req_addr(vif.maint_req_addr),.maint_req_data(vif.maint_req_data),
        .maint_rsp_valid(vif.maint_rsp_valid),.maint_rsp_ready(vif.maint_rsp_ready),
        .maint_rsp_data(vif.maint_rsp_data),.maint_rsp_error(vif.maint_rsp_error),
        .busy(vif.busy),.done(vif.done),.error(vif.error),.error_code(vif.error_code),
        .completed_elements(vif.completed_elements),.elapsed_cycles(vif.elapsed_cycles),
        .init_done(vif.init_done),.refresh_count(refresh_count),.read_wait_cycles(),.write_wait_cycles(),
        .dst_bank_conflict_cycles(),.read_trace(),.dram_dq_in(dq),.*
    );
    assign vif.rd_valid=dut.engine_rd_valid;
    assign vif.rd_ready=dut.engine_rd_ready;
    assign vif.rd_addr=dut.engine_rd_addr;
    assign vif.rd_rsp_valid=dut.src_rd_valid && vif.busy;
    assign vif.rd_rsp_ready=dut.engine_rd_rsp_ready;
    assign vif.rd_data=dut.src_rd_data;
    assign vif.rd_error=dut.src_rd_error;
    assign vif.wr_valid=dut.engine_wr_valid;
    assign vif.wr_ready=dut.engine_wr_ready;
    assign vif.wr_addr=dut.engine_wr_addr;
    assign vif.wr_data=dut.engine_wr_data;
    assign vif.wr_rsp_valid=dut.dst_wr_valid && vif.busy;
    assign vif.wr_rsp_ready=dut.engine_wr_rsp_ready;
    assign vif.wr_error=dut.dst_wr_error;
    tma_sdram_model #(.READ_XOR_MASK(READ_XOR_MASK)) memory (.power_reset(rst),.cke(dram_cke),
        .cs_n(dram_cs_n),.ras_n(dram_ras_n),.cas_n(dram_cas_n),.we_n(dram_we_n),
        .addr(dram_addr),.ba(dram_ba),.dqm(dram_dqm),.controller_oe(dram_dq_oe),.dq(dq),.*);
    initial begin
        uvm_config_db#(virtual tma_uvm_if)::set(null,"uvm_test_top.*","vif",vif);
        uvm_config_db#(int)::set(null,"uvm_test_top","pipelined",PIPELINED);
        uvm_config_db#(int)::set(null,"uvm_test_top","swizzle",SWIZZLE);
        uvm_config_db#(int)::set(null,"uvm_test_top","burst_words",READ_BURST_WORDS);
        run_test("tma_mutation_test");
    end
    initial begin #100000000;`uvm_fatal("TMA_WATCHDOG","UVM simulation exceeded 100 ms") end

    always @(negedge clk) begin : mutation_error_stop
        uvm_report_server server;
        server=uvm_report_server::get_server();
        if(server.get_severity_count(UVM_ERROR)>0) begin
            server.report_summarize();
            $display("TMA_MUTATION_STOP_AFTER_UVM_ERROR");
            $finish;
        end
    end
endmodule
