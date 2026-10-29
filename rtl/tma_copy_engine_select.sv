`default_nettype none

module tma_copy_engine_select #(
    parameter bit PIPELINED = 0,
    parameter int unsigned SRC_BYTES = 8192,
    parameter int unsigned DST_BYTES = 8192
) (
    input wire clk, rst,
    input wire desc_valid,
    output wire desc_ready,
    input wire [31:0] desc_src_base, desc_dst_base,
    input wire [15:0] desc_rows, desc_cols,
    input wire [31:0] desc_src_row_stride, desc_src_col_stride,
    input wire [31:0] desc_dst_row_stride, desc_dst_col_stride,
    output wire rd_req_valid,
    input wire rd_req_ready,
    output wire [31:0] rd_req_addr,
    input wire rd_rsp_valid,
    output wire rd_rsp_ready,
    input wire [15:0] rd_rsp_data,
    input wire rd_rsp_error,
    output wire wr_req_valid,
    input wire wr_req_ready,
    output wire [31:0] wr_req_addr,
    output wire [15:0] wr_req_data,
    input wire wr_rsp_valid,
    output wire wr_rsp_ready,
    input wire wr_rsp_error,
    output wire busy, done, error,
    output wire [2:0] error_code,
    output wire [31:0] completed_elements,
    output wire [63:0] elapsed_cycles, read_wait_cycles, write_wait_cycles
);
    generate
        if (PIPELINED) begin : pipelined
            tma_copy_engine_pipelined #(.SRC_BYTES(SRC_BYTES), .DST_BYTES(DST_BYTES))
                impl (.peak_buffered(), .buffer_stall_cycles(), .*);
        end else begin : serialized
            tma_copy_engine #(.SRC_BYTES(SRC_BYTES), .DST_BYTES(DST_BYTES)) impl (.*);
        end
    endgenerate
endmodule

`default_nettype wire
