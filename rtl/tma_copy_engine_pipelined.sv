`default_nettype none

// Ordered copy pipeline: one pending read, a data/destination FIFO, and one
// pending write. Both channels can replace a response on its acceptance edge.
module tma_copy_engine_pipelined #(
    parameter int unsigned ADDR_W = 32,
    parameter int unsigned COUNT_W = 16,
    parameter int unsigned SRC_BYTES = 8192,
    parameter int unsigned DST_BYTES = 8192,
    parameter int unsigned FIFO_DEPTH = 4
) (
    input wire clk, rst,
    input wire desc_valid,
    output wire desc_ready,
    input wire [ADDR_W-1:0] desc_src_base, desc_dst_base,
    input wire [COUNT_W-1:0] desc_rows, desc_cols,
    input wire [ADDR_W-1:0] desc_src_row_stride, desc_src_col_stride,
    input wire [ADDR_W-1:0] desc_dst_row_stride, desc_dst_col_stride,
    output wire rd_req_valid,
    input wire rd_req_ready,
    output wire [ADDR_W-1:0] rd_req_addr,
    input wire rd_rsp_valid,
    output wire rd_rsp_ready,
    input wire [15:0] rd_rsp_data,
    input wire rd_rsp_error,
    output wire wr_req_valid,
    input wire wr_req_ready,
    output wire [ADDR_W-1:0] wr_req_addr,
    output wire [15:0] wr_req_data,
    input wire wr_rsp_valid,
    output wire wr_rsp_ready,
    input wire wr_rsp_error,
    output wire busy,
    output logic done, error,
    output logic [2:0] error_code,
    output logic [31:0] completed_elements,
    output logic [63:0] elapsed_cycles, read_wait_cycles, write_wait_cycles,
    output logic [$clog2(FIFO_DEPTH+1)-1:0] peak_buffered,
    output logic [63:0] buffer_stall_cycles
);
    // Same address/count bounds as the baseline. FIFO_DEPTH must be a power of
    // two >= 2. The default 32/16-bit, four-entry configuration is verified.
    localparam int PTR_W = $clog2(FIFO_DEPTH);
    localparam int USED_W = $clog2(FIFO_DEPTH + 1);
    localparam logic [ADDR_W-1:0] SRC_LAST = ADDR_W'(SRC_BYTES - 2);
    localparam logic [ADDR_W-1:0] DST_LAST = ADDR_W'(DST_BYTES - 2);
    localparam logic [2:0] OK = 0, EMPTY = 1, ALIGNMENT = 2,
                            BOUNDS = 3, READ_ERROR = 4, WRITE_ERROR = 5;
    typedef enum logic [1:0] {IDLE, RUN, FINISH} state_t;
    state_t state_q;
    logic allocation_done_q, drop_reads_q, drop_writes_q;
    logic slot_valid_q, read_pending_q, write_pending_q;
    logic [ADDR_W-1:0] slot_src_q, slot_dst_q, pending_dst_q;
    logic [PTR_W-1:0] head_q, tail_q;
    logic [USED_W-1:0] used_q, next_used;
    logic [15:0] fifo_data [0:FIFO_DEPTH-1];
    logic [ADDR_W-1:0] fifo_dst [0:FIFO_DEPTH-1];
    wire gen_valid, gen_ready, gen_last;
    wire [ADDR_W-1:0] gen_src, gen_dst;
    wire descriptor_empty = (desc_rows == 0) || (desc_cols == 0);
    wire descriptor_unaligned = desc_src_base[0] || desc_dst_base[0] ||
        desc_src_row_stride[0] || desc_src_col_stride[0] ||
        desc_dst_row_stride[0] || desc_dst_col_stride[0];
    wire descriptor_outside = (desc_src_base > SRC_LAST) || (desc_dst_base > DST_LAST) ||
        (desc_src_row_stride > SRC_LAST) || (desc_src_col_stride > SRC_LAST) ||
        (desc_dst_row_stride > DST_LAST) || (desc_dst_col_stride > DST_LAST);
    wire descriptor_legal = !descriptor_empty && !descriptor_unaligned && !descriptor_outside;

    assign busy = (state_q != IDLE);
    assign desc_ready = !busy;
    assign wr_rsp_ready = (state_q == RUN) && write_pending_q;
    wire write_response = wr_rsp_valid && wr_rsp_ready;
    wire write_fault = write_response && wr_rsp_error;
    // A later write cannot escape on the cycle an earlier write reports failure.
    assign wr_req_valid = (state_q == RUN) && !drop_writes_q && (used_q != 0) &&
        (!write_pending_q || (write_response && !wr_rsp_error));
    assign wr_req_addr = fifo_dst[head_q];
    assign wr_req_data = fifo_data[head_q];
    wire pop = wr_req_valid && wr_req_ready;
    wire fifo_room = (used_q < USED_W'(FIFO_DEPTH)) || pop;
    assign rd_rsp_ready = (state_q == RUN) && read_pending_q &&
        (drop_reads_q || (rd_rsp_valid && rd_rsp_error) || fifo_room);
    wire read_response = rd_rsp_valid && rd_rsp_ready;
    wire read_fault = read_response && rd_rsp_error;
    assign rd_req_valid = (state_q == RUN) && slot_valid_q &&
                          (!read_pending_q || read_response);
    assign rd_req_addr = slot_src_q;
    wire read_request = rd_req_valid && rd_req_ready;
    wire slot_room = !slot_valid_q || read_request;
    assign gen_ready = (state_q == RUN) && !allocation_done_q && slot_room &&
                       !read_fault && !write_fault;
    wire bad_pair = (gen_src > SRC_LAST) || (gen_dst > DST_LAST);
    wire bounds_fault = gen_valid && gen_ready && bad_pair;
    wire allocate = gen_valid && gen_ready && !bad_pair;
    wire push = read_response && !rd_rsp_error && !drop_reads_q && !write_fault;

    always_comb begin
        next_used = used_q;
        if (write_fault) next_used = 0;
        else case ({push, pop})
            2'b10: next_used = used_q + 1'b1;
            2'b01: next_used = used_q - 1'b1;
            default: next_used = used_q;
        endcase
    end
    always_ff @(posedge clk) begin
        if (push) begin
            fifo_data[tail_q] <= rd_rsp_data;
            fifo_dst[tail_q] <= pending_dst_q;
        end
    end

    tma_addr_gen #(.ADDR_W(ADDR_W), .COUNT_W(COUNT_W)) address_generator (
        .clk(clk), .rst(rst || (state_q == FINISH)),
        .desc_valid(desc_valid && desc_ready && descriptor_legal), .desc_ready(),
        .desc_src_base(desc_src_base), .desc_dst_base(desc_dst_base),
        .desc_rows(desc_rows), .desc_cols(desc_cols),
        .desc_src_row_stride(desc_src_row_stride), .desc_src_col_stride(desc_src_col_stride),
        .desc_dst_row_stride(desc_dst_row_stride), .desc_dst_col_stride(desc_dst_col_stride),
        .addr_valid(gen_valid), .addr_ready(gen_ready), .src_addr(gen_src), .dst_addr(gen_dst),
        .addr_last(gen_last), .busy(), .done(), .error()
    );

    always_ff @(posedge clk) begin
        if (rst) begin
            state_q <= IDLE;
            allocation_done_q <= 0;
            drop_reads_q <= 0;
            drop_writes_q <= 0;
            slot_valid_q <= 0;
            read_pending_q <= 0;
            write_pending_q <= 0;
            slot_src_q <= 0;
            slot_dst_q <= 0;
            pending_dst_q <= 0;
            head_q <= 0;
            tail_q <= 0;
            used_q <= 0;
            done <= 0;
            error <= 0;
            error_code <= OK;
            completed_elements <= 0;
            elapsed_cycles <= 0;
            read_wait_cycles <= 0;
            write_wait_cycles <= 0;
            peak_buffered <= 0;
            buffer_stall_cycles <= 0;
        end else begin
            done <= 0;
            error <= 0;
            if (busy) elapsed_cycles <= elapsed_cycles + 1'b1;
            case (state_q)
                IDLE: if (desc_valid) begin
                    allocation_done_q <= 0;
                    drop_reads_q <= 0;
                    drop_writes_q <= 0;
                    slot_valid_q <= 0;
                    read_pending_q <= 0;
                    write_pending_q <= 0;
                    head_q <= 0;
                    tail_q <= 0;
                    used_q <= 0;
                    completed_elements <= 0;
                    elapsed_cycles <= 0;
                    read_wait_cycles <= 0;
                    write_wait_cycles <= 0;
                    peak_buffered <= 0;
                    buffer_stall_cycles <= 0;
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
                        state_q <= RUN;
                    end
                end
                RUN: begin
                    if ((rd_req_valid && !rd_req_ready) || (rd_rsp_ready && !rd_rsp_valid))
                        read_wait_cycles <= read_wait_cycles + 1'b1;
                    if ((wr_req_valid && !wr_req_ready) || (wr_rsp_ready && !wr_rsp_valid))
                        write_wait_cycles <= write_wait_cycles + 1'b1;
                    if (rd_rsp_valid && read_pending_q && !rd_rsp_ready)
                        buffer_stall_cycles <= buffer_stall_cycles + 1'b1;
                    if (next_used > peak_buffered) peak_buffered <= next_used;
                    if (slot_room) begin
                        slot_valid_q <= allocate;
                        if (allocate) begin
                            slot_src_q <= gen_src;
                            slot_dst_q <= gen_dst;
                        end
                    end
                    if (allocate && gen_last) allocation_done_q <= 1;
                    if (read_request) pending_dst_q <= slot_dst_q;
                    read_pending_q <= (read_pending_q && !read_response) || read_request;
                    write_pending_q <= (write_pending_q && !write_response) || pop;
                    used_q <= next_used;
                    if (push) tail_q <= tail_q + 1'b1;
                    if (pop) head_q <= head_q + 1'b1;
                    if (write_response && !wr_rsp_error)
                        completed_elements <= completed_elements + 1'b1;

                    // Error priority follows descriptor order: writes precede
                    // failed later reads, which precede a later bounds failure.
                    if (write_fault) begin
                        error_code <= WRITE_ERROR;
                        allocation_done_q <= 1;
                        drop_reads_q <= 1;
                        drop_writes_q <= 1;
                        head_q <= 0;
                        tail_q <= 0;
                    end else if (read_fault) begin
                        if (error_code != WRITE_ERROR) error_code <= READ_ERROR;
                        allocation_done_q <= 1;
                        drop_reads_q <= 1;
                    end else if (bounds_fault) begin
                        if (error_code == OK) error_code <= BOUNDS;
                        allocation_done_q <= 1;
                    end
                    if (allocation_done_q && !slot_valid_q && !read_pending_q &&
                        (used_q == 0) && !write_pending_q)
                        state_q <= FINISH;
                end
                FINISH: begin
                    done <= 1;
                    error <= (error_code != OK);
                    state_q <= IDLE;
                end
                default: state_q <= IDLE;
            endcase
        end
    end
endmodule

`default_nettype wire
