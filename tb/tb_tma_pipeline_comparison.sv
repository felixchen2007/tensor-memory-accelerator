`timescale 1ns/1ps
`default_nettype none

module tb_tma_pipeline_comparison;
    logic clk = 0;
    always #5 clk = !clk;
    logic rst = 1, load_image = 0, desc_valid = 0, trace_enabled = 0;
    logic [31:0] desc_src_base = 0, desc_dst_base = 2048;
    logic [15:0] desc_rows = 1, desc_cols = 32;
    logic [31:0] desc_src_row_stride = 64, desc_src_col_stride = 2;
    logic [31:0] desc_dst_row_stride = 64, desc_dst_col_stride = 2;
    wire [1:0] desc_ready, busy, done, error;
    wire [1:0][2:0] error_code;
    wire [1:0][31:0] completed_elements;
    wire [1:0][63:0] elapsed_cycles, read_wait_cycles, write_wait_cycles;
    wire [1:0] rd_req_valid, rd_req_ready, rd_rsp_valid, rd_rsp_ready, rd_rsp_error;
    wire [1:0][31:0] rd_req_addr;
    wire [1:0][15:0] rd_rsp_data;
    wire [1:0] wr_req_valid, wr_req_ready, wr_rsp_valid, wr_rsp_ready, wr_rsp_error;
    wire [1:0][31:0] wr_req_addr;
    wire [1:0][15:0] wr_req_data;
    wire [1:0] rd_pending, wr_pending;
    wire [15:0] destination_mem [0:1][0:4095];
    logic [15:0] source_image [0:4095], initial_image [0:4095], golden [0:4095];
    logic [31:0] legal_reads [0:4095], expected_writes [0:4095];
    logic [15:0] expected_write_data [0:4095];
    integer reads_seen [0:1], writes_seen [0:1], successful_writes [0:1], overlap_cycles [0:1];
    integer timing_mode = 0, fault_kind = 0, fault_index = 0, stress_mode = 0;
    integer legal_read_count = 0, expected_write_count = 0;
    logic [31:0] timing_seed = 32'h74a913e5, base_seed = 32'h74a913e5;
    logic [1:0] hold_rd_req = 0, hold_rd_rsp = 0, hold_wr_req = 0, hold_wr_rsp = 0;
    logic [1:0] seen_done = 0;
    logic [1:0][63:0] bench_cycles = 0, bench_read_wait = 0, bench_write_wait = 0;
    logic [1:0] rd_stalled = 0, wr_stalled = 0;
    logic [1:0][31:0] held_rd_addr, held_wr_addr;
    logic [1:0][15:0] held_wr_data;
    integer watchdog = 0;

    genvar engine_index;
    generate
        for (engine_index = 0; engine_index < 2; engine_index = engine_index + 1) begin : copies
            tma_copy_engine_select #(.PIPELINED(engine_index == 1)) engine (
                .clk(clk), .rst(rst), .desc_valid(desc_valid), .desc_ready(desc_ready[engine_index]),
                .desc_src_base(desc_src_base), .desc_dst_base(desc_dst_base),
                .desc_rows(desc_rows), .desc_cols(desc_cols),
                .desc_src_row_stride(desc_src_row_stride), .desc_src_col_stride(desc_src_col_stride),
                .desc_dst_row_stride(desc_dst_row_stride), .desc_dst_col_stride(desc_dst_col_stride),
                .rd_req_valid(rd_req_valid[engine_index]), .rd_req_ready(rd_req_ready[engine_index]),
                .rd_req_addr(rd_req_addr[engine_index]), .rd_rsp_valid(rd_rsp_valid[engine_index]),
                .rd_rsp_ready(rd_rsp_ready[engine_index]), .rd_rsp_data(rd_rsp_data[engine_index]),
                .rd_rsp_error(rd_rsp_error[engine_index]), .wr_req_valid(wr_req_valid[engine_index]),
                .wr_req_ready(wr_req_ready[engine_index]), .wr_req_addr(wr_req_addr[engine_index]),
                .wr_req_data(wr_req_data[engine_index]), .wr_rsp_valid(wr_rsp_valid[engine_index]),
                .wr_rsp_ready(wr_rsp_ready[engine_index]), .wr_rsp_error(wr_rsp_error[engine_index]),
                .busy(busy[engine_index]), .done(done[engine_index]), .error(error[engine_index]),
                .error_code(error_code[engine_index]), .completed_elements(completed_elements[engine_index]),
                .elapsed_cycles(elapsed_cycles[engine_index]), .read_wait_cycles(read_wait_cycles[engine_index]),
                .write_wait_cycles(write_wait_cycles[engine_index])
            );
            tma_paired_memory_model memory (
                .clk(clk), .rst(rst), .load_image(load_image),
                .source_image(source_image), .initial_image(initial_image),
                .destination_mem(destination_mem[engine_index]), .timing_mode(timing_mode), .timing_seed(timing_seed),
                .fault_kind(fault_kind), .fault_index(fault_index),
                .hold_read_request(hold_rd_req[engine_index] ||
                    (stress_mode == 2 && reads_seen[engine_index] >= 1 && elapsed_cycles[engine_index] < 64)),
                .hold_read_response(hold_rd_rsp[engine_index]),
                .hold_write_request(hold_wr_req[engine_index] ||
                    (stress_mode == 1 && elapsed_cycles[engine_index] < 64)),
                .hold_write_response(hold_wr_rsp[engine_index]), .trace_enabled(trace_enabled),
                .legal_read_count(legal_read_count), .expected_write_count(expected_write_count),
                .legal_reads(legal_reads), .expected_writes(expected_writes), .expected_write_data(expected_write_data),
                .rd_req_valid(rd_req_valid[engine_index]), .rd_req_ready(rd_req_ready[engine_index]),
                .rd_req_addr(rd_req_addr[engine_index]), .rd_rsp_valid(rd_rsp_valid[engine_index]),
                .rd_rsp_ready(rd_rsp_ready[engine_index]), .rd_rsp_data(rd_rsp_data[engine_index]),
                .rd_rsp_error(rd_rsp_error[engine_index]), .wr_req_valid(wr_req_valid[engine_index]),
                .wr_req_ready(wr_req_ready[engine_index]), .wr_req_addr(wr_req_addr[engine_index]),
                .wr_req_data(wr_req_data[engine_index]), .wr_rsp_valid(wr_rsp_valid[engine_index]),
                .wr_rsp_ready(wr_rsp_ready[engine_index]), .wr_rsp_error(wr_rsp_error[engine_index]),
                .rd_pending(rd_pending[engine_index]), .wr_pending(wr_pending[engine_index]),
                .reads_seen(reads_seen[engine_index]), .writes_seen(writes_seen[engine_index]),
                .successful_writes(successful_writes[engine_index]), .overlap_cycles(overlap_cycles[engine_index])
            );
        end
    endgenerate
    wire [31:0] peak_buffered = copies[1].engine.pipelined.impl.peak_buffered;
    wire [63:0] buffer_stall_cycles = copies[1].engine.pipelined.impl.buffer_stall_cycles;

    always @(posedge clk) begin
        watchdog <= watchdog + 1;
        if (watchdog > 2000000) $fatal(1, "Pipeline comparison watchdog");
        for (int core = 0; core < 2; core++) begin
            if (rst || load_image) begin
                seen_done[core] <= 0;
                rd_stalled[core] <= 0;
                wr_stalled[core] <= 0;
                bench_cycles[core] <= 0;
                bench_read_wait[core] <= 0;
                bench_write_wait[core] <= 0;
            end else begin
                if (desc_valid && desc_ready[core]) begin
                    bench_cycles[core] <= 0;
                    bench_read_wait[core] <= 0;
                    bench_write_wait[core] <= 0;
                end else if (busy[core]) begin
                    bench_cycles[core] <= bench_cycles[core] + 1;
                    if ((rd_req_valid[core] && !rd_req_ready[core]) || (rd_rsp_ready[core] && !rd_rsp_valid[core]))
                        bench_read_wait[core] <= bench_read_wait[core] + 1;
                    if ((wr_req_valid[core] && !wr_req_ready[core]) || (wr_rsp_ready[core] && !wr_rsp_valid[core]))
                        bench_write_wait[core] <= bench_write_wait[core] + 1;
                end
                if (done[core]) begin
                    seen_done[core] <= 1;
                    if (error[core] !== (error_code[core] != 0))
                        $fatal(1, "Completion/error pulse mismatch, core=%0d", core);
                    if (rd_pending[core] || wr_pending[core] || busy[core])
                        $fatal(1, "Pipeline/baseline completed before draining memory, core=%0d", core);
                end
                if (error[core] && !done[core]) $fatal(1, "Error without completion");
                if (rd_stalled[core] && (!rd_req_valid[core] || rd_req_addr[core] !== held_rd_addr[core]))
                    $fatal(1, "Read request changed while stalled, core=%0d", core);
                if (wr_stalled[core] && (!wr_req_valid[core] || wr_req_addr[core] !== held_wr_addr[core] ||
                                        wr_req_data[core] !== held_wr_data[core]))
                    $fatal(1, "Write request changed while stalled, core=%0d", core);
                if (desc_ready[core] !== !busy[core]) $fatal(1, "Ready/busy mismatch");
                rd_stalled[core] <= rd_req_valid[core] && !rd_req_ready[core];
                wr_stalled[core] <= wr_req_valid[core] && !wr_req_ready[core];
                held_rd_addr[core] <= rd_req_addr[core];
                held_wr_addr[core] <= wr_req_addr[core];
                held_wr_data[core] <= wr_req_data[core];
            end
        end
        if (!rst && peak_buffered > 4) $fatal(1, "FIFO overflow");
    end

    integer reset_checks = 0;
    task automatic reset_pipeline(input integer stage);
        begin
            @(negedge clk);
            rst = 1;
            trace_enabled = 0;
            desc_valid = 0;
            hold_rd_req = stage == 0 ? 2'b10 : 0;
            hold_rd_rsp = stage == 1 ? 2'b10 : 0;
            hold_wr_req = stage == 2 ? 2'b10 : 0;
            hold_wr_rsp = stage == 3 ? 2'b10 : 0;
            repeat (2) @(posedge clk);
            @(negedge clk);
            rst = 0;
            desc_valid = 1;
            @(posedge clk);
            #1;
            @(negedge clk);
            desc_valid = 0;
            case (stage)
                0: wait (rd_req_valid[1]);
                1: wait (rd_pending[1] && rd_rsp_ready[1]);
                2: wait (peak_buffered == 4 && rd_rsp_valid[1] && !rd_rsp_ready[1]);
                3: wait (wr_pending[1] && wr_rsp_ready[1]);
            endcase
            repeat (2) @(posedge clk);
            @(negedge clk);
            rst = 1;
            @(posedge clk);
            #1;
            if (busy != 0 || done != 0 || rd_pending != 0 || wr_pending != 0 || peak_buffered != 0)
                $fatal(1, "Pipeline reset failed stage=%0d", stage);
            @(negedge clk);
            rst = 0;
            hold_rd_req = 0;
            hold_rd_rsp = 0;
            hold_wr_req = 0;
            hold_wr_rsp = 0;
            repeat (3) begin
                @(posedge clk);
                #1;
                if (busy != 0 || done != 0 || rd_pending != 0 || wr_pending != 0)
                    $fatal(1, "Late activity after pipeline reset");
            end
            reset_checks = reset_checks + 1;
        end
    endtask

    integer vector_file, metrics_file, scanned, case_id = 0;
    integer expected_error, expected_completed, minimum_reads, baseline_cycles, ignored;
    integer checked_words = 0, overlap_cases = 0, full_fifo_cases = 0, faster_cases = 0;
    integer codes_seen [0:5];
    string vector_path;
    initial begin
        for (int index = 0; index < 4096; index++) begin
            source_image[index] = 16'(index);
            initial_image[index] = 16'ha55a;
        end
        for (int code = 0; code < 6; code++) codes_seen[code] = 0;
        if ($value$plusargs("TIMING_SEED=%h", base_seed)) timing_seed = base_seed;
        @(negedge clk);
        load_image = 1;
        @(posedge clk);
        @(negedge clk);
        load_image = 0;
        for (int stage = 0; stage < 4; stage++) reset_pipeline(stage);
        if (!$value$plusargs("PIPELINE_VECTORS=%s", vector_path)) vector_path = "pipeline_vectors.txt";
        vector_file = $fopen(vector_path, "r");
        metrics_file = $fopen("pipeline_metrics.csv", "w");
        if (vector_file == 0 || metrics_file == 0) $fatal(1, "Pipeline files missing");
        $fdisplay(metrics_file, "id,mode,baseline_cycles,pipeline_cycles,baseline_reads,pipeline_reads,write_requests,completed_elements,error_code,pipeline_peak_buffered,pipeline_buffer_stalls,pipeline_overlap_cycles,baseline_read_wait,baseline_write_wait,pipeline_read_wait,pipeline_write_wait");
        while (!$feof(vector_file)) begin
            @(negedge clk);
            scanned = $fscanf(vector_file, "%h %h %h %h %h %h %h %h %h %h %h %h %h %h %h %h %h %h\n",
                desc_src_base, desc_dst_base, desc_rows, desc_cols,
                desc_src_row_stride, desc_src_col_stride, desc_dst_row_stride, desc_dst_col_stride,
                timing_mode, fault_kind, fault_index, expected_error, expected_completed,
                minimum_reads, expected_write_count, baseline_cycles, legal_read_count, stress_mode);
            if (scanned == -1) break;
            if (scanned != 18 || legal_read_count > 4096 || expected_write_count > 4096)
                $fatal(1, "Bad pipeline case header %0d", case_id);
            for (int index = 0; index < 4096; index++) begin
                scanned = $fscanf(vector_file, "%h %h %h\n", source_image[index], initial_image[index], golden[index]);
                if (scanned != 3) $fatal(1, "Truncated pipeline memory image");
            end
            for (int index = 0; index < minimum_reads; index++) begin
                scanned = $fscanf(vector_file, "%h\n", ignored);
                if (scanned != 1) $fatal(1, "Truncated minimum read trace");
            end
            for (int index = 0; index < expected_write_count; index++) begin
                scanned = $fscanf(vector_file, "%h %h\n", expected_writes[index], expected_write_data[index]);
                if (scanned != 2) $fatal(1, "Truncated pipeline write trace");
            end
            for (int index = 0; index < legal_read_count; index++) begin
                scanned = $fscanf(vector_file, "%h\n", legal_reads[index]);
                if (scanned != 1) $fatal(1, "Truncated legal prefetch trace");
            end
            timing_seed = base_seed ^ (32'(case_id) * 32'h45d9f3b);
            trace_enabled = 1;
            load_image = 1;
            @(posedge clk);
            #1;
            @(negedge clk);
            load_image = 0;
            desc_valid = 1;
            @(posedge clk);
            if (desc_ready != 2'b11) $fatal(1, "Paired descriptors not accepted together");
            #1;
            @(negedge clk);
            desc_valid = 0;
            desc_rows = 0;
            desc_cols = 0;
            desc_src_base = '1;
            desc_dst_base = '1;
            while (seen_done != 2'b11) begin
                @(posedge clk);
                #1;
            end
            for (int core = 0; core < 2; core++) begin
                if (error_code[core] !== 3'(expected_error) ||
                    completed_elements[core] !== 32'(expected_completed) ||
                    writes_seen[core] != expected_write_count || successful_writes[core] != expected_completed ||
                    reads_seen[core] < minimum_reads || reads_seen[core] > legal_read_count ||
                    busy[core] || rd_pending[core] || wr_pending[core])
                    $fatal(1, "Paired status mismatch case=%0d core=%0d code=%0d/%0d done_words=%0d/%0d reads=%0d writes=%0d/%0d",
                        case_id, core, error_code[core], expected_error, completed_elements[core], expected_completed,
                        reads_seen[core], writes_seen[core], expected_write_count);
                if ((core == 0 || fault_kind == 0) && reads_seen[core] != minimum_reads)
                    $fatal(1, "Unexpected non-prefetch read count");
                if (elapsed_cycles[core] !== bench_cycles[core] ||
                    read_wait_cycles[core] !== bench_read_wait[core] || write_wait_cycles[core] !== bench_write_wait[core])
                    $fatal(1, "Paired counters mismatch case=%0d core=%0d", case_id, core);
                for (int index = 0; index < 4096; index++) begin
                    if (destination_mem[core][index] !== golden[index])
                        $fatal(1, "Paired memory mismatch case=%0d core=%0d word=%0d got=%h expected=%h",
                            case_id, core, index, destination_mem[core][index], golden[index]);
                    checked_words = checked_words + 1;
                end
            end
            if (baseline_cycles != 0 && (elapsed_cycles[0] != baseline_cycles ||
                elapsed_cycles[1] != expected_completed + 6))
                $fatal(1, "Ideal pipeline schedule mismatch case=%0d baseline=%0d pipeline=%0d", case_id, elapsed_cycles[0], elapsed_cycles[1]);
            if (stress_mode == 2 && reads_seen[1] < 2)
                $fatal(1, "Stalled offered read was not drained on write error");
            if (stress_mode == 1 && peak_buffered != 4)
                $fatal(1, "Read fault stress did not fill the FIFO");
            if (overlap_cycles[1] != 0) overlap_cases = overlap_cases + 1;
            if (peak_buffered == 4) full_fifo_cases = full_fifo_cases + 1;
            if (expected_error == 0 && elapsed_cycles[1] < elapsed_cycles[0]) faster_cases = faster_cases + 1;
            codes_seen[expected_error] = codes_seen[expected_error] + 1;
            $fdisplay(metrics_file, "%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d",
                case_id, timing_mode, elapsed_cycles[0], elapsed_cycles[1], reads_seen[0], reads_seen[1],
                writes_seen[1], completed_elements[1], error_code[1], peak_buffered, buffer_stall_cycles,
                overlap_cycles[1], read_wait_cycles[0], write_wait_cycles[0], read_wait_cycles[1], write_wait_cycles[1]);
            case_id = case_id + 1;
        end
        $fclose(vector_file);
        $fclose(metrics_file);
        for (int code = 0; code < 6; code++)
            if (codes_seen[code] == 0) $fatal(1, "Missing paired status coverage");
        if (overlap_cases == 0 || full_fifo_cases == 0 || faster_cases == 0 || reset_checks != 4)
            $fatal(1, "Missing pipeline coverage");
        $display("TMA_PIPELINE_COMPARISON_PASS descriptors=%0d whole_memory_checks=%0d reset_scenarios=%0d overlap_cases=%0d full_fifo_cases=%0d faster_successful_cases=%0d identical_per_transaction_timing=pass",
            case_id, checked_words, reset_checks, overlap_cases, full_fifo_cases, faster_cases);
        $finish;
    end
endmodule

`default_nettype wire
