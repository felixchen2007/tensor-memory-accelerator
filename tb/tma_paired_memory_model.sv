`timescale 1ns/1ps
`default_nettype none

// Test-only memory. Transaction i receives the same service delays in either
// engine, independently of the cycle on which that engine issues it.
module tma_paired_memory_model (
    input wire clk, rst, load_image,
    input wire [15:0] source_image [0:4095], initial_image [0:4095],
    output logic [15:0] destination_mem [0:4095],
    input wire [31:0] timing_mode,
    input wire [31:0] timing_seed,
    input wire [31:0] fault_kind, fault_index,
    input wire hold_read_request, hold_read_response, hold_write_request, hold_write_response,
    input wire trace_enabled,
    input wire [31:0] legal_read_count, expected_write_count,
    input wire [31:0] legal_reads [0:4095], expected_writes [0:4095],
    input wire [15:0] expected_write_data [0:4095],
    input wire rd_req_valid,
    output wire rd_req_ready,
    input wire [31:0] rd_req_addr,
    output wire rd_rsp_valid,
    input wire rd_rsp_ready,
    output logic [15:0] rd_rsp_data,
    output logic rd_rsp_error,
    input wire wr_req_valid,
    output wire wr_req_ready,
    input wire [31:0] wr_req_addr,
    input wire [15:0] wr_req_data,
    output wire wr_rsp_valid,
    input wire wr_rsp_ready,
    output logic wr_rsp_error,
    output logic rd_pending, wr_pending,
    output integer reads_seen, writes_seen, successful_writes, overlap_cycles
);
    logic [15:0] source_mem [0:4095];
    logic [31:0] pending_write_address;
    logic [15:0] pending_write_data;
    integer rd_delay, wr_delay, rd_gap, wr_gap;
    function automatic logic [31:0] mix(input integer index, input logic [31:0] salt);
        logic [31:0] temp;
        begin
            temp = (32'(index) * 32'h9e3779b9) ^ timing_seed ^ salt;
            temp = temp ^ (temp << 13);
            temp = temp ^ (temp >> 17);
            mix = temp ^ (temp << 5);
        end
    endfunction
    function automatic integer gap(input integer index, input logic is_write);
        logic [31:0] value;
        begin
            value = mix(index, is_write ? 32'h79f19a37 : 32'h208451b3);
            gap = timing_mode == 2 ? int'(value[1:0]) : 0;
        end
    endfunction
    function automatic integer delay_cycles(input integer index, input logic is_write);
        logic [31:0] value;
        begin
            value = mix(index, is_write ? 32'hb71d9365 : 32'h4c8f2a19);
            delay_cycles = timing_mode == 2 ? int'(value[4:2]) :
                           (timing_mode == 1 ? 3 : 0);
        end
    endfunction
    assign rd_rsp_valid = rd_pending && (rd_delay == 0) && !hold_read_response;
    assign wr_rsp_valid = wr_pending && (wr_delay == 0) && !hold_write_response;
    assign rd_req_ready = !hold_read_request && (rd_gap == 0) &&
                         (!rd_pending || (rd_rsp_valid && rd_rsp_ready));
    assign wr_req_ready = !hold_write_request && (wr_gap == 0) &&
                         (!wr_pending || (wr_rsp_valid && wr_rsp_ready));
    wire rd_request = rd_req_valid && rd_req_ready;
    wire wr_request = wr_req_valid && wr_req_ready;
    wire rd_response = rd_rsp_valid && rd_rsp_ready;
    wire wr_response = wr_rsp_valid && wr_rsp_ready;

    always @(posedge clk) begin
        if (load_image) begin
            for (int index = 0; index < 4096; index++) begin
                source_mem[index] <= source_image[index];
                destination_mem[index] <= initial_image[index];
            end
        end
        if (rst || load_image) begin
            rd_pending <= 0;
            wr_pending <= 0;
            rd_delay <= 0;
            wr_delay <= 0;
            rd_gap <= gap(0, 0);
            wr_gap <= gap(0, 1);
            rd_rsp_data <= 0;
            rd_rsp_error <= 0;
            wr_rsp_error <= 0;
            reads_seen <= 0;
            writes_seen <= 0;
            successful_writes <= 0;
            overlap_cycles <= 0;
        end else begin
            rd_pending <= (rd_pending && !rd_response) || rd_request;
            wr_pending <= (wr_pending && !wr_response) || wr_request;
            if (rd_pending && wr_pending) overlap_cycles <= overlap_cycles + 1;
            if (rd_delay > 0) rd_delay <= rd_delay - 1;
            if (wr_delay > 0) wr_delay <= wr_delay - 1;
            if (rd_req_valid && (!rd_pending || rd_response) && rd_gap > 0)
                rd_gap <= rd_gap - 1;
            if (wr_req_valid && (!wr_pending || wr_response) && wr_gap > 0)
                wr_gap <= wr_gap - 1;
            if (rd_request) begin
                if (rd_req_addr[0] || rd_req_addr >= 8192)
                    $fatal(1, "Paired memory: illegal read address %h", rd_req_addr);
                if (trace_enabled && (reads_seen >= legal_read_count || rd_req_addr !== legal_reads[reads_seen]))
                    $fatal(1, "Paired memory: read trace mismatch index=%0d addr=%h", reads_seen, rd_req_addr);
                rd_rsp_data <= source_mem[rd_req_addr >> 1];
                rd_rsp_error <= fault_kind == 1 && reads_seen == fault_index;
                rd_delay <= delay_cycles(reads_seen, 0);
                rd_gap <= gap(reads_seen + 1, 0);
                reads_seen <= reads_seen + 1;
            end
            if (wr_request) begin
                if (wr_req_addr[0] || wr_req_addr >= 8192)
                    $fatal(1, "Paired memory: illegal write address %h", wr_req_addr);
                if (trace_enabled && (writes_seen >= expected_write_count ||
                    wr_req_addr !== expected_writes[writes_seen] ||
                    wr_req_data !== expected_write_data[writes_seen]))
                    $fatal(1, "Paired memory: write trace mismatch index=%0d addr=%h data=%h",
                        writes_seen, wr_req_addr, wr_req_data);
                pending_write_address <= wr_req_addr;
                pending_write_data <= wr_req_data;
                wr_rsp_error <= fault_kind == 2 && writes_seen == fault_index;
                wr_delay <= delay_cycles(writes_seen, 1);
                wr_gap <= gap(writes_seen + 1, 1);
                writes_seen <= writes_seen + 1;
            end
            if (wr_response && !wr_rsp_error) begin
                destination_mem[pending_write_address >> 1] <= pending_write_data;
                successful_writes <= successful_writes + 1;
            end
        end
    end
endmodule

`default_nettype wire
