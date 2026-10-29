`timescale 1ns/1ps
`default_nettype none
module tb_tma_sdram_copy_system #(
    parameter bit PIPELINED=1,
    parameter bit SWIZZLE=0,
    parameter int READ_BURST_WORDS=1
);
    logic clk=0,rst=1;
    always #10 clk=~clk;
    logic desc_valid=0;
    wire desc_ready;
    logic [31:0] desc_src_base=0,desc_dst_base=0;
    logic [15:0] desc_rows=0,desc_cols=0;
    logic [31:0] desc_src_row_stride=0,desc_src_col_stride=0;
    logic [31:0] desc_dst_row_stride=0,desc_dst_col_stride=0;
    logic maint_req_valid=0,maint_req_write=0,maint_req_dst=0,maint_rsp_ready=0;
    logic [31:0] maint_req_addr=0;
    logic [15:0] maint_req_data=0;
    wire maint_req_ready,maint_rsp_valid,maint_rsp_error;
    wire [15:0] maint_rsp_data;
    wire busy,done,error,init_done;
    wire [2:0] error_code;
    wire [31:0] completed_elements,refresh_count,dst_bank_conflict_cycles;
    wire [63:0] elapsed_cycles,read_wait_cycles,write_wait_cycles;
    wire dram_cke,dram_cs_n,dram_ras_n,dram_cas_n,dram_we_n,dram_dq_oe;
    wire [12:0] dram_addr;
    wire [1:0] dram_ba,dram_dqm;
    wire [15:0] dram_dq_out;
    tri [15:0] dq;
    assign dq=dram_dq_oe ? dram_dq_out : 16'hzzzz;
    tma_sdram_copy_system #(.PIPELINED(PIPELINED),.SWIZZLE(SWIZZLE),.READ_BURST_WORDS(READ_BURST_WORDS)) dut (.dram_dq_in(dq),.read_trace(),.*);
    wire dram_clk=~clk;
    integer reads,writes,refreshes,max_refresh_gap;
    tma_sdram_model memory (.dram_clk(dram_clk),.power_reset(rst),.cke(dram_cke),.cs_n(dram_cs_n),
        .ras_n(dram_ras_n),.cas_n(dram_cas_n),.we_n(dram_we_n),.addr(dram_addr),
        .ba(dram_ba),.dqm(dram_dqm),.controller_oe(dram_dq_oe),.dq(dq),.*);
    logic [15:0] golden[4096];
    integer commands=0,checked=0,cases=0,metrics;
    string metrics_name="sdram_copy_metrics.csv";
    function automatic logic [15:0] pattern(input logic [31:0] address);
        return 16'(((address>>1)*73) ^ (address>>13) ^ 32'ha55a);
    endfunction
    task automatic tick(); @(posedge clk); #1; endtask
    task automatic host(input bit wr,input bit dst,input logic [31:0] address,
                        input logic [15:0] data,output logic [15:0] result,
                        input bit bad=0);
        logic [15:0] snapshot;
        @(negedge clk); #1;
        maint_req_valid=1;maint_req_write=wr;maint_req_dst=dst;
        maint_req_addr=address;maint_req_data=data;
        do @(posedge clk); while(!maint_req_ready);
        #1;maint_req_valid=0;
        while(!maint_rsp_valid) tick();
        snapshot=maint_rsp_data;
        if(commands%17==0) repeat(3) begin
            tick();
            if(!maint_rsp_valid || maint_rsp_data!==snapshot) $fatal(1,"host stalled response changed");
        end
        if(maint_rsp_error!==bad) $fatal(1,"host error mismatch addr=%h",address);
        result=maint_rsp_data;
        @(negedge clk); #1;maint_rsp_ready=1;
        tick();maint_rsp_ready=0;commands++;
    endtask
    task automatic copy_case(input string name,input logic [31:0] sb,db,
        input int rows,cols,input logic [31:0] srs,scs,drs,dcs,
        input int expected_error=0);
        logic [15:0] value;
        logic [63:0] sa,da;
        int valid_count,timeout_count,reads_before,beats_before;
        logic [31:0] previous_refresh;
        bit stopped;
        for(int w=0;w<4096;w++) begin
            golden[w]=16'(w ^ 16'hca71);
            host(1,1,32'(w*2),golden[w],value);
        end
        valid_count=0;stopped=0;
        for(int r=0;r<rows;r++) for(int c=0;c<cols;c++) begin
            sa=64'(sb)+64'(r)*srs+64'(c)*scs;
            da=64'(db)+64'(r)*drs+64'(c)*dcs;
            if(expected_error!=1 && expected_error!=2 && !stopped) begin
                if(sa>=67108864 || da>=8192) stopped=1;
                else begin
                    host(1,0,32'(sa),pattern(32'(sa)),value);
                    golden[da>>1]=pattern(32'(sa)); valid_count++;
                end
            end
        end
        // Start every descriptor at the same refresh phase in every engine and
        // layout run. Host execution and earlier descriptors cannot bias it.
        previous_refresh=refresh_count;
        while(refresh_count==previous_refresh) tick();
        repeat(8) tick();
        @(negedge clk); #1;
        desc_src_base=sb;desc_dst_base=db;desc_rows=16'(rows);desc_cols=16'(cols);
        desc_src_row_stride=srs;desc_src_col_stride=scs;
        desc_dst_row_stride=drs;desc_dst_col_stride=dcs;desc_valid=1;
        reads_before=reads;beats_before=memory.read_beats;
        do @(posedge clk); while(!desc_ready);
        #1;desc_valid=0;timeout_count=0;
        while(!done) begin
            if(maint_req_ready) $fatal(1,"host admitted during copy");
            tick();timeout_count++;
            if(timeout_count>100000) $fatal(1,"copy timeout");
        end
        if(error_code!==3'(expected_error) || error!==(expected_error!=0) || completed_elements!=valid_count)
            $fatal(1,"copy status case=%s code=%0d count=%0d wanted=%0d",name,error_code,completed_elements,valid_count);
        $fdisplay(metrics,"%s,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d",name,PIPELINED,SWIZZLE,completed_elements,error_code,elapsed_cycles,refresh_count,READ_BURST_WORDS,reads-reads_before,memory.read_beats-beats_before);
        tick();
        for(int w=0;w<4096;w++) begin
            host(0,1,32'(w*2),0,value);
            if(value!==golden[w]) $fatal(1,"destination mismatch case=%s word=%0d got=%h expected=%h",name,w,value,golden[w]);
            checked++;
        end
        cases++;
    endtask
    initial begin
        logic [15:0] value;
        if($value$plusargs("METRICS=%s",metrics_name)) begin end
        metrics=$fopen(metrics_name,"w");
        if(!metrics) $fatal(1,"metrics open failed");
        $fdisplay(metrics,"name,pipelined,swizzle,completed_elements,error_code,elapsed_cycles,refresh_count,read_burst_words,read_commands,read_beats");
        repeat(4) tick();rst=0;
        while(!init_done) begin
            if(desc_ready || maint_req_ready) $fatal(1,"control ready before init"); tick();
        end
        host(0,0,1,0,value,1);host(1,0,32'h04000000,0,value,1);
        host(0,1,8192,0,value,1);host(1,1,1,0,value,1);
        copy_case("last_word",32'h03fffffe,0,1,1,2,2,2,2);
        copy_case("row_crossing",2040,0,1,16,32,2,32,2);
        copy_case("copy32",0,0,32,32,64,2,64,2);
        copy_case("transpose32",32'h03fff800,0,32,32,64,2,2,64);
        copy_case("padded",32'h020007f8,100,8,16,40,2,48,2);
        copy_case("column_gather",32'h03000000,0,32,8,2,2048,16,2);
        copy_case("broadcast",32'h01000000,0,1,32,64,0,64,2);
        copy_case("small_transpose",32'h010007f8,10,3,5,14,2,2,10);
        copy_case("alignment",1,0,1,4,8,2,8,2,2);
        copy_case("empty",0,0,0,4,8,2,8,2,1);
        copy_case("late_destination_bounds",0,8190,1,2,4,2,4,2,3);
        copy_case("late_source_bounds",32'h03fffffe,0,1,2,4,2,4,2,3);
        $fclose(metrics);
        $display("TMA_SDRAM_COPY_PASS cases=%0d destination_checks=%0d host_commands=%0d pipelined=%0d swizzle=%0d sdram_reads=%0d sdram_writes=%0d refreshes=%0d max_refresh_gap=%0d",cases,checked,commands,PIPELINED,SWIZZLE,reads,writes,refreshes,max_refresh_gap);
        $finish;
    end
    initial begin #100000000; $fatal(1,"integration watchdog"); end
endmodule
`default_nettype wire
