`timescale 1ns/1ps
`default_nettype none

module tb_tma_scratchpad #(
    parameter bit SWIZZLE = 0,
    parameter int unsigned SWIZZLE_SHIFT = 5
);
    logic clk = 0;
    always #5 clk = !clk;
    logic rst = 1;
    logic [3:0] rd_req_valid = 0, rd_rsp_ready = 0;
    wire [3:0] rd_req_ready, rd_rsp_valid;
    logic [3:0][11:0] rd_req_word_addr = '0;
    wire [3:0][15:0] rd_rsp_data;
    logic wr_en = 0;
    logic [11:0] wr_word_addr = 0;
    logic [15:0] wr_data = 0;
    wire [31:0] bank_conflict_cycles, bank_conflict_requests;
    localparam integer COLUMN_CYCLES = SWIZZLE && SWIZZLE_SHIFT == 5 ? 1 :
        (SWIZZLE && (SWIZZLE_SHIFT == 4 || SWIZZLE_SHIFT == 6) ? 2 : 4);
    localparam integer COLUMN_DENIED = COLUMN_CYCLES == 4 ? 6 : (COLUMN_CYCLES == 2 ? 2 : 0);
    tma_scratchpad #(.SWIZZLE(SWIZZLE), .SWIZZLE_SHIFT(SWIZZLE_SHIFT)) dut (.*);

    // Flat memory oracle: it has no bank decoding or arbiter implementation.
    logic [15:0] reference_mem [0:4095];
    logic [3:0] pending = 0, fired_q = 0, stalled_rsp_q = 0;
    logic [3:0][15:0] expected_data, held_rsp_data;
    integer accepted_reads = 0, checked_responses = 0, checked_writes = 0;
    integer stalled_response_cycles = 0, cycles = 0;
    logic [31:0] rng = 32'hb18a24e9;
    function automatic logic [31:0] next_random(input logic [31:0] value);
        logic [31:0] temp;
        begin
            temp = value ^ (value << 13);
            temp = temp ^ (temp >> 17);
            next_random = temp ^ (temp << 5);
        end
    endfunction

    always @(posedge clk) begin
        cycles = cycles + 1;
        if (cycles > 20000) $fatal(1, "Scratchpad watchdog");
        if (rst) begin
            pending = 0;
            fired_q <= 0;
            stalled_rsp_q <= 0;
        end else begin
            fired_q <= rd_req_valid & rd_req_ready;
            for (int lane = 0; lane < 4; lane++) begin
                if (stalled_rsp_q[lane] &&
                    (!rd_rsp_valid[lane] || rd_rsp_data[lane] !== held_rsp_data[lane]))
                    $fatal(1, "Response changed under backpressure, lane %0d", lane);
                if (rd_rsp_valid[lane] && !pending[lane])
                    $fatal(1, "Unrequested response, lane %0d", lane);
                if (rd_rsp_valid[lane] && rd_rsp_ready[lane]) begin
                    if (rd_rsp_data[lane] !== expected_data[lane])
                        $fatal(1, "Scratchpad data mismatch lane=%0d got=%h expected=%h",
                               lane, rd_rsp_data[lane], expected_data[lane]);
                    pending[lane] = 0;
                    checked_responses = checked_responses + 1;
                end
                if (rd_req_valid[lane] && rd_req_ready[lane]) begin
                    if (pending[lane]) $fatal(1, "Lane accepted a second outstanding read");
                    pending[lane] = 1;
                    expected_data[lane] = (wr_en && wr_word_addr == rd_req_word_addr[lane]) ?
                        wr_data : reference_mem[rd_req_word_addr[lane]];
                    accepted_reads = accepted_reads + 1;
                end
                if (rd_rsp_valid[lane] && !rd_rsp_ready[lane])
                    stalled_response_cycles = stalled_response_cycles + 1;
            end
            stalled_rsp_q <= rd_rsp_valid & ~rd_rsp_ready;
            held_rsp_data <= rd_rsp_data;
            if (wr_en) begin
                reference_mem[wr_word_addr] = wr_data;
                checked_writes = checked_writes + 1;
            end
        end
    end

    task automatic read_batch(input logic [3:0][11:0] addresses,
                              input logic random_stalls,
                              output integer service_cycles);
        logic [3:0] sent, received, request_fire, response_fire;
        begin
            sent = 0;
            received = 0;
            service_cycles = 0;
            @(negedge clk);
            rd_req_valid = 4'b1111;
            rd_req_word_addr = addresses;
            rd_rsp_ready = random_stalls ? 4'b0000 : 4'b1111;
            while (sent != 4'b1111 || received != 4'b1111) begin
                @(posedge clk);
                request_fire = rd_req_valid & rd_req_ready;
                response_fire = rd_rsp_valid & rd_rsp_ready;
                if (request_fire != 0) service_cycles = service_cycles + 1;
                sent = sent | request_fire;
                received = received | response_fire;
                #1;
                @(negedge clk);
                rd_req_valid = rd_req_valid & ~request_fire;
                rng = next_random(rng);
                rd_rsp_ready = random_stalls ? rng[3:0] : 4'b1111;
            end
            rd_req_valid = 0;
            rd_rsp_ready = 4'b1111;
        end
    endtask

    integer service, saved_cycles, saved_requests, saved_reads;
    integer row_service_cycles, column_service_cycles;
    initial begin
        repeat (2) @(posedge clk);
        @(negedge clk);
        rst = 0;
        for (int word_index = 0; word_index < 4096; word_index++) begin
            wr_en = 1;
            wr_word_addr = 12'(word_index);
            wr_data = 16'(word_index) ^ 16'ha55a;
            @(posedge clk);
            @(negedge clk);
        end
        wr_en = 0;

        saved_cycles = int'(bank_conflict_cycles);
        read_batch({12'd3, 12'd2, 12'd1, 12'd0}, 0, row_service_cycles);
        if (row_service_cycles != 1 || bank_conflict_cycles != saved_cycles)
            $fatal(1, "Adjacent row values did not read in parallel");
        saved_cycles = int'(bank_conflict_cycles);
        saved_requests = int'(bank_conflict_requests);
        read_batch({12'd96, 12'd64, 12'd32, 12'd0}, 0, column_service_cycles);
        if (column_service_cycles != COLUMN_CYCLES ||
            bank_conflict_cycles != saved_cycles + COLUMN_CYCLES - 1 ||
            bank_conflict_requests != saved_requests + COLUMN_DENIED)
            $fatal(1, "Column bank conflict accounting mismatch");
        read_batch({12'd4095, 12'd4094, 12'd4093, 12'd4092}, 1, service);
        read_batch({12'd2049, 12'd2048, 12'd2047, 12'd2046}, 1, service);

        // Same-edge read/write returns the new word. Later writes must not
        // change that response while it is held by a stalled consumer.
        @(negedge clk);
        rd_req_valid = 1;
        rd_req_word_addr[0] = 99;
        rd_rsp_ready = 0;
        wr_en = 1;
        wr_word_addr = 99;
        wr_data = 16'hcafe;
        @(posedge clk);
        #1;
        @(negedge clk);
        rd_req_valid = 0;
        wr_data = 16'hbeef;
        repeat (3) @(posedge clk);
        #1;
        if (rd_rsp_data[0] !== 16'hcafe) $fatal(1, "Collision forwarding/snapshot failed");
        @(negedge clk);
        wr_en = 0;
        rd_rsp_ready = 4'b1111;
        @(posedge clk);
        #1;

        // Reset cancels responses, preserves RAM, and suppresses a reset-edge write.
        @(negedge clk);
        rd_req_valid = 4'b1111;
        rd_req_word_addr = {12'd3, 12'd2, 12'd1, 12'd0};
        rd_rsp_ready = 0;
        @(posedge clk);
        #1;
        if (rd_rsp_valid != 4'b1111) $fatal(1, "Reset test did not create pending reads");
        @(negedge clk);
        rst = 1;
        wr_en = 1;
        wr_word_addr = 99;
        wr_data = 16'h1234;
        @(posedge clk);
        #1;
        if (rd_rsp_valid != 0 || bank_conflict_cycles != 0 || bank_conflict_requests != 0)
            $fatal(1, "Scratchpad reset did not clear protocol state");
        @(negedge clk);
        rst = 0;
        wr_en = 0;
        rd_req_valid = 0;
        rd_rsp_ready = 4'b1111;
        read_batch({12'd102, 12'd101, 12'd100, 12'd99}, 0, service);

        // Sustained four-bank stream: 256 requests in 64 request cycles.
        saved_reads = accepted_reads;
        for (int beat = 0; beat < 64; beat++) begin
            @(negedge clk);
            rd_req_valid = 4'b1111;
            rd_rsp_ready = 4'b1111;
            for (int lane = 0; lane < 4; lane++)
                rd_req_word_addr[lane] = 12'(4 * beat + lane);
            @(posedge clk);
            if (rd_req_ready != 4'b1111) $fatal(1, "Four-bank stream lost throughput");
            #1;
        end
        @(negedge clk);
        rd_req_valid = 0;
        @(posedge clk);
        #1;
        if (accepted_reads - saved_reads != 256) $fatal(1, "Four-bank stream count mismatch");

        for (int beat = 0; beat < 400; beat++) begin
            @(negedge clk);
            rng = next_random(rng);
            rd_rsp_ready = rng[3:0];
            wr_en = rng[4];
            wr_word_addr = rng[16:5];
            wr_data = rng[31:16];
            for (int lane = 0; lane < 4; lane++) begin
                if (!rd_req_valid[lane] || fired_q[lane]) begin
                    rng = next_random(rng);
                    rd_req_valid[lane] = rng[0];
                    rd_req_word_addr[lane] = rng[12:1];
                end
            end
        end
        @(negedge clk);
        wr_en = 0;
        rd_rsp_ready = 4'b1111;
        rd_req_valid = rd_req_valid & ~fired_q;
        while (rd_req_valid != 0 || rd_rsp_valid != 0) begin
            @(posedge clk);
            #1;
            @(negedge clk);
            rd_req_valid = rd_req_valid & ~fired_q;
        end
        if (pending != 0 || stalled_response_cycles == 0)
            $fatal(1, "Scratchpad failed to drain/exercise backpressure");
        // Four accepted reads were deliberately canceled by the reset scenario.
        if (accepted_reads != checked_responses + 4) $fatal(1, "Read conservation mismatch");
        $display("TMA_SCRATCHPAD_PASS swizzle=%0d shift=%0d reads=%0d responses=%0d writes=%0d canceled=4 row_service_cycles=%0d column_service_cycles=%0d stream_reads=256 stream_request_cycles=64 stalled_response_cycles=%0d bank_conflict_cycles=%0d bank_conflict_requests=%0d",
            SWIZZLE, SWIZZLE_SHIFT, accepted_reads, checked_responses, checked_writes, row_service_cycles, column_service_cycles,
            stalled_response_cycles, bank_conflict_cycles, bank_conflict_requests);
        $finish;
    end
endmodule

`default_nettype wire
