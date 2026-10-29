`timescale 1ns/1ps
`default_nettype none
module tb_tma_sdram_controller #(
    parameter int READ_BURST_WORDS = 1,
    parameter realtime T_AC = 5.4,
    parameter int READ_SKEW_CYCLES = 0,
    parameter int REFRESH_CYCLES = 350,
    parameter realtime SDRAM_PHASE_NS = 10.0
);
    logic clk=0, rst=1;
    always #10 clk=~clk;
    logic rd_req_valid=0, wr_req_valid=0, rd_rsp_ready=0, wr_rsp_ready=0;
    logic [31:0] rd_req_addr=0, wr_req_addr=0;
    logic [15:0] wr_req_data=0;
    wire rd_req_ready,wr_req_ready,rd_rsp_valid,wr_rsp_valid,rd_rsp_error,wr_rsp_error;
    wire [15:0] rd_rsp_data;
    wire init_done,active,dram_cke,dram_cs_n,dram_ras_n,dram_cas_n,dram_we_n;
    wire [31:0] refresh_count;
    wire [12:0] dram_addr;
    wire [1:0] dram_ba,dram_dqm;
    wire [15:0] dram_dq_out;
    wire dram_dq_oe;
    tri [15:0] dq;
    assign dq=dram_dq_oe ? dram_dq_out : 16'hzzzz;
    tma_sdram_controller #(.REFRESH_CYCLES(REFRESH_CYCLES),.READ_BURST_WORDS(READ_BURST_WORDS)) dut (.dram_dq_in(dq), .read_trace(), .*);
    initial if($test$plusargs("BAD_BURST_MODE")) force dram_addr[9]=1'b0;
    logic dram_clk=0;
    // Schedule every edge (transport delay). A delayed continuous assignment
    // would filter a clock whose half-period is shorter than the phase shift.
    always @(clk) dram_clk <= #(SDRAM_PHASE_NS) clk;
    integer reads,writes,refreshes,max_refresh_gap;
    tma_sdram_model #(.T_AC(T_AC),.READ_SKEW_CYCLES(READ_SKEW_CYCLES)) memory (
        .dram_clk(dram_clk),.power_reset(rst),.cke(dram_cke),.cs_n(dram_cs_n),
        .ras_n(dram_ras_n),.cas_n(dram_cas_n),.we_n(dram_we_n),.addr(dram_addr),
        .ba(dram_ba),.dqm(dram_dqm),.controller_oe(dram_dq_oe),.dq(dq),.*);
    logic [15:0] golden [longint unsigned];
    int checks=0, errors=0, held_cycles=0, dual_requests=0;
    int unsigned rng=32'h6c71a903;
    function automatic int unsigned random_word();
        rng=rng^(rng<<13); rng=rng^(rng>>17); rng=rng^(rng<<5); return rng;
    endfunction
    task automatic tick(); @(posedge clk); #1; endtask
    task automatic transfer(input bit wr,input logic [31:0] address,input logic [15:0] data,
                            input int stalls=0,input bit expect_error=0);
        logic [15:0] snapshot;
        int refs_before;
        @(negedge clk); #1;
        if(wr) begin wr_req_valid=1;wr_req_addr=address;wr_req_data=data; end
        else begin rd_req_valid=1;rd_req_addr=address; end
        do @(posedge clk); while (!(wr ? wr_req_ready : rd_req_ready));
        #1;
        if(wr) wr_req_valid=0; else rd_req_valid=0;
        while (!(wr ? wr_rsp_valid : rd_rsp_valid)) tick();
        snapshot=rd_rsp_data; refs_before=refreshes;
        repeat(stalls) begin
            tick(); held_cycles++;
            if (!(wr ? wr_rsp_valid : rd_rsp_valid)) $fatal(1,"response withdrawn");
            if(!wr && rd_rsp_data!==snapshot) $fatal(1,"stalled response changed");
        end
        if(stalls>=800 && refreshes<=refs_before+1) $fatal(1,"refresh blocked by response stall");
        if ((wr ? wr_rsp_error : rd_rsp_error)!==expect_error) $fatal(1,"bad error response %h",address);
        if(expect_error) errors++;
        else if(wr) golden[longint'(address>>1)]=data;
        else begin
            if(rd_rsp_data!==golden[longint'(address>>1)])
                $fatal(1,"SDRAM data mismatch addr=%h got=%h expected=%h",address,rd_rsp_data,golden[longint'(address>>1)]);
            checks++;
        end
        @(negedge clk); #1;
        if(wr) wr_rsp_ready=1; else rd_rsp_ready=1;
        tick();
        if(wr) wr_rsp_ready=0; else rd_rsp_ready=0;
    endtask
    initial begin : exercise
        logic [31:0] addr;
        int unsigned value;
        int prior_reads,prior_writes;
        repeat(4) tick(); rst=0;
        while(!init_done) begin
            if(rd_req_ready || wr_req_ready) $fatal(1,"ready before initialization");
            tick();
        end
        if($test$plusargs("BREAK_REFRESH")) begin
            force dut.refresh_age_q=0;
            repeat(1000) tick();
            $fatal(1,"NEGATIVE_TEST did not detect broken refresh");
        end
        // All 25 word-address bits and bank/row/column endpoints, retained
        // together before readback to expose aliasing.
        transfer(1,0,16'ha55a);
        for(int b=0;b<25;b++) transfer(1,32'd2<<b,16'(b*173+19));
        foreach(golden[key]) transfer(0,32'(key<<1),0);
        for(int bank=0;bank<4;bank++) begin
            for(int off=0;off<4;off++) begin
                addr=(32'(bank)<<24)+32'(2044+off*2);
                transfer(1,addr,16'(bank*997+off));
            end
        end
        transfer(1,32'h03fffffe,16'h7e21);
        foreach(golden[key]) transfer(0,32'(key<<1),0);
        for(int b=0;b<16;b++) begin
            transfer(1,100,16'b1<<b); transfer(0,100,0);
            transfer(1,100,~(16'b1<<b)); transfer(0,100,0);
        end
        for(int i=0;i<600;i++) begin
            value=random_word();
            addr={6'b0,value[24:0],1'b0};
            transfer(1,addr,16'(random_word()),int'(random_word()%7));
            transfer(0,addr,0,int'(random_word()%7));
        end
        transfer(1,0,16'hbeef,850);
        transfer(0,0,0,850);
        prior_reads=reads;prior_writes=writes;
        transfer(0,1,0,5,1); transfer(1,3,0,5,1);
        transfer(0,32'h04000000,0,3,1); transfer(1,32'hfffffffe,0,3,1);
        if(reads!=prior_reads || writes!=prior_writes) $fatal(1,"invalid access reached SDRAM pins");
        // Both inputs remain offered; exactly one is accepted at a time.
        repeat(12) begin
            @(negedge clk); #1;
            rd_req_addr=0;wr_req_addr=102;wr_req_data=16'h1234;
            rd_req_valid=1;wr_req_valid=1;
            while(rd_req_valid || wr_req_valid || active) begin
                @(posedge clk);
                if(rd_req_valid && rd_req_ready && wr_req_valid && wr_req_ready) $fatal(1,"double acceptance");
                if(rd_req_valid && rd_req_ready) begin rd_req_valid<=0;dual_requests++; end
                if(wr_req_valid && wr_req_ready) begin wr_req_valid<=0;dual_requests++;end
                if(rd_rsp_valid && rd_rsp_ready) begin
                    if(rd_rsp_data!==16'hbeef || rd_rsp_error) $fatal(1,"dual read mismatch"); checks++;
                end
                if(wr_rsp_valid && wr_rsp_ready && wr_rsp_error) $fatal(1,"dual write error");
                #1;rd_rsp_ready=1;wr_rsp_ready=1;
            end
            rd_rsp_ready=0;wr_rsp_ready=0;
        end
        repeat(1200) tick();
        if(READ_BURST_WORDS==4) begin
            for(int i=0;i<8;i++) transfer(1,32'h400+32'(2*i),16'h7000+16'(i));
            prior_reads=reads;
            transfer(0,32'h406,0);transfer(0,32'h400,0);
            transfer(0,32'h404,0);transfer(0,32'h402,0);
            if(reads-prior_reads!=1) $fatal(1,"BL4 did not reuse all four prefetched words");
            transfer(1,32'h404,16'h5aa5);
            prior_reads=reads;
            transfer(0,32'h400,0);transfer(0,32'h404,0);
            if(reads-prior_reads!=1) $fatal(1,"BL4 write invalidation failed");
            prior_reads=reads;
            transfer(0,32'h408,0);transfer(0,32'h400,0);
            if(reads-prior_reads!=2) $fatal(1,"BL4 tag eviction failed");
        end
        if(max_refresh_gap>390 || refreshes<20) $fatal(1,"refresh coverage missing");
        $display("TMA_SDRAM_CONTROLLER_PASS checks=%0d reads=%0d writes=%0d invalid=%0d held_cycles=%0d dual_requests=%0d refreshes=%0d max_refresh_gap=%0d tac=%0.1f burst_words=%0d read_beats=%0d",checks,reads,writes,errors,held_cycles,dual_requests,refreshes,max_refresh_gap,T_AC,READ_BURST_WORDS,memory.read_beats);
        $finish;
    end
    initial begin #100000000; $fatal(1,"controller watchdog"); end
endmodule
`default_nettype wire
