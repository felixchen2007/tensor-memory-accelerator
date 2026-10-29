`default_nettype none

// Four logical word-addressed read lanes and one always-accepting write port.
// Optional XOR bank permutation; physical row remains word address / 4.
module tma_scratchpad #(
    parameter int unsigned ROW_W = 10,
    parameter bit SWIZZLE = 0,
    parameter int unsigned SWIZZLE_SHIFT = 5
) (
    input wire clk,
    input wire rst,
    input wire [3:0] rd_req_valid,
    output logic [3:0] rd_req_ready,
    input wire [3:0][ROW_W+1:0] rd_req_word_addr,
    output logic [3:0] rd_rsp_valid,
    input wire [3:0] rd_rsp_ready,
    output logic [3:0][15:0] rd_rsp_data,
    input wire wr_en,
    input wire [ROW_W+1:0] wr_word_addr,
    input wire [15:0] wr_data,
    output logic [31:0] bank_conflict_cycles,
    output logic [31:0] bank_conflict_requests
);
    logic [3:0] owner_valid_q;
    logic [3:0][1:0] owner_lane_q;
    logic [3:0] bank_free, lane_free, allocated;
    logic [3:0] bank_rd_en;
    logic [3:0][ROW_W-1:0] bank_rd_row;
    logic [3:0][1:0] grant_lane;
    wire [3:0][15:0] bank_ram_data;
    wire [3:0][15:0] bank_data;
    logic [3:0] forward_q;
    logic [3:0][15:0] forward_data_q;
    logic [2:0] blocked_requests;
    wire [3:0][1:0] read_bank;
    wire [1:0] write_bank = bank_for_word(wr_word_addr);

    function automatic logic [1:0] bank_for_word(input logic [ROW_W+1:0] address);
        if (SWIZZLE)
            bank_for_word = address[1:0] ^ 2'(address >> SWIZZLE_SHIFT);
        else
            bank_for_word = address[1:0];
    endfunction

    // Mixing only retained row bits makes (bank,row) a reversible mapping.
    generate
        if (SWIZZLE && (SWIZZLE_SHIFT < 2 || SWIZZLE_SHIFT > ROW_W)) begin : invalid_layout
            initial $fatal(1, "SWIZZLE_SHIFT must be in [2, ROW_W] when enabled");
        end
    endgenerate

    // A bank retains its read result until its owning lane accepts it. This
    // prevents another lane from overwriting a response held under backpressure.
    always_comb begin
        rd_req_ready = '0;
        rd_rsp_valid = '0;
        rd_rsp_data = '0;
        bank_free = '1;
        lane_free = '1;
        allocated = '0;
        bank_rd_en = '0;
        bank_rd_row = '0;
        grant_lane = '0;
        blocked_requests = '0;
        for (int bank = 0; bank < 4; bank++) begin
            if (owner_valid_q[bank]) begin
                rd_rsp_valid[owner_lane_q[bank]] = 1'b1;
                rd_rsp_data[owner_lane_q[bank]] = bank_data[bank];
                bank_free[bank] = rd_rsp_ready[owner_lane_q[bank]];
                lane_free[owner_lane_q[bank]] = rd_rsp_ready[owner_lane_q[bank]];
            end
        end
        // Fixed lane priority within each bank; fairness is not guaranteed.
        for (int lane = 0; lane < 4; lane++) begin
            if (rd_req_valid[lane] && lane_free[lane]) begin
                if (bank_free[read_bank[lane]] && !allocated[read_bank[lane]]) begin
                    rd_req_ready[lane] = 1'b1;
                    allocated[read_bank[lane]] = 1'b1;
                    bank_rd_en[read_bank[lane]] = 1'b1;
                    bank_rd_row[read_bank[lane]] = rd_req_word_addr[lane][ROW_W+1:2];
                    grant_lane[read_bank[lane]] = 2'(lane);
                end else begin
                    blocked_requests = blocked_requests + 1'b1;
                end
            end
        end
    end

    genvar bank_index;
    generate
    for (bank_index = 0; bank_index < 4; bank_index = bank_index + 1) begin : banks
        assign read_bank[bank_index] = bank_for_word(rd_req_word_addr[bank_index]);
        wire bank_wr_en = wr_en && !rst && (write_bank == 2'(bank_index));
        tma_ram_bank #(.ROW_W(ROW_W)) storage (
            .clk(clk), .rd_en(bank_rd_en[bank_index] && !rst),
            .rd_row(bank_rd_row[bank_index]), .rd_data(bank_ram_data[bank_index]),
            .wr_en(bank_wr_en), .wr_row(wr_word_addr[ROW_W+1:2]), .wr_data(wr_data)
        );
        assign bank_data[bank_index] = forward_q[bank_index] ? forward_data_q[bank_index] : bank_ram_data[bank_index];
        always_ff @(posedge clk) begin
            if (rst) begin
                owner_valid_q[bank_index] <= 1'b0;
                owner_lane_q[bank_index] <= '0;
                forward_q[bank_index] <= 1'b0;
                forward_data_q[bank_index] <= '0;
            end else if (bank_rd_en[bank_index]) begin
                owner_valid_q[bank_index] <= 1'b1;
                owner_lane_q[bank_index] <= grant_lane[bank_index];
                forward_q[bank_index] <= bank_wr_en &&
                    (bank_rd_row[bank_index] == wr_word_addr[ROW_W+1:2]);
                forward_data_q[bank_index] <= wr_data;
            end else if (bank_free[bank_index]) begin
                owner_valid_q[bank_index] <= 1'b0;
            end
        end
    end
    endgenerate

    always_ff @(posedge clk) begin
        if (rst) begin
            bank_conflict_cycles <= '0;
            bank_conflict_requests <= '0;
        end else if (blocked_requests != 0) begin
            bank_conflict_cycles <= bank_conflict_cycles + 1'b1;
            bank_conflict_requests <= bank_conflict_requests + 32'(blocked_requests);
        end
    end
endmodule

`default_nettype wire
