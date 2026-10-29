`default_nettype none

// Serialized 16-bit copy baseline. A successful write response acknowledges
// completion, not just acceptance of the write request. See docs/copy_engine.md.
module tma_copy_engine #(
    parameter int unsigned ADDR_W = 32,
    parameter int unsigned COUNT_W = 16,
    parameter int unsigned SRC_BYTES = 8192,
    parameter int unsigned DST_BYTES = 8192
) (
    input  wire clk,
    input  wire rst,
    input  wire desc_valid,
    output wire desc_ready,
    input  wire [ADDR_W-1:0] desc_src_base,
    input  wire [ADDR_W-1:0] desc_dst_base,
    input  wire [COUNT_W-1:0] desc_rows,
    input  wire [COUNT_W-1:0] desc_cols,
    input  wire [ADDR_W-1:0] desc_src_row_stride,
    input  wire [ADDR_W-1:0] desc_src_col_stride,
    input  wire [ADDR_W-1:0] desc_dst_row_stride,
    input  wire [ADDR_W-1:0] desc_dst_col_stride,

    output wire rd_req_valid,
    input  wire rd_req_ready,
    output wire [ADDR_W-1:0] rd_req_addr,
    input  wire rd_rsp_valid,
    output wire rd_rsp_ready,
    input  wire [15:0] rd_rsp_data,
    input  wire rd_rsp_error,

    output wire wr_req_valid,
    input  wire wr_req_ready,
    output wire [ADDR_W-1:0] wr_req_addr,
    output wire [15:0] wr_req_data,
    input  wire wr_rsp_valid,
    output wire wr_rsp_ready,
    input  wire wr_rsp_error,

    output wire busy,
    output logic done,
    output logic error,
    output logic [2:0] error_code,
    output logic [31:0] completed_elements,
    output logic [63:0] elapsed_cycles,
    output logic [63:0] read_wait_cycles,
    output logic [63:0] write_wait_cycles
);
    // Require ADDR_W >= 2, COUNT_W >= 1, and even endpoint sizes in
    // [2, 2**(ADDR_W-1)]. Bounded unsigned strides prevent address wrap before
    // the per-element bounds check. Only the default widths are validated so far.
    localparam logic [ADDR_W-1:0] SRC_LAST = ADDR_W'(SRC_BYTES - 2);
    localparam logic [ADDR_W-1:0] DST_LAST = ADDR_W'(DST_BYTES - 2);
    localparam logic [2:0] OK = 3'd0, EMPTY = 3'd1, ALIGNMENT = 3'd2,
                            BOUNDS = 3'd3, READ_ERROR = 3'd4, WRITE_ERROR = 3'd5;

    typedef enum logic [2:0] {
        IDLE, FETCH, READ_REQ, READ_RSP, WRITE_REQ, WRITE_RSP, FINISH
    } state_t;
    state_t state_q;
    logic [ADDR_W-1:0] src_q, dst_q;
    logic [15:0] data_q;
    logic last_q;
    wire gen_valid, gen_ready, gen_last;
    wire [ADDR_W-1:0] gen_src, gen_dst;
    wire descriptor_empty = (desc_rows == '0) || (desc_cols == '0);
    wire descriptor_unaligned = desc_src_base[0] || desc_dst_base[0] ||
        desc_src_row_stride[0] || desc_src_col_stride[0] ||
        desc_dst_row_stride[0] || desc_dst_col_stride[0];
    wire descriptor_outside = (desc_src_base > SRC_LAST) ||
        (desc_dst_base > DST_LAST) || (desc_src_row_stride > SRC_LAST) ||
        (desc_src_col_stride > SRC_LAST) || (desc_dst_row_stride > DST_LAST) ||
        (desc_dst_col_stride > DST_LAST);
    wire descriptor_legal = !descriptor_empty && !descriptor_unaligned &&
                            !descriptor_outside;

    assign desc_ready = (state_q == IDLE);
    assign busy = (state_q != IDLE);
    assign gen_ready = (state_q == FETCH);
    assign rd_req_valid = (state_q == READ_REQ);
    assign rd_req_addr = src_q;
    assign rd_rsp_ready = (state_q == READ_RSP);
    assign wr_req_valid = (state_q == WRITE_REQ);
    assign wr_req_addr = dst_q;
    assign wr_req_data = data_q;
    assign wr_rsp_ready = (state_q == WRITE_RSP);

    tma_addr_gen #(.ADDR_W(ADDR_W), .COUNT_W(COUNT_W)) address_generator (
        .clk(clk), .rst(rst || (state_q == FINISH)),
        .desc_valid(desc_valid && desc_ready && descriptor_legal),
        .desc_ready(), .desc_src_base(desc_src_base), .desc_dst_base(desc_dst_base),
        .desc_rows(desc_rows), .desc_cols(desc_cols),
        .desc_src_row_stride(desc_src_row_stride),
        .desc_src_col_stride(desc_src_col_stride),
        .desc_dst_row_stride(desc_dst_row_stride),
        .desc_dst_col_stride(desc_dst_col_stride),
        .addr_valid(gen_valid), .addr_ready(gen_ready),
        .src_addr(gen_src), .dst_addr(gen_dst), .addr_last(gen_last),
        .busy(), .done(), .error()
    );

    always_ff @(posedge clk) begin
        if (rst) begin
            state_q <= IDLE;
            src_q <= '0;
            dst_q <= '0;
            data_q <= '0;
            last_q <= 1'b0;
            done <= 1'b0;
            error <= 1'b0;
            error_code <= OK;
            completed_elements <= '0;
            elapsed_cycles <= '0;
            read_wait_cycles <= '0;
            write_wait_cycles <= '0;
        end else begin
            done <= 1'b0;
            error <= 1'b0;
            if (busy)
                elapsed_cycles <= elapsed_cycles + 1'b1;
            if ((rd_req_valid && !rd_req_ready) || (rd_rsp_ready && !rd_rsp_valid))
                read_wait_cycles <= read_wait_cycles + 1'b1;
            if ((wr_req_valid && !wr_req_ready) || (wr_rsp_ready && !wr_rsp_valid))
                write_wait_cycles <= write_wait_cycles + 1'b1;

            case (state_q)
                IDLE: if (desc_valid) begin
                    completed_elements <= '0;
                    elapsed_cycles <= '0;
                    read_wait_cycles <= '0;
                    write_wait_cycles <= '0;
                    if (descriptor_empty) begin
                        error_code <= EMPTY;
                        state_q <= FINISH;
                    end else if (descriptor_unaligned) begin
                        error_code <= ALIGNMENT;
                        state_q <= FINISH;
                    end else if (descriptor_outside) begin
                        error_code <= BOUNDS;
                        state_q <= FINISH;
                    end else begin
                        error_code <= OK;
                        state_q <= FETCH;
                    end
                end
                FETCH: if (gen_valid) begin
                    if ((gen_src > SRC_LAST) || (gen_dst > DST_LAST)) begin
                        error_code <= BOUNDS;
                        state_q <= FINISH;
                    end else begin
                        src_q <= gen_src;
                        dst_q <= gen_dst;
                        last_q <= gen_last;
                        state_q <= READ_REQ;
                    end
                end
                READ_REQ: if (rd_req_ready)
                    state_q <= READ_RSP;
                READ_RSP: if (rd_rsp_valid) begin
                    if (rd_rsp_error) begin
                        error_code <= READ_ERROR;
                        state_q <= FINISH;
                    end else begin
                        data_q <= rd_rsp_data;
                        state_q <= WRITE_REQ;
                    end
                end
                WRITE_REQ: if (wr_req_ready)
                    state_q <= WRITE_RSP;
                WRITE_RSP: if (wr_rsp_valid) begin
                    if (wr_rsp_error) begin
                        error_code <= WRITE_ERROR;
                        state_q <= FINISH;
                    end else begin
                        completed_elements <= completed_elements + 1'b1;
                        state_q <= last_q ? FINISH : FETCH;
                    end
                end
                FINISH: begin
                    state_q <= IDLE;
                    done <= 1'b1;
                    error <= (error_code != OK);
                end
                default: state_q <= IDLE;
            endcase
        end
    end
endmodule

`default_nettype wire
