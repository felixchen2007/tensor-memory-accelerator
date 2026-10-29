`default_nettype none

// Byte-addressed ready/valid adapter for the copy engine. Lanes 1-3 are unused
// here; the standalone scratchpad exposes them to a future parallel consumer.
module tma_scratchpad_endpoint #(
    parameter int unsigned ROW_W = 10,
    parameter bit SWIZZLE = 0,
    parameter int unsigned SWIZZLE_SHIFT = 5
) (
    input wire clk,
    input wire rst,
    input wire rd_req_valid,
    output wire rd_req_ready,
    input wire [31:0] rd_req_addr,
    output wire rd_rsp_valid,
    input wire rd_rsp_ready,
    output wire [15:0] rd_rsp_data,
    output wire rd_rsp_error,
    input wire wr_req_valid,
    output wire wr_req_ready,
    input wire [31:0] wr_req_addr,
    input wire [15:0] wr_req_data,
    output logic wr_rsp_valid,
    input wire wr_rsp_ready,
    output logic wr_rsp_error,
    output wire [31:0] bank_conflict_cycles
);
    localparam logic [31:0] BYTES = 32'(1 << (ROW_W + 3));
    wire rd_legal = !rd_req_addr[0] && (rd_req_addr < BYTES);
    wire wr_legal = !wr_req_addr[0] && (wr_req_addr < BYTES);
    logic rd_error_q;
    wire [3:0] lane_req_ready, lane_rsp_valid;
    wire [3:0][15:0] lane_rsp_data;
    wire rd_slot_free = !rd_rsp_valid || rd_rsp_ready;
    wire [3:0] lane_req_valid = {3'b000, rd_req_valid && rd_legal && rd_slot_free};
    wire [3:0][ROW_W+1:0] lane_req_addr = {
        {(3 * (ROW_W + 2)){1'b0}}, rd_req_addr[ROW_W+2:1]
    };
    assign rd_req_ready = rd_slot_free && (!rd_legal || lane_req_ready[0]);
    assign rd_rsp_valid = rd_error_q || lane_rsp_valid[0];
    assign rd_rsp_error = rd_error_q;
    assign rd_rsp_data = rd_error_q ? 16'b0 : lane_rsp_data[0];
    assign wr_req_ready = !wr_rsp_valid || wr_rsp_ready;

    tma_scratchpad #(.ROW_W(ROW_W), .SWIZZLE(SWIZZLE), .SWIZZLE_SHIFT(SWIZZLE_SHIFT)) memory (
        .clk(clk), .rst(rst),
        .rd_req_valid(lane_req_valid), .rd_req_ready(lane_req_ready),
        .rd_req_word_addr(lane_req_addr), .rd_rsp_valid(lane_rsp_valid),
        .rd_rsp_ready({3'b000, rd_rsp_ready}), .rd_rsp_data(lane_rsp_data),
        .wr_en(wr_req_valid && wr_req_ready && wr_legal),
        .wr_word_addr(wr_req_addr[ROW_W+2:1]), .wr_data(wr_req_data),
        .bank_conflict_cycles(bank_conflict_cycles), .bank_conflict_requests()
    );

    always_ff @(posedge clk) begin
        if (rst) begin
            rd_error_q <= 1'b0;
            wr_rsp_valid <= 1'b0;
            wr_rsp_error <= 1'b0;
        end else begin
            if (rd_slot_free)
                rd_error_q <= rd_req_valid && rd_req_ready && !rd_legal;
            if (wr_req_ready) begin
                wr_rsp_valid <= wr_req_valid;
                wr_rsp_error <= wr_req_valid && !wr_legal;
            end
        end
    end
endmodule

`default_nettype wire
