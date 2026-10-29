`timescale 1ns/1ps
`default_nettype none

module tb_tma_swizzle_comparison;
    logic clk = 0;
    always #5 clk = !clk;
    logic rst = 1;
    logic [3:0][3:0] req_valid = '0;
    wire [3:0][3:0] req_ready, rsp_valid;
    logic [3:0][11:0] request_words = '0;
    logic [3:0] rsp_ready = 4'b1111;
    wire [3:0][3:0][15:0] rsp_data;
    logic wr_en = 0;
    logic [11:0] wr_word_addr = 0;
    logic [15:0] wr_data = 0;
    wire [3:0][31:0] conflict_cycles, conflict_requests;
    genvar variant;
    generate
        for (variant = 0; variant < 4; variant = variant + 1) begin : layouts
            localparam integer SHIFT = variant == 1 ? 3 : (variant == 2 ? 4 : 5);
            tma_scratchpad #(.SWIZZLE(variant != 0), .SWIZZLE_SHIFT(SHIFT)) memory (
                .clk(clk), .rst(rst), .rd_req_valid(req_valid[variant]), .rd_req_ready(req_ready[variant]),
                .rd_req_word_addr(request_words), .rd_rsp_valid(rsp_valid[variant]),
                .rd_rsp_ready(rsp_ready), .rd_rsp_data(rsp_data[variant]),
                .wr_en(wr_en), .wr_word_addr(wr_word_addr), .wr_data(wr_data),
                .bank_conflict_cycles(conflict_cycles[variant]),
                .bank_conflict_requests(conflict_requests[variant])
            );
        end
    endgenerate

    // Flat storage oracle is independent of every physical bank permutation.
    logic [15:0] flat_memory [0:4095];
    logic [3:0][3:0] pending = '0, stalled_q = '0;
    logic [3:0][3:0][15:0] expected_data, held_data;
    integer accepted_reads = 0, checked_responses = 0, checked_writes = 0;
    integer stalled_lane_cycles = 0, watchdog = 0;
    always @(posedge clk) begin
        watchdog = watchdog + 1;
        if (watchdog > 100000) $fatal(1, "Swizzle comparison watchdog");
        if (rst) begin
            pending = '0;
            stalled_q <= '0;
        end else begin
            for (int mode = 0; mode < 4; mode++) begin
                for (int lane = 0; lane < 4; lane++) begin
                    if (stalled_q[mode][lane] &&
                        (!rsp_valid[mode][lane] || rsp_data[mode][lane] !== held_data[mode][lane]))
                        $fatal(1, "Swizzled response changed while stalled mode=%0d lane=%0d", mode, lane);
                    if (rsp_valid[mode][lane] && !pending[mode][lane])
                        $fatal(1, "Unrequested swizzled response");
                    if (rsp_valid[mode][lane] && rsp_ready[lane]) begin
                        if (rsp_data[mode][lane] !== expected_data[mode][lane])
                            $fatal(1, "Bank mapping mismatch mode=%0d lane=%0d got=%h expected=%h",
                                mode, lane, rsp_data[mode][lane], expected_data[mode][lane]);
                        pending[mode][lane] = 0;
                        checked_responses = checked_responses + 1;
                    end
                    if (req_valid[mode][lane] && req_ready[mode][lane]) begin
                        if (pending[mode][lane]) $fatal(1, "Two pending requests on one lane");
                        pending[mode][lane] = 1;
                        expected_data[mode][lane] = (wr_en && wr_word_addr == request_words[lane]) ?
                            wr_data : flat_memory[request_words[lane]];
                        accepted_reads = accepted_reads + 1;
                    end
                    if (rsp_valid[mode][lane] && !rsp_ready[lane])
                        stalled_lane_cycles = stalled_lane_cycles + 1;
                end
                stalled_q[mode] <= rsp_valid[mode] & ~rsp_ready;
                held_data[mode] <= rsp_data[mode];
            end
            if (wr_en) begin
                flat_memory[wr_word_addr] = wr_data;
                checked_writes = checked_writes + 1;
            end
        end
    end

    function automatic logic [3:0] readiness(input integer batch, input integer cycle_index);
        logic [31:0] value;
        begin
            value = 32'(batch) * 32'h9e3779b9 ^ 32'(cycle_index) * 32'h45d9f3b ^ 32'h8a917c35;
            value = value ^ (value >> 13);
            value = value ^ (value << 7);
            readiness = cycle_index < 3 ? 4'b0000 :
                        (cycle_index % 5 == 0 ? 4'b1111 : value[3:0]);
        end
    endfunction

    integer vector_file, metrics_file, scanned, case_id = 0;
    integer expected_cycles [0:3];
    integer issue_cycles [0:3], completion_cycles [0:3];
    integer stalled_mode, write_flag, vector_write_word, vector_write_data, cycle_index;
    logic [3:0][3:0] sent, received, request_fire, response_fire;
    logic [3:0][31:0] saved_conflicts, saved_denied;
    integer improved_xor5 = 0, regressed_xor5 = 0, unchanged_xor5 = 0;
    string vector_path;
    initial begin
        repeat (2) @(posedge clk);
        @(negedge clk);
        rst = 0;
        for (int word_index = 0; word_index < 4096; word_index++) begin
            wr_en = 1;
            wr_word_addr = 12'(word_index);
            wr_data = (16'(word_index) * 16'd73) ^ 16'ha55a;
            @(posedge clk);
            @(negedge clk);
        end
        wr_en = 0;
        if (!$value$plusargs("SWIZZLE_VECTORS=%s", vector_path)) vector_path = "swizzle_vectors.txt";
        vector_file = $fopen(vector_path, "r");
        metrics_file = $fopen("swizzle_metrics.csv", "w");
        if (vector_file == 0 || metrics_file == 0) $fatal(1, "Swizzle files missing");
        $fdisplay(metrics_file, "id,variant,issue_cycles,completion_cycles,conflict_cycles,denied_requests,stalled");
        while (!$feof(vector_file)) begin
            @(negedge clk);
            scanned = $fscanf(vector_file, "%h %h %h %h %h %h %h %h %h %h %h %h\n",
                request_words[0], request_words[1], request_words[2], request_words[3],
                expected_cycles[0], expected_cycles[1], expected_cycles[2], expected_cycles[3],
                stalled_mode, write_flag, vector_write_word, vector_write_data);
            if (scanned == -1) break;
            if (scanned != 12) $fatal(1, "Malformed swizzle vector %0d", case_id);
            if (write_flag != 0) begin
                wr_en = 1;
                wr_word_addr = 12'(vector_write_word);
                wr_data = 16'(vector_write_data);
                @(posedge clk);
                @(negedge clk);
                wr_en = 0;
            end
            saved_conflicts = conflict_cycles;
            saved_denied = conflict_requests;
            sent = '0;
            received = '0;
            for (int mode = 0; mode < 4; mode++) begin
                issue_cycles[mode] = 0;
                completion_cycles[mode] = 0;
            end
            cycle_index = 0;
            req_valid = '1;
            rsp_ready = stalled_mode != 0 ? readiness(case_id, cycle_index) : 4'b1111;
            while (received != 16'hffff) begin
                @(posedge clk);
                for (int mode = 0; mode < 4; mode++) begin
                    if (sent[mode] != 4'b1111) issue_cycles[mode] = issue_cycles[mode] + 1;
                    if (received[mode] != 4'b1111) completion_cycles[mode] = completion_cycles[mode] + 1;
                    request_fire[mode] = req_valid[mode] & req_ready[mode];
                    response_fire[mode] = rsp_valid[mode] & rsp_ready;
                    sent[mode] = sent[mode] | request_fire[mode];
                    received[mode] = received[mode] | response_fire[mode];
                end
                #1;
                @(negedge clk);
                for (int mode = 0; mode < 4; mode++) req_valid[mode] = req_valid[mode] & ~request_fire[mode];
                cycle_index = cycle_index + 1;
                rsp_ready = stalled_mode != 0 ? readiness(case_id, cycle_index) : 4'b1111;
                if (cycle_index > 100) $fatal(1, "Swizzle packet failed to drain case=%0d", case_id);
            end
            for (int mode = 0; mode < 4; mode++) begin
                if (stalled_mode == 0 && (issue_cycles[mode] != expected_cycles[mode] ||
                    completion_cycles[mode] != expected_cycles[mode] + 1))
                    $fatal(1, "Swizzle issue/latency mismatch case=%0d mode=%0d issue=%0d expected=%0d completion=%0d",
                        case_id, mode, issue_cycles[mode], expected_cycles[mode], completion_cycles[mode]);
                $fdisplay(metrics_file, "%0d,%0d,%0d,%0d,%0d,%0d,%0d", case_id, mode,
                    issue_cycles[mode], completion_cycles[mode], conflict_cycles[mode] - saved_conflicts[mode],
                    conflict_requests[mode] - saved_denied[mode], stalled_mode);
            end
            if (stalled_mode == 0) begin
                if (issue_cycles[3] < issue_cycles[0]) improved_xor5 = improved_xor5 + 1;
                else if (issue_cycles[3] > issue_cycles[0]) regressed_xor5 = regressed_xor5 + 1;
                else unchanged_xor5 = unchanged_xor5 + 1;
            end
            if (pending != 0) $fatal(1, "Pending responses after swizzle packet");
            req_valid = 0;
            rsp_ready = 4'b1111;
            case_id = case_id + 1;
        end
        $fclose(vector_file);
        $fclose(metrics_file);
        if (accepted_reads != checked_responses || checked_responses != case_id * 16 ||
            stalled_lane_cycles == 0 || improved_xor5 == 0 || regressed_xor5 == 0)
            $fatal(1, "Swizzle conservation or comparison coverage missing");
        $display("TMA_SWIZZLE_COMPARISON_PASS batches=%0d responses=%0d writes=%0d variants=4 xor5_improved=%0d xor5_regressed=%0d xor5_unchanged=%0d stalled_lane_cycles=%0d alias_checks_per_variant=8192",
            case_id, checked_responses, checked_writes, improved_xor5, regressed_xor5, unchanged_xor5, stalled_lane_cycles);
        $finish;
    end
endmodule

`default_nettype wire
