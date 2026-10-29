`default_nettype none

// External SDRAM source and an 8 KiB banked destination scratchpad.
// The maintenance port loads/inspects memory while the copy engine is idle.
module tma_sdram_copy_system #(
    parameter bit PIPELINED = 0,
    parameter bit SWIZZLE = 0,
    parameter int unsigned SWIZZLE_SHIFT = 5,
    parameter int unsigned READ_BURST_WORDS = 1
) (
    input wire clk,
    input wire rst,
    input wire desc_valid,
    output wire desc_ready,
    input wire [31:0] desc_src_base,
    input wire [31:0] desc_dst_base,
    input wire [15:0] desc_rows,
    input wire [15:0] desc_cols,
    input wire [31:0] desc_src_row_stride,
    input wire [31:0] desc_src_col_stride,
    input wire [31:0] desc_dst_row_stride,
    input wire [31:0] desc_dst_col_stride,
    input wire maint_req_valid,
    output wire maint_req_ready,
    input wire maint_req_write,
    input wire maint_req_dst,
    input wire [31:0] maint_req_addr,
    input wire [15:0] maint_req_data,
    output wire maint_rsp_valid,
    input wire maint_rsp_ready,
    output wire [15:0] maint_rsp_data,
    output wire maint_rsp_error,
    output wire busy,
    output wire done,
    output wire error,
    output wire [2:0] error_code,
    output wire [31:0] completed_elements,
    output wire [63:0] elapsed_cycles,
    output wire [63:0] read_wait_cycles,
    output wire [63:0] write_wait_cycles,
    output wire init_done,
    output wire [31:0] refresh_count,
    output wire dram_cke, dram_cs_n, dram_ras_n, dram_cas_n, dram_we_n,
    output wire [12:0] dram_addr,
    output wire [1:0] dram_ba, dram_dqm,
    output wire [15:0] dram_dq_out,
    output wire dram_dq_oe,
    input wire [15:0] dram_dq_in,
    output wire [31:0] dst_bank_conflict_cycles,
    output wire [255:0] read_trace
);
    logic maint_active_q, maint_write_q, maint_dst_q;
    wire engine_desc_ready;
    wire ctrl_allowed = init_done && !busy && !maint_active_q && !desc_valid;
    wire ctrl_req = maint_req_valid && ctrl_allowed;
    wire engine_rd_valid, engine_rd_ready, engine_rd_rsp_ready;
    wire [31:0] engine_rd_addr;
    wire engine_wr_valid, engine_wr_ready, engine_wr_rsp_ready;
    wire [31:0] engine_wr_addr;
    wire [15:0] engine_wr_data;
    wire src_rd_ready, src_rd_valid, src_rd_error;
    wire [15:0] src_rd_data;
    wire src_wr_ready, src_wr_valid, src_wr_error;
    wire dst_rd_ready, dst_rd_valid, dst_rd_error;
    wire [15:0] dst_rd_data;
    wire dst_wr_ready, dst_wr_valid, dst_wr_error;

    assign desc_ready = init_done && engine_desc_ready && !maint_active_q;
    assign maint_req_ready = ctrl_allowed &&
        (maint_req_dst ? (maint_req_write ? dst_wr_ready : dst_rd_ready) :
                        (maint_req_write ? src_wr_ready : src_rd_ready));
    assign maint_rsp_valid = maint_active_q &&
        (maint_dst_q ? (maint_write_q ? dst_wr_valid : dst_rd_valid) :
                       (maint_write_q ? src_wr_valid : src_rd_valid));
    assign maint_rsp_error = maint_dst_q ?
        (maint_write_q ? dst_wr_error : dst_rd_error) :
        (maint_write_q ? src_wr_error : src_rd_error);
    assign maint_rsp_data = maint_write_q ? 16'b0 : (maint_dst_q ? dst_rd_data : src_rd_data);
    assign engine_rd_ready = src_rd_ready;
    assign engine_wr_ready = dst_wr_ready;

    always_ff @(posedge clk) begin
        if (rst) begin
            maint_active_q <= 1'b0;
            maint_write_q <= 1'b0;
            maint_dst_q <= 1'b0;
        end else begin
            if (maint_req_valid && maint_req_ready) begin
                maint_active_q <= 1'b1;
                maint_write_q <= maint_req_write;
                maint_dst_q <= maint_req_dst;
            end else if (maint_rsp_valid && maint_rsp_ready) begin
                maint_active_q <= 1'b0;
            end
        end
    end

    tma_copy_engine_select #(.PIPELINED(PIPELINED), .SRC_BYTES(67108864)) engine (
        .clk(clk), .rst(rst),
        .desc_valid(desc_valid && !maint_active_q && init_done), .desc_ready(engine_desc_ready),
        .desc_src_base(desc_src_base), .desc_dst_base(desc_dst_base),
        .desc_rows(desc_rows), .desc_cols(desc_cols),
        .desc_src_row_stride(desc_src_row_stride), .desc_src_col_stride(desc_src_col_stride),
        .desc_dst_row_stride(desc_dst_row_stride), .desc_dst_col_stride(desc_dst_col_stride),
        .rd_req_valid(engine_rd_valid), .rd_req_ready(engine_rd_ready), .rd_req_addr(engine_rd_addr),
        .rd_rsp_valid(src_rd_valid && busy), .rd_rsp_ready(engine_rd_rsp_ready),
        .rd_rsp_data(src_rd_data), .rd_rsp_error(src_rd_error),
        .wr_req_valid(engine_wr_valid), .wr_req_ready(engine_wr_ready),
        .wr_req_addr(engine_wr_addr), .wr_req_data(engine_wr_data),
        .wr_rsp_valid(dst_wr_valid && busy), .wr_rsp_ready(engine_wr_rsp_ready),
        .wr_rsp_error(dst_wr_error), .busy(busy), .done(done), .error(error),
        .error_code(error_code), .completed_elements(completed_elements),
        .elapsed_cycles(elapsed_cycles), .read_wait_cycles(read_wait_cycles),
        .write_wait_cycles(write_wait_cycles)
    );

    tma_sdram_controller #(.READ_BURST_WORDS(READ_BURST_WORDS)) source (
        .clk(clk), .rst(rst),
        .rd_req_valid(busy ? engine_rd_valid : (ctrl_req && !maint_req_write && !maint_req_dst)),
        .rd_req_ready(src_rd_ready), .rd_req_addr(busy ? engine_rd_addr : maint_req_addr),
        .rd_rsp_valid(src_rd_valid), .rd_rsp_ready(busy ? engine_rd_rsp_ready :
            (maint_active_q && !maint_dst_q && !maint_write_q && maint_rsp_ready)),
        .rd_rsp_data(src_rd_data), .rd_rsp_error(src_rd_error),
        .wr_req_valid(ctrl_req && maint_req_write && !maint_req_dst),
        .wr_req_ready(src_wr_ready), .wr_req_addr(maint_req_addr), .wr_req_data(maint_req_data),
        .wr_rsp_valid(src_wr_valid), .wr_rsp_ready(maint_active_q && !maint_dst_q &&
            maint_write_q && maint_rsp_ready), .wr_rsp_error(src_wr_error),
        .init_done(init_done), .refresh_count(refresh_count), .active(),
        .dram_cke(dram_cke), .dram_cs_n(dram_cs_n), .dram_ras_n(dram_ras_n),
        .dram_cas_n(dram_cas_n), .dram_we_n(dram_we_n), .dram_addr(dram_addr),
        .dram_ba(dram_ba), .dram_dqm(dram_dqm), .dram_dq_out(dram_dq_out),
        .dram_dq_oe(dram_dq_oe), .dram_dq_in(dram_dq_in), .read_trace(read_trace)
    );
    tma_scratchpad_endpoint #(.SWIZZLE(SWIZZLE), .SWIZZLE_SHIFT(SWIZZLE_SHIFT)) destination (
        .clk(clk), .rst(rst),
        .rd_req_valid(ctrl_req && !maint_req_write && maint_req_dst),
        .rd_req_ready(dst_rd_ready), .rd_req_addr(maint_req_addr),
        .rd_rsp_valid(dst_rd_valid), .rd_rsp_ready(maint_active_q && maint_dst_q &&
            !maint_write_q && maint_rsp_ready), .rd_rsp_data(dst_rd_data), .rd_rsp_error(dst_rd_error),
        .wr_req_valid(busy ? engine_wr_valid : (ctrl_req && maint_req_write && maint_req_dst)),
        .wr_req_ready(dst_wr_ready), .wr_req_addr(busy ? engine_wr_addr : maint_req_addr),
        .wr_req_data(busy ? engine_wr_data : maint_req_data),
        .wr_rsp_valid(dst_wr_valid), .wr_rsp_ready(busy ? engine_wr_rsp_ready :
            (maint_active_q && maint_dst_q && maint_write_q && maint_rsp_ready)),
        .wr_rsp_error(dst_wr_error), .bank_conflict_cycles(dst_bank_conflict_cycles)
    );
endmodule

`default_nettype wire
