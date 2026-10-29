`default_nettype none

// Row-major traversal of a 2D descriptor. All addresses/strides are byte offsets.
// Arithmetic intentionally wraps at ADDR_W bits. See docs/architecture.md.
module tma_addr_gen #(
    parameter int unsigned ADDR_W = 32,
    parameter int unsigned COUNT_W = 16
) (
    input  wire                  clk,
    input  wire                  rst,

    input  wire                  desc_valid,
    output wire                  desc_ready,
    input  wire [ADDR_W-1:0]     desc_src_base,
    input  wire [ADDR_W-1:0]     desc_dst_base,
    input  wire [COUNT_W-1:0]    desc_rows,
    input  wire [COUNT_W-1:0]    desc_cols,
    input  wire [ADDR_W-1:0]     desc_src_row_stride,
    input  wire [ADDR_W-1:0]     desc_src_col_stride,
    input  wire [ADDR_W-1:0]     desc_dst_row_stride,
    input  wire [ADDR_W-1:0]     desc_dst_col_stride,

    output wire                  addr_valid,
    input  wire                  addr_ready,
    output logic [ADDR_W-1:0]    src_addr,
    output logic [ADDR_W-1:0]    dst_addr,
    output wire                  addr_last,
    output wire                  busy,
    output logic                 done,
    output logic                 error
);

    logic active_q;
    logic [COUNT_W-1:0] row_q, col_q, last_row_q, last_col_q;
    logic [ADDR_W-1:0] src_row_base_q, dst_row_base_q;
    logic [ADDR_W-1:0] src_row_stride_q, src_col_stride_q;
    logic [ADDR_W-1:0] dst_row_stride_q, dst_col_stride_q;

    assign desc_ready = !active_q;
    assign addr_valid = active_q;
    assign busy = active_q;
    assign addr_last = active_q && (row_q == last_row_q) &&
                       (col_q == last_col_q);

    always_ff @(posedge clk) begin
        if (rst) begin
            active_q <= 1'b0;
            row_q <= '0;
            col_q <= '0;
            last_row_q <= '0;
            last_col_q <= '0;
            src_row_base_q <= '0;
            dst_row_base_q <= '0;
            src_row_stride_q <= '0;
            src_col_stride_q <= '0;
            dst_row_stride_q <= '0;
            dst_col_stride_q <= '0;
            src_addr <= '0;
            dst_addr <= '0;
            done <= 1'b0;
            error <= 1'b0;
        end else begin
            done <= 1'b0;
            error <= 1'b0;

            if (desc_valid && desc_ready) begin
                if ((desc_rows == '0) || (desc_cols == '0)) begin
                    done <= 1'b1;
                    error <= 1'b1;
                end else begin
                    active_q <= 1'b1;
                    row_q <= '0;
                    col_q <= '0;
                    last_row_q <= desc_rows - 1'b1;
                    last_col_q <= desc_cols - 1'b1;
                    src_row_base_q <= desc_src_base;
                    dst_row_base_q <= desc_dst_base;
                    src_addr <= desc_src_base;
                    dst_addr <= desc_dst_base;
                    src_row_stride_q <= desc_src_row_stride;
                    src_col_stride_q <= desc_src_col_stride;
                    dst_row_stride_q <= desc_dst_row_stride;
                    dst_col_stride_q <= desc_dst_col_stride;
                end
            end else if (addr_valid && addr_ready) begin
                if (addr_last) begin
                    active_q <= 1'b0;
                    done <= 1'b1;
                end else if (col_q == last_col_q) begin
                    row_q <= row_q + 1'b1;
                    col_q <= '0;
                    src_row_base_q <= src_row_base_q + src_row_stride_q;
                    dst_row_base_q <= dst_row_base_q + dst_row_stride_q;
                    src_addr <= src_row_base_q + src_row_stride_q;
                    dst_addr <= dst_row_base_q + dst_row_stride_q;
                end else begin
                    col_q <= col_q + 1'b1;
                    src_addr <= src_addr + src_col_stride_q;
                    dst_addr <= dst_addr + dst_col_stride_q;
                end
            end
        end
    end

endmodule

`default_nettype wire
