`timescale 1ns/1ps
`default_nettype none

module tb_tma_local_copy_system #(
    parameter bit PIPELINED = 0,
    parameter bit SWIZZLE = 0,
    parameter int unsigned SWIZZLE_SHIFT = 5
);
    logic clk = 0;
    always #5 clk = !clk;
    logic rst = 1, desc_valid = 0;
    wire desc_ready;
    logic [31:0] desc_src_base = 0, desc_dst_base = 0;
    logic [15:0] desc_rows = 0, desc_cols = 0;
    logic [31:0] desc_src_row_stride = 0, desc_src_col_stride = 0;
    logic [31:0] desc_dst_row_stride = 0, desc_dst_col_stride = 0;
    logic maint_req_valid = 0, maint_req_write = 0, maint_req_dst = 0;
    wire maint_req_ready, maint_rsp_valid, maint_rsp_error;
    logic [31:0] maint_req_addr = 0;
    logic [15:0] maint_req_data = 0;
    logic maint_rsp_ready = 0;
    wire [15:0] maint_rsp_data;
    wire busy, done, error;
    wire [2:0] error_code;
    wire [31:0] completed_elements, src_bank_conflict_cycles, dst_bank_conflict_cycles;
    wire [63:0] elapsed_cycles, read_wait_cycles, write_wait_cycles;
    tma_local_copy_system #(.PIPELINED(PIPELINED), .SWIZZLE(SWIZZLE), .SWIZZLE_SHIFT(SWIZZLE_SHIFT)) dut (.*);

    logic [15:0] source_image [0:4095], destination_image [0:4095], golden [0:4095];
    integer watchdog = 0, maintenance_commands = 0;
    always @(posedge clk) begin
        watchdog <= watchdog + 1;
        if (watchdog > 5000000) $fatal(1, "Local RAM integration watchdog");
        if (!rst) begin
            if (busy && maint_req_ready) $fatal(1, "Maintenance allowed during copy");
            if (maint_req_valid && maint_req_ready && desc_valid && desc_ready)
                $fatal(1, "Descriptor and maintenance accepted together");
            if (maint_req_valid && maint_req_ready)
                maintenance_commands <= maintenance_commands + 1;
        end
    end

    task automatic access_memory(input logic write_word, input logic destination,
        input logic [31:0] address, input logic [15:0] value,
        input logic expected_error, input integer response_hold,
        output logic [15:0] result);
        logic [15:0] held_data;
        begin
            @(negedge clk);
            maint_req_valid = 1;
            maint_req_write = write_word;
            maint_req_dst = destination;
            maint_req_addr = address;
            maint_req_data = value;
            maint_rsp_ready = 0;
            do @(posedge clk); while (!maint_req_ready);
            #1;
            if (desc_ready) $fatal(1, "Descriptor allowed with pending maintenance response");
            @(negedge clk);
            maint_req_valid = 0;
            if (!maint_rsp_valid) $fatal(1, "Memory response missing after accepted request");
            held_data = maint_rsp_data;
            repeat (response_hold) begin
                @(posedge clk);
                #1;
                if (!maint_rsp_valid || maint_rsp_data !== held_data ||
                    maint_rsp_error !== expected_error)
                    $fatal(1, "Maintenance response did not hold under backpressure");
                @(negedge clk);
            end
            maint_rsp_ready = 1;
            @(posedge clk);
            if (!maint_rsp_valid || maint_rsp_error !== expected_error)
                $fatal(1, "Maintenance response error mismatch addr=%h", address);
            result = maint_rsp_data;
            #1;
        end
    endtask

    integer vector_file, metrics_file, scanned, case_id = 0, checked_words = 0;
    integer timing_mode, fault_kind, fault_index, expected_error, expected_completed;
    integer expected_reads, expected_writes, expected_cycles;
    logic [31:0] ignored_address;
    logic [15:0] ignored_data, value;
    longint unsigned measured_cycles;
    string vector_path, metrics_path;
    initial begin
        repeat (2) @(posedge clk);
        @(negedge clk);
        rst = 0;
        access_memory(1, 0, 0, 16'h1234, 0, 3, value);
        access_memory(0, 0, 0, 0, 0, 3, value);
        if (value !== 16'h1234) $fatal(1, "Maintenance readback mismatch");
        access_memory(1, 0, 1, 16'hffff, 1, 2, value);
        access_memory(0, 0, 8192, 0, 1, 2, value);
        access_memory(0, 0, 0, 0, 0, 0, value);
        if (value !== 16'h1234) $fatal(1, "Invalid write changed RAM");

        // Descriptor priority over a simultaneously offered maintenance read.
        @(negedge clk);
        desc_valid = 1;
        desc_rows = 0;
        desc_cols = 1;
        maint_req_valid = 1;
        maint_rsp_ready = 0;
        @(posedge clk);
        if (!desc_ready || maint_req_ready) $fatal(1, "Descriptor priority mismatch");
        #1;
        @(negedge clk);
        desc_valid = 0;
        do @(posedge clk); while (!maint_req_ready);
        #1;
        @(negedge clk);
        maint_req_valid = 0;
        maint_rsp_ready = 1;
        @(posedge clk);
        if (!maint_rsp_valid || maint_rsp_error || maint_rsp_data !== 16'h1234)
            $fatal(1, "Maintenance failed to resume after descriptor");
        #1;

        // An accepted write survives reset, even if its acknowledgement is canceled.
        @(negedge clk);
        maint_rsp_ready = 0;
        maint_req_valid = 1;
        maint_req_write = 1;
        maint_req_addr = 0;
        maint_req_data = 16'hbeef;
        @(posedge clk);
        if (!maint_req_ready) $fatal(1, "Reset persistence setup not accepted");
        #1;
        @(negedge clk);
        rst = 1;
        @(posedge clk);
        #1;
        if (maint_rsp_valid || busy || done) $fatal(1, "Pending maintenance was not canceled");
        @(negedge clk);
        rst = 0;
        maint_req_valid = 0;
        access_memory(0, 0, 0, 0, 0, 0, value);
        if (value !== 16'hbeef) $fatal(1, "Reset unexpectedly cleared committed RAM contents");

        if (!$value$plusargs("LOCAL_VECTORS=%s", vector_path)) vector_path = "local_vectors.txt";
        vector_file = $fopen(vector_path, "r");
        if (!$value$plusargs("METRICS=%s", metrics_path)) metrics_path = "local_metrics.csv";
        metrics_file = $fopen(metrics_path, "w");
        if (vector_file == 0 || metrics_file == 0) $fatal(1, "Local integration files missing");
        $fdisplay(metrics_file, "id,completed_elements,elapsed_cycles,read_wait_cycles,write_wait_cycles,error_code");
        while (!$feof(vector_file)) begin
            @(negedge clk);
            maint_req_valid = 0;
            scanned = $fscanf(vector_file, "%h %h %h %h %h %h %h %h %h %h %h %h %h %h %h %h\n",
                desc_src_base, desc_dst_base, desc_rows, desc_cols,
                desc_src_row_stride, desc_src_col_stride, desc_dst_row_stride, desc_dst_col_stride,
                timing_mode, fault_kind, fault_index, expected_error, expected_completed,
                expected_reads, expected_writes, expected_cycles);
            if (scanned == -1) break;
            if (scanned != 16 || fault_kind != 0) $fatal(1, "Malformed local case %0d", case_id);
            for (int word_index = 0; word_index < 4096; word_index++) begin
                scanned = $fscanf(vector_file, "%h %h %h\n",
                    source_image[word_index], destination_image[word_index], golden[word_index]);
                if (scanned != 3) $fatal(1, "Truncated local RAM image");
            end
            for (int index = 0; index < expected_reads; index++) begin
                scanned = $fscanf(vector_file, "%h\n", ignored_address);
                if (scanned != 1) $fatal(1, "Truncated local read oracle");
            end
            for (int index = 0; index < expected_writes; index++) begin
                scanned = $fscanf(vector_file, "%h %h\n", ignored_address, ignored_data);
                if (scanned != 2) $fatal(1, "Truncated local write oracle");
            end
            // Load using public RTL ports; no hierarchical RAM initialization.
            for (int word_index = 0; word_index < 4096; word_index++) begin
                access_memory(1, 0, 32'(2 * word_index), source_image[word_index], 0, 0, value);
                access_memory(1, 1, 32'(2 * word_index), destination_image[word_index], 0, 0, value);
            end
            @(negedge clk);
            desc_valid = 1;
            @(posedge clk);
            if (!desc_ready) $fatal(1, "Local descriptor not accepted");
            #1;
            @(negedge clk);
            desc_valid = 0;
            while (!done) begin
                @(posedge clk);
                #1;
            end
            if (error !== (expected_error != 0) || error_code !== 3'(expected_error) ||
                completed_elements !== 32'(expected_completed) || busy ||
                read_wait_cycles != 0 || write_wait_cycles != 0)
                $fatal(1, "Local copy status/counter mismatch case=%0d", case_id);
            if (expected_cycles != 0 && PIPELINED) expected_cycles = expected_completed + 6;
            if (expected_cycles != 0 && elapsed_cycles != expected_cycles)
                $fatal(1, "Local copy cycle mismatch case=%0d cycles=%0d/%0d",
                    case_id, elapsed_cycles, expected_cycles);
            if (src_bank_conflict_cycles != 0 || dst_bank_conflict_cycles != 0)
                $fatal(1, "Unexpected single-lane bank conflict");
            measured_cycles = elapsed_cycles;
            $fdisplay(metrics_file, "%0d,%0d,%0d,%0d,%0d,%0d", case_id, completed_elements,
                elapsed_cycles, read_wait_cycles, write_wait_cycles, error_code);
            for (int word_index = 0; word_index < 4096; word_index++) begin
                access_memory(0, 1, 32'(2 * word_index), 0, 0, 0, value);
                if (value !== golden[word_index])
                    $fatal(1, "Local destination mismatch case=%0d word=%0d got=%h expected=%h",
                        case_id, word_index, value, golden[word_index]);
                checked_words = checked_words + 1;
            end
            if (elapsed_cycles !== measured_cycles || done || error)
                $fatal(1, "Status changed while inspecting RAM");
            case_id = case_id + 1;
        end
        $fclose(vector_file);
        $fclose(metrics_file);
        if (case_id < 20) $fatal(1, "Insufficient local integration traffic");
        $display("TMA_LOCAL_COPY_PASS pipeline=%0d swizzle=%0d shift=%0d descriptors=%0d whole_memory_checks=%0d maintenance_commands=%0d public_port_loading=pass response_backpressure=pass invalid_accesses=pass reset_persistence=pass descriptor_priority=pass",
            PIPELINED, SWIZZLE, SWIZZLE_SHIFT, case_id, checked_words, maintenance_commands);
        $finish;
    end
endmodule

`default_nettype wire
