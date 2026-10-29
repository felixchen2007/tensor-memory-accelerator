`timescale 1ns/1ps
`default_nettype none

module tb_tma_copy_engine;
    localparam integer WORDS = 4096;
    logic clk = 1'b0;
    always #5 clk = !clk;
    logic rst = 1'b1, desc_valid = 1'b0;
    wire desc_ready;
    logic [31:0] desc_src_base = '0, desc_dst_base = '0;
    logic [15:0] desc_rows = '0, desc_cols = '0;
    logic [31:0] desc_src_row_stride = '0, desc_src_col_stride = '0;
    logic [31:0] desc_dst_row_stride = '0, desc_dst_col_stride = '0;
    wire rd_req_valid, rd_req_ready, rd_rsp_valid, rd_rsp_ready;
    wire [31:0] rd_req_addr;
    logic [15:0] rd_rsp_data;
    logic rd_rsp_error;
    wire wr_req_valid, wr_req_ready, wr_rsp_valid, wr_rsp_ready;
    wire [31:0] wr_req_addr;
    wire [15:0] wr_req_data;
    logic wr_rsp_error;
    wire busy, done, error;
    wire [2:0] error_code;
    wire [31:0] completed_elements;
    wire [63:0] elapsed_cycles, read_wait_cycles, write_wait_cycles;
    tma_copy_engine dut (.*);

    logic [15:0] source_mem [0:WORDS-1];
    logic [15:0] destination_mem [0:WORDS-1];
    logic [15:0] golden_mem [0:WORDS-1];
    logic [31:0] expected_reads [0:WORDS-1];
    logic [31:0] expected_writes [0:WORDS-1];
    logic [15:0] expected_write_data [0:WORDS-1];
    integer timing_mode = 0, fault_kind = 0, fault_index = 0;
    integer expected_error, expected_completed, expected_read_count, expected_write_count;
    integer expected_cycles;
    logic trace_enabled = 1'b0;
    logic hold_rd_req = 0, hold_rd_rsp = 0, hold_wr_req = 0, hold_wr_rsp = 0;
    logic rd_pending = 0, wr_pending = 0;
    integer rd_delay = 0, wr_delay = 0;
    logic [31:0] pending_wr_addr;
    logic [15:0] pending_wr_data;
    integer reads_seen = 0, writes_seen = 0, successful_writes = 0;
    longint unsigned bench_cycles = 0, bench_read_wait = 0, bench_write_wait = 0;
    logic [31:0] prng = 32'h91e10da5;
    integer watchdog = 0;

    function automatic logic [31:0] next_random(input logic [31:0] value);
        logic [31:0] temp;
        begin
            temp = value ^ (value << 13);
            temp = temp ^ (temp >> 17);
            next_random = temp ^ (temp << 5);
        end
    endfunction
    always @(negedge clk) prng <= next_random(prng);

    assign rd_req_ready = !rd_pending && !hold_rd_req &&
                          ((timing_mode == 0) || (prng[1:0] != 0));
    assign wr_req_ready = !wr_pending && !hold_wr_req &&
                          ((timing_mode == 0) || (prng[3:2] != 0));
    assign rd_rsp_valid = rd_pending && (rd_delay == 0) && !hold_rd_rsp;
    assign wr_rsp_valid = wr_pending && (wr_delay == 0) && !hold_wr_rsp;

    // Behavioral endpoints: accept requests, then independently delay responses.
    // Writes commit on successful response handshake in this particular model.
    always @(posedge clk) begin
        watchdog <= watchdog + 1;
        if (watchdog > 2000000) $fatal(1, "Copy regression watchdog expired");
        if (rst) begin
            rd_pending <= 0;
            wr_pending <= 0;
            rd_delay <= 0;
            wr_delay <= 0;
            rd_rsp_data <= 0;
            rd_rsp_error <= 0;
            wr_rsp_error <= 0;
            reads_seen <= 0;
            writes_seen <= 0;
            successful_writes <= 0;
            bench_cycles <= 0;
            bench_read_wait <= 0;
            bench_write_wait <= 0;
        end else begin
            if (desc_valid && desc_ready) begin
                reads_seen <= 0;
                writes_seen <= 0;
                successful_writes <= 0;
                bench_cycles <= 0;
                bench_read_wait <= 0;
                bench_write_wait <= 0;
            end else if (busy) begin
                bench_cycles <= bench_cycles + 1;
                if ((rd_req_valid && !rd_req_ready) || (rd_rsp_ready && !rd_rsp_valid))
                    bench_read_wait <= bench_read_wait + 1;
                if ((wr_req_valid && !wr_req_ready) || (wr_rsp_ready && !wr_rsp_valid))
                    bench_write_wait <= bench_write_wait + 1;
            end
            if (rd_pending && rd_delay > 0) rd_delay <= rd_delay - 1;
            if (wr_pending && wr_delay > 0) wr_delay <= wr_delay - 1;
            if (rd_pending && wr_pending)
                $fatal(1, "More than one outstanding memory transaction");
            if (done && (rd_pending || wr_pending))
                $fatal(1, "Completion preceded a memory response");
            if (error && !done) $fatal(1, "Error pulse without completion");

            if (rd_req_valid && rd_req_ready) begin
                if (rd_req_addr[0] || rd_req_addr >= 2 * WORDS || wr_pending)
                    $fatal(1, "Invalid/overlapping read request %h", rd_req_addr);
                if (trace_enabled && (reads_seen >= expected_read_count ||
                    rd_req_addr !== expected_reads[reads_seen]))
                    $fatal(1, "Read trace mismatch at request %0d: %h", reads_seen, rd_req_addr);
                rd_pending <= 1;
                rd_rsp_data <= source_mem[rd_req_addr >> 1];
                rd_rsp_error <= (fault_kind == 1 && reads_seen == fault_index);
                rd_delay <= (timing_mode == 0) ? 0 : int'(prng[6:4]);
                reads_seen <= reads_seen + 1;
            end
            if (rd_rsp_valid && rd_rsp_ready) rd_pending <= 0;
            if (wr_req_valid && wr_req_ready) begin
                if (wr_req_addr[0] || wr_req_addr >= 2 * WORDS || rd_pending)
                    $fatal(1, "Invalid/overlapping write request %h", wr_req_addr);
                if (trace_enabled && (writes_seen >= expected_write_count ||
                    wr_req_addr !== expected_writes[writes_seen] ||
                    wr_req_data !== expected_write_data[writes_seen]))
                    $fatal(1, "Write trace mismatch request=%0d addr=%h data=%h",
                           writes_seen, wr_req_addr, wr_req_data);
                wr_pending <= 1;
                pending_wr_addr <= wr_req_addr;
                pending_wr_data <= wr_req_data;
                wr_rsp_error <= (fault_kind == 2 && writes_seen == fault_index);
                wr_delay <= (timing_mode == 0) ? 0 : int'(prng[9:7]);
                writes_seen <= writes_seen + 1;
            end
            if (wr_rsp_valid && wr_rsp_ready) begin
                wr_pending <= 0;
                if (!wr_rsp_error) begin
                    destination_mem[pending_wr_addr >> 1] <= pending_wr_data;
                    successful_writes <= successful_writes + 1;
                end
            end
        end
    end

    logic rd_stalled = 0, wr_stalled = 0;
    logic [31:0] held_rd_addr, held_wr_addr;
    logic [15:0] held_wr_data;
    always @(posedge clk) begin
        if (rst) begin
            rd_stalled <= 0;
            wr_stalled <= 0;
        end else begin
            if (rd_stalled && (!rd_req_valid || rd_req_addr !== held_rd_addr))
                $fatal(1, "Read request changed while stalled");
            if (wr_stalled && (!wr_req_valid || wr_req_addr !== held_wr_addr ||
                               wr_req_data !== held_wr_data))
                $fatal(1, "Write request changed while stalled");
            rd_stalled <= rd_req_valid && !rd_req_ready;
            wr_stalled <= wr_req_valid && !wr_req_ready;
            held_rd_addr <= rd_req_addr;
            held_wr_addr <= wr_req_addr;
            held_wr_data <= wr_req_data;
            if (desc_ready !== !busy) $fatal(1, "Descriptor ready/busy contract");
        end
    end

    integer reset_checks = 0;
    task automatic reset_at_stage(input integer stage);
        begin
            @(negedge clk);
            rst = 1;
            desc_valid = 0;
            trace_enabled = 0;
            hold_rd_req = (stage == 1);
            hold_rd_rsp = (stage == 2);
            hold_wr_req = (stage == 3);
            hold_wr_rsp = (stage == 4);
            repeat (2) @(posedge clk);
            @(negedge clk);
            rst = 0;
            desc_valid = 1;
            desc_src_base = 0;
            desc_dst_base = 16;
            desc_rows = 1;
            desc_cols = 1;
            desc_src_row_stride = 2;
            desc_src_col_stride = 2;
            desc_dst_row_stride = 2;
            desc_dst_col_stride = 2;
            @(posedge clk);
            #1;
            if (!busy || done) $fatal(1, "Reset test descriptor not started");
            if (stage != 0) begin
                @(negedge clk);
                desc_valid = 0;
                case (stage)
                    1: wait (rd_req_valid);
                    2: wait (rd_rsp_ready && rd_pending);
                    3: wait (wr_req_valid);
                    4: wait (wr_rsp_ready && wr_pending);
                    5: wait (wr_rsp_valid && wr_rsp_ready);
                endcase
                if (stage == 5) begin
                    @(posedge clk);
                    #1; // Last write acknowledged; FINISH has not yet pulsed done.
                end else begin
                    repeat (2) @(posedge clk);
                    #1;
                end
            end
            @(negedge clk);
            rst = 1;
            desc_valid = 1;
            desc_rows = 0;
            @(posedge clk);
            #1;
            if (busy || done || error || rd_req_valid || wr_req_valid ||
                rd_rsp_ready || wr_rsp_ready || completed_elements != 0)
                $fatal(1, "Reset cancellation failed at stage %0d", stage);
            @(negedge clk);
            rst = 0;
            desc_valid = 0;
            hold_rd_req = 0;
            hold_rd_rsp = 0;
            hold_wr_req = 0;
            hold_wr_rsp = 0;
            repeat (3) begin
                @(posedge clk);
                #1;
                if (busy || done || error || rd_pending || wr_pending)
                    $fatal(1, "Late activity after reset at stage %0d", stage);
            end
            reset_checks = reset_checks + 1;
        end
    endtask

    integer vector_file, metrics_file, scanned;
    integer case_id = 0, i, stage;
    integer total_reads = 0, total_writes = 0, total_completed = 0;
    integer codes_seen [0:5];
    longint unsigned total_read_wait = 0, total_write_wait = 0;
    string vector_path;
    initial begin
        for (i = 0; i < WORDS; i = i + 1) begin
            source_mem[i] = 16'(i);
            destination_mem[i] = 16'ha55a;
        end
        for (i = 0; i < 6; i = i + 1) codes_seen[i] = 0;
        for (stage = 0; stage < 6; stage = stage + 1) reset_at_stage(stage);
        if (!$value$plusargs("COPY_VECTORS=%s", vector_path)) vector_path = "copy_vectors.txt";
        vector_file = $fopen(vector_path, "r");
        metrics_file = $fopen("copy_metrics.csv", "w");
        if (vector_file == 0 || metrics_file == 0) $fatal(1, "Unable to open copy vector/metrics files");
        $fdisplay(metrics_file, "id,completed_elements,elapsed_cycles,read_wait_cycles,write_wait_cycles,error_code,read_requests,write_requests");
        while (!$feof(vector_file)) begin
            @(negedge clk);
            desc_valid = 0;
            scanned = $fscanf(vector_file, "%h %h %h %h %h %h %h %h %h %h %h %h %h %h %h %h\n",
                desc_src_base, desc_dst_base, desc_rows, desc_cols,
                desc_src_row_stride, desc_src_col_stride,
                desc_dst_row_stride, desc_dst_col_stride,
                timing_mode, fault_kind, fault_index, expected_error, expected_completed,
                expected_read_count, expected_write_count, expected_cycles);
            if (scanned == -1) break;
            if (scanned != 16 || expected_read_count > WORDS || expected_write_count > WORDS)
                $fatal(1, "Malformed copy case header %0d", case_id);
            for (i = 0; i < WORDS; i = i + 1) begin
                scanned = $fscanf(vector_file, "%h %h %h\n", source_mem[i], destination_mem[i], golden_mem[i]);
                if (scanned != 3) $fatal(1, "Missing memory image case=%0d word=%0d", case_id, i);
            end
            for (i = 0; i < expected_read_count; i = i + 1) begin
                scanned = $fscanf(vector_file, "%h\n", expected_reads[i]);
                if (scanned != 1) $fatal(1, "Missing expected read");
            end
            for (i = 0; i < expected_write_count; i = i + 1) begin
                scanned = $fscanf(vector_file, "%h %h\n", expected_writes[i], expected_write_data[i]);
                if (scanned != 2) $fatal(1, "Missing expected write");
            end
            trace_enabled = 1;
            if (!desc_ready) $fatal(1, "Not ready for copy descriptor");
            desc_valid = 1;
            @(posedge clk);
            #1;
            if (!busy || done) $fatal(1, "Copy descriptor acceptance failed");
            @(negedge clk);
            // Keep a conflicting descriptor asserted throughout busy operation.
            desc_rows = 0;
            desc_cols = 0;
            desc_src_base = '1;
            desc_dst_base = '1;
            while (!done) begin
                @(posedge clk);
                #1;
                if (!busy && !done) $fatal(1, "Copy lost active descriptor");
            end
            if (error !== (expected_error != 0) || error_code !== 3'(expected_error) ||
                completed_elements !== 32'(expected_completed) || busy ||
                reads_seen != expected_read_count || writes_seen != expected_write_count ||
                successful_writes != expected_completed || rd_pending || wr_pending)
                $fatal(1, "Copy status mismatch case=%0d code=%0d/%0d completed=%0d/%0d reads=%0d/%0d writes=%0d/%0d",
                    case_id, error_code, expected_error, completed_elements, expected_completed,
                    reads_seen, expected_read_count, writes_seen, expected_write_count);
            if (elapsed_cycles !== bench_cycles || read_wait_cycles !== bench_read_wait ||
                write_wait_cycles !== bench_write_wait)
                $fatal(1, "Performance counter mismatch case=%0d cycles=%0d/%0d", case_id, elapsed_cycles, bench_cycles);
            if (expected_cycles != 0 && elapsed_cycles != expected_cycles)
                $fatal(1, "Minimum-latency baseline mismatch case=%0d cycles=%0d/%0d", case_id, elapsed_cycles, expected_cycles);
            for (i = 0; i < WORDS; i = i + 1)
                if (destination_mem[i] !== golden_mem[i])
                    $fatal(1, "Destination mismatch case=%0d word=%0d got=%h expected=%h",
                           case_id, i, destination_mem[i], golden_mem[i]);
            $fdisplay(metrics_file, "%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d", case_id,
                completed_elements, elapsed_cycles, read_wait_cycles, write_wait_cycles,
                error_code, reads_seen, writes_seen);
            total_reads = total_reads + reads_seen;
            total_writes = total_writes + writes_seen;
            total_completed = total_completed + successful_writes;
            total_read_wait = total_read_wait + read_wait_cycles;
            total_write_wait = total_write_wait + write_wait_cycles;
            codes_seen[expected_error] = codes_seen[expected_error] + 1;
            case_id = case_id + 1;
            @(negedge clk);
            desc_valid = 0;
            @(posedge clk);
            #1;
            if (done || error || busy) $fatal(1, "Completion/error pulse did not clear");
        end
        $fclose(vector_file);
        $fclose(metrics_file);
        for (i = 0; i < 6; i = i + 1)
            if (codes_seen[i] == 0) $fatal(1, "Error/status code %0d not exercised", i);
        if (total_read_wait == 0 || total_write_wait == 0 || reset_checks != 6)
            $fatal(1, "Stall/reset coverage absent");
        $display("TMA_COPY_ENGINE_PASS descriptors=%0d reads=%0d writes=%0d completed=%0d reset_stages=%0d read_wait=%0d write_wait=%0d whole_memory_checks=%0d",
            case_id, total_reads, total_writes, total_completed, reset_checks,
            total_read_wait, total_write_wait, case_id * WORDS);
        $finish;
    end
endmodule

`default_nettype wire
