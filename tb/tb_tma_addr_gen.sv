`timescale 1ns/1ps
`default_nettype none

module tb_tma_addr_gen;
    logic clk = 1'b0;
    always #5 clk = !clk;

    logic rst = 1'b1;
    logic desc_valid = 1'b0;
    wire desc_ready;
    logic [31:0] desc_src_base = '0, desc_dst_base = '0;
    logic [15:0] desc_rows = '0, desc_cols = '0;
    logic [31:0] desc_src_row_stride = '0, desc_src_col_stride = '0;
    logic [31:0] desc_dst_row_stride = '0, desc_dst_col_stride = '0;
    wire addr_valid;
    logic addr_ready = 1'b0;
    wire [31:0] src_addr, dst_addr;
    wire addr_last, busy, done, error;

    tma_addr_gen dut (.*);

    logic was_stalled = 1'b0;
    logic [31:0] held_src, held_dst;
    logic held_last;
    integer cycles = 0;
    integer stalled_cycles = 0;

    // Check protocol independently of the file-driven data scoreboard.
    always @(posedge clk) begin
        cycles <= cycles + 1;
        if (cycles > 2000000)
            $fatal(1, "Watchdog: possible deadlock");
        if (rst) begin
            was_stalled <= 1'b0;
        end else begin
            if (desc_ready !== !busy || addr_valid !== busy)
                $fatal(1, "Ready/busy/valid contract violated");
            if (was_stalled &&
                (addr_valid !== 1'b1 || src_addr !== held_src ||
                 dst_addr !== held_dst || addr_last !== held_last))
                $fatal(1, "Output changed during backpressure");
            was_stalled <= addr_valid && !addr_ready;
            held_src <= src_addr;
            held_dst <= dst_addr;
            held_last <= addr_last;
            if (addr_valid && !addr_ready)
                stalled_cycles <= stalled_cycles + 1;
        end
    end

    function automatic logic [31:0] next_random(input logic [31:0] value);
        logic [31:0] temp;
        begin
            temp = value ^ (value << 13);
            temp = temp ^ (temp >> 17);
            next_random = temp ^ (temp << 5);
        end
    endfunction

    task automatic check_reset_cancellation;
        begin
            repeat (2) @(posedge clk);
            @(negedge clk);
            rst = 1'b0;
            desc_valid = 1'b1;
            desc_src_base = 32'h1000;
            desc_dst_base = 32'h2000;
            desc_rows = 2;
            desc_cols = 3;
            desc_src_row_stride = 6;
            desc_src_col_stride = 2;
            desc_dst_row_stride = 6;
            desc_dst_col_stride = 2;
            @(posedge clk);
            #1;
            if (addr_valid !== 1'b1 || src_addr !== 32'h1000 ||
                dst_addr !== 32'h2000 || done !== 1'b0 || error !== 1'b0)
                $fatal(1, "First address after descriptor acceptance is incorrect");
            @(negedge clk);
            desc_valid = 1'b0;
            repeat (3) begin
                @(posedge clk);
                #1;
                if (addr_valid !== 1'b1 || done !== 1'b0)
                    $fatal(1, "Stalled descriptor completed prematurely");
            end
            @(negedge clk);
            rst = 1'b1;
            // Reset wins over both a possible output handshake and a new input.
            desc_valid = 1'b1;
            desc_rows = 0;
            addr_ready = 1'b1;
            @(posedge clk);
            #1;
            if (addr_valid !== 1'b0 || busy !== 1'b0 || desc_ready !== 1'b1 ||
                done !== 1'b0 || error !== 1'b0)
                $fatal(1, "Reset failed to cancel the active descriptor");
            @(negedge clk);
            rst = 1'b0;
            desc_valid = 1'b0;
            addr_ready = 1'b0;
            @(posedge clk);
            #1;
            if (addr_valid !== 1'b0 || done !== 1'b0 || error !== 1'b0)
                $fatal(1, "Canceled descriptor produced a later output/completion");
        end
    endtask

    integer vector_file;
    integer scanned;
    integer case_count = 0;
    integer pair_count = 0;
    integer empty_count = 0;
    integer expected_count;
    integer expected_last;
    integer beat, attempts;
    logic [31:0] expected_src, expected_dst;
    logic [31:0] prng = 32'h6d2b79f5;
    logic fired;
    string vector_path;

    initial begin
        check_reset_cancellation();
        if (!$value$plusargs("VECTORS=%s", vector_path))
            vector_path = "vectors.txt";
        vector_file = $fopen(vector_path, "r");
        if (vector_file == 0)
            $fatal(1, "Unable to open vectors: %s", vector_path);

        while (!$feof(vector_file)) begin
            @(negedge clk);
            desc_valid = 1'b0;
            addr_ready = 1'b0;
            scanned = $fscanf(vector_file, "%h %h %h %h %h %h %h %h %h\n",
                              desc_src_base, desc_dst_base, desc_rows, desc_cols,
                              desc_src_row_stride, desc_src_col_stride,
                              desc_dst_row_stride, desc_dst_col_stride,
                              expected_count);
            if (scanned == -1)
                break;
            if (scanned != 9)
                $fatal(1, "Malformed descriptor header at case %0d", case_count);
            if (desc_ready !== 1'b1)
                $fatal(1, "Not ready for case %0d", case_count);
            desc_valid = 1'b1;
            @(posedge clk);
            #1;
            case_count = case_count + 1;

            if (expected_count == 0) begin
                empty_count = empty_count + 1;
                if (done !== 1'b1 || error !== 1'b1 || busy !== 1'b0 ||
                    addr_valid !== 1'b0)
                    $fatal(1, "Empty descriptor handling failed, case %0d", case_count);
            end else begin
                if (addr_valid !== 1'b1 || done !== 1'b0 || error !== 1'b0)
                    $fatal(1, "Initial valid/status failed, case %0d", case_count);
                for (beat = 0; beat < expected_count; beat = beat + 1) begin
                    scanned = $fscanf(vector_file, "%h %h %h\n",
                                      expected_src, expected_dst, expected_last);
                    if (scanned != 3)
                        $fatal(1, "Missing expectation at case %0d beat %0d", case_count, beat);
                    fired = 1'b0;
                    attempts = 0;
                    while (!fired) begin
                        @(negedge clk);
                        prng = next_random(prng);
                        // Force stalls at the first and final pair as well as
                        // random stalls throughout the descriptor.
                        addr_ready = ((beat == 0 || expected_last == 1) && attempts < 2)
                                     ? 1'b0 : (prng[1:0] != 2'b00);
                        attempts = attempts + 1;
                        // A conflicting descriptor must never replace active state.
                        desc_valid = 1'b1;
                        desc_src_base = 32'hdeadbeef;
                        desc_dst_base = 32'hbad0cafe;
                        desc_rows = 0;
                        desc_cols = 0;
                        desc_src_row_stride = '1;
                        desc_src_col_stride = '1;
                        desc_dst_row_stride = '1;
                        desc_dst_col_stride = '1;
                        @(posedge clk);
                        if (busy !== 1'b1 || desc_ready !== 1'b0 ||
                            done !== 1'b0 || error !== 1'b0)
                            $fatal(1, "Active descriptor/status lost, case %0d", case_count);
                        fired = addr_valid && addr_ready;
                        if (fired) begin
                            if (src_addr !== expected_src || dst_addr !== expected_dst ||
                                addr_last !== (expected_last == 1))
                                $fatal(1, "Mismatch case=%0d beat=%0d got=%h,%h,%b expected=%h,%h,%0d",
                                       case_count, beat, src_addr, dst_addr, addr_last,
                                       expected_src, expected_dst, expected_last);
                            pair_count = pair_count + 1;
                        end
                        #1;
                        if (fired && expected_last == 1) begin
                            if (done !== 1'b1 || error !== 1'b0 || busy !== 1'b0 ||
                                addr_valid !== 1'b0 || desc_ready !== 1'b1)
                                $fatal(1, "Final address completion failed, case %0d", case_count);
                        end else if (done !== 1'b0 || error !== 1'b0) begin
                            $fatal(1, "Premature completion, case %0d", case_count);
                        end
                    end
                end
            end

            @(negedge clk);
            desc_valid = 1'b0;
            addr_ready = 1'b0;
            @(posedge clk);
            #1;
            if (done !== 1'b0 || error !== 1'b0 || addr_valid !== 1'b0)
                $fatal(1, "Completion pulse did not clear, case %0d", case_count);
        end

        $fclose(vector_file);
        if (case_count == 0 || pair_count == 0 || stalled_cycles == 0)
            $fatal(1, "Regression did not exercise meaningful traffic");
        $display("TMA_ADDR_GEN_PASS descriptors=%0d pairs=%0d empty=%0d stalled_cycles=%0d cycles=%0d reset_cancellation=pass",
                 case_count, pair_count, empty_count, stalled_cycles, cycles);
        $finish;
    end
endmodule

`default_nettype wire
