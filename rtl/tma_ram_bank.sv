`default_nettype none

// One synchronous read port and one write port. Collision forwarding lives in
// the parent, so primitive read-during-write data is deliberately unspecified.
module tma_ram_bank #(
    parameter int unsigned ROW_W = 10
) (
    input wire clk,
    input wire rd_en,
    input wire [ROW_W-1:0] rd_row,
    output logic [15:0] rd_data,
    input wire wr_en,
    input wire [ROW_W-1:0] wr_row,
    input wire [15:0] wr_data
);
    (* ramstyle = "M9K, no_rw_check" *) logic [15:0] memory [0:(1 << ROW_W)-1];
    always_ff @(posedge clk) begin
        if (wr_en) memory[wr_row] <= wr_data;
        if (rd_en) rd_data <= memory[rd_row];
    end
endmodule

`default_nettype wire
