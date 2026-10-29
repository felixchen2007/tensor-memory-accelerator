`timescale 1ns/1ps
`default_nettype none
module tb_tma_de10_lite #(
    parameter bit PIPELINED=1,
    parameter int READ_BURST_WORDS=1,
    parameter bit EXPECT_FAIL=0,
    parameter logic [15:0] READ_XOR_MASK=0,
    parameter int FAULT_STAGE=0
);
    logic MAX10_CLK1_50=0;
    always #10 MAX10_CLK1_50=~MAX10_CLK1_50;
    wire [9:0] LEDR;
    wire [12:0] DRAM_ADDR;
    wire [1:0] DRAM_BA;
    wire DRAM_CAS_N,DRAM_CKE,DRAM_CLK,DRAM_CS_N;
    wire DRAM_LDQM,DRAM_UDQM,DRAM_RAS_N,DRAM_WE_N;
    tri [15:0] DRAM_DQ;
    tma_de10_lite #(.PIPELINED(PIPELINED),.READ_BURST_WORDS(READ_BURST_WORDS)) dut (.*);
    integer reads,writes,refreshes,max_refresh_gap;
    integer descriptor_starts=0;
    always @(posedge dut.core_clk) begin
        if(!dut.rst && dut.stage_code==9 && dut.test.desc_ready) begin
            if(dut.test.system.source.refresh_age_q!=1)
                $fatal(1,"board descriptor did not start at the controlled refresh phase");
            descriptor_starts++;
        end
    end
    wire power_reset=dut.rst;
    tma_sdram_model #(.READ_XOR_MASK(READ_XOR_MASK)) memory (.dram_clk(DRAM_CLK),.power_reset(power_reset),.cke(DRAM_CKE),
        .cs_n(DRAM_CS_N),.ras_n(DRAM_RAS_N),.cas_n(DRAM_CAS_N),.we_n(DRAM_WE_N),
        .addr(DRAM_ADDR),.ba(DRAM_BA),.dqm({DRAM_UDQM,DRAM_LDQM}),
        .controller_oe(dut.dq_oe),.dq(DRAM_DQ),.*);
    // Inject at public maintenance response data, without modifying RAM arrays.
    initial begin
        if(FAULT_STAGE==2) begin
            wait(dut.stage_code==8 && dut.test.maint_rsp_valid);
            force dut.test.maint_rsp_data=16'h9932;
        end else if(FAULT_STAGE==3) begin
            wait(dut.stage_code==12 && dut.test.maint_rsp_valid);
            force dut.test.maint_rsp_data=16'ha55b;
        end
    end
    initial begin
        wait(LEDR[1] || LEDR[2]);#1;
        if(FAULT_STAGE!=2) begin
            repeat(3) @(posedge MAX10_CLK1_50);
            #1;
            if(dut.read_trace[255:240]!==16'h5254 || dut.read_trace[227:224]!=12)
                $fatal(1,"read trace was not completed");
            if(FAULT_STAGE==1 && dut.read_trace[16*dut.read_trace[231:228] +: 16]!==dut.observed_data)
                $fatal(1,"read trace capture does not match consumed data");
            $display("TMA_READ_TRACE_HEX=%h",dut.read_trace);
        end
        if(EXPECT_FAIL) begin
            if(!LEDR[2] || LEDR[1] || dut.failure_word!=0 || dut.stage_code!=13)
                $fatal(1,"board failure diagnostics incorrect");
            if(FAULT_STAGE==2) begin
                if(dut.failure_reason!=9 || dut.expected_data!==16'h9933 || dut.observed_data!==16'h9932 ||
                    dut.passed_stages!=0 || dut.completed_elements!=0 || reads!=0 || writes!=0)
                    $fatal(1,"scratchpad preflight did not isolate local failure");
            end else if(FAULT_STAGE==3) begin
                if(dut.failure_reason!=4 || dut.expected_data!==16'ha55a || dut.observed_data!==16'ha55b ||
                    dut.passed_stages!=7 || dut.completed_elements!=1024 ||
                    dut.source_checked_words!=1024 || dut.scratch_checked_words!=1024)
                    $fatal(1,"tensor failure did not retain preflight success");
            end else begin
                if(dut.failure_reason!=6 || dut.expected_data!==16'ha55a || dut.observed_data!==(16'ha55a ^ READ_XOR_MASK) ||
                    dut.passed_stages!=1 || dut.completed_elements!=0 || dut.source_checked_words!=0 || dut.scratch_checked_words!=1024)
                    $fatal(1,"source preflight did not stop before tensor copy");
            end
            $display("TMA_DEBUG_HEX=%h",dut.debug_value);
            $display("TMA_DE10_LITE_FAIL_DETECTED fault_stage=%0d reason=%0d word=%0d expected=%h observed=%h",FAULT_STAGE,dut.failure_reason,dut.failure_word,dut.expected_data,dut.observed_data);
            $finish;
        end
        if(!LEDR[1] || LEDR[2] || dut.checked_words!=1024) $fatal(1,"board selftest failed");
        if(dut.failure_reason!=0 || dut.completed_elements!=1024 || dut.debug_value[255:240]!==16'h544d ||
            dut.debug_value[239:232]!==(READ_BURST_WORDS==4 ? 8'd4 : 8'd3) ||
            dut.debug_value[3:0]!=={1'b1,(READ_BURST_WORDS==4),1'b1,PIPELINED} ||
            dut.source_checked_words!=1024 ||
            dut.scratch_checked_words!=1024 || dut.passed_stages!=7)
            $fatal(1,"board diagnostic fields incorrect");
        if(reads!=(READ_BURST_WORDS==4 ? 512 : 2048) || writes!=1024 ||
            memory.read_beats!=2048 || descriptor_starts!=1) $fatal(1,"board coverage missing");
        repeat(1000) @(posedge MAX10_CLK1_50);
        $display("TMA_DEBUG_HEX=%h",dut.debug_value);
        $display("TMA_DE10_LITE_PASS words=%0d source_checks=%0d scratch_checks=%0d reads=%0d writes=%0d refreshes=%0d max_refresh_gap=%0d copy_cycles=%0d pipelined=%0d refresh_phase=1 burst_words=%0d read_beats=%0d",dut.checked_words,dut.source_checked_words,dut.scratch_checked_words,reads,writes,refreshes,max_refresh_gap,dut.test.elapsed_cycles,PIPELINED,READ_BURST_WORDS,memory.read_beats);
        $finish;
    end
    initial begin #10000000;$fatal(1,"board selftest watchdog");end
endmodule
`default_nettype wire
