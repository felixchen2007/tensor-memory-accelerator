// Connects the accelerator to the pin-level SDRAM model for cocotb.
// It snapshots interface signals on each rising edge so Python can check which transfers occurred.

`timescale 1ns/1ps
module tb_tma_cocotb #(
    parameter bit PIPELINED=1,SWIZZLE=0,
    parameter int READ_BURST_WORDS=4,
    parameter logic [15:0] READ_XOR_MASK=0
);
    logic clk=0,rst=1,dram_clk=0;
    always #10 clk=~clk;
    always @(clk) dram_clk <= #5 clk;
    initial begin repeat(4) @(posedge clk);@(negedge clk);rst=0;end
    logic desc_valid=0,desc_ready;
    logic [31:0] desc_src_base=0,desc_dst_base=0;
    logic [15:0] desc_rows=0,desc_cols=0;
    logic [31:0] desc_src_row_stride=0,desc_src_col_stride=0;
    logic [31:0] desc_dst_row_stride=0,desc_dst_col_stride=0;
    logic maint_req_valid=0,maint_req_ready,maint_req_write=0,maint_req_dst=0;
    logic [31:0] maint_req_addr=0;
    logic [15:0] maint_req_data=0;
    logic maint_rsp_valid,maint_rsp_ready=0,maint_rsp_error;
    logic [15:0] maint_rsp_data;
    logic init_done,busy,done,error;
    logic [2:0] error_code;
    logic [31:0] completed_elements;
    logic [63:0] elapsed_cycles;
    // Passive taps at the engine's actual request/response interfaces.
    // No RAM contents or controller state are exposed to the scoreboard.
    logic rd_valid,rd_ready,rd_rsp_valid,rd_rsp_ready,rd_error;
    logic [31:0] rd_addr;
    logic [15:0] rd_data;
    logic wr_valid,wr_ready,wr_rsp_valid,wr_rsp_ready,wr_error;
    logic [31:0] wr_addr;
    logic [15:0] wr_data;
    wire dram_cke,dram_cs_n,dram_ras_n,dram_cas_n,dram_we_n,dram_dq_oe;
    wire [12:0] dram_addr;
    wire [1:0] dram_ba,dram_dqm;
    wire [15:0] dram_dq_out;
    tri [15:0] dq;
    assign dq=dram_dq_oe ? dram_dq_out : 16'hzzzz;
    wire [31:0] refresh_count;
    integer reads,writes,refreshes,max_refresh_gap;
    tma_sdram_copy_system #(.PIPELINED(PIPELINED),.SWIZZLE(SWIZZLE),.READ_BURST_WORDS(READ_BURST_WORDS)) dut (
        .clk(clk),.rst(rst),.desc_valid(desc_valid),.desc_ready(desc_ready),
        .desc_src_base(desc_src_base),.desc_dst_base(desc_dst_base),
        .desc_rows(desc_rows),.desc_cols(desc_cols),
        .desc_src_row_stride(desc_src_row_stride),.desc_src_col_stride(desc_src_col_stride),
        .desc_dst_row_stride(desc_dst_row_stride),.desc_dst_col_stride(desc_dst_col_stride),
        .maint_req_valid(maint_req_valid),.maint_req_ready(maint_req_ready),
        .maint_req_write(maint_req_write),.maint_req_dst(maint_req_dst),
        .maint_req_addr(maint_req_addr),.maint_req_data(maint_req_data),
        .maint_rsp_valid(maint_rsp_valid),.maint_rsp_ready(maint_rsp_ready),
        .maint_rsp_data(maint_rsp_data),.maint_rsp_error(maint_rsp_error),
        .busy(busy),.done(done),.error(error),.error_code(error_code),
        .completed_elements(completed_elements),.elapsed_cycles(elapsed_cycles),
        .init_done(init_done),.refresh_count(refresh_count),.read_wait_cycles(),.write_wait_cycles(),
        .dst_bank_conflict_cycles(),.read_trace(),.dram_dq_in(dq),.*
    );
    assign rd_valid=dut.engine_rd_valid;
    assign rd_ready=dut.engine_rd_ready;
    assign rd_addr=dut.engine_rd_addr;
    assign rd_rsp_valid=dut.src_rd_valid && busy;
    assign rd_rsp_ready=dut.engine_rd_rsp_ready;
    assign rd_data=dut.src_rd_data;
    assign rd_error=dut.src_rd_error;
    assign wr_valid=dut.engine_wr_valid;
    assign wr_ready=dut.engine_wr_ready;
    assign wr_addr=dut.engine_wr_addr;
    assign wr_data=dut.engine_wr_data;
    assign wr_rsp_valid=dut.dst_wr_valid && busy;
    assign wr_rsp_ready=dut.engine_wr_rsp_ready;
    assign wr_error=dut.dst_wr_error;

    // Snapshot the handshake edge before the RTL's nonblocking updates.
    // Python consumes these observations on the falling edge.
    logic [16:0] sampled_flags;
    logic [223:0] sampled_desc;
    logic [49:0] sampled_maint;
    logic [16:0] sampled_maint_response, sampled_read_response;
    logic [31:0] sampled_read;
    logic [47:0] sampled_write;
    logic sampled_write_response;
    logic [35:0] sampled_completion;
    always @(posedge clk) begin
        sampled_flags <= {done, busy, init_done,
                          wr_rsp_ready, wr_rsp_valid, wr_ready, wr_valid,
                          rd_rsp_ready, rd_rsp_valid, rd_ready, rd_valid,
                          maint_rsp_ready, maint_rsp_valid, maint_req_ready, maint_req_valid,
                          desc_ready, desc_valid};
        sampled_desc <= {desc_src_base, desc_dst_base, desc_rows, desc_cols,
                         desc_src_row_stride, desc_src_col_stride, desc_dst_row_stride, desc_dst_col_stride};
        sampled_maint <= {maint_req_write, maint_req_dst, maint_req_addr, maint_req_data};
        sampled_maint_response <= {maint_rsp_error, maint_rsp_data};
        sampled_read <= rd_addr;
        sampled_read_response <= {rd_error, rd_data};
        sampled_write <= {wr_addr, wr_data};
        sampled_write_response <= wr_error;
        sampled_completion <= {error_code, error, completed_elements};
    end
    tma_sdram_model #(.READ_XOR_MASK(READ_XOR_MASK)) memory (.power_reset(rst),.cke(dram_cke),
        .cs_n(dram_cs_n),.ras_n(dram_ras_n),.cas_n(dram_cas_n),.we_n(dram_we_n),
        .addr(dram_addr),.ba(dram_ba),.dqm(dram_dqm),.controller_oe(dram_dq_oe),.dq(dq),.*);
endmodule
