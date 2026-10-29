`default_nettype none

// Isolate local RAM and SDRAM before exercising the tensor loader. All accesses
// use the public maintenance/descriptor interfaces; no hierarchical RAM access.
module tma_sdram_selftest #(
    parameter bit PIPELINED=1,
    parameter bit SWIZZLE=0,
    parameter bit TRANSPOSE=1,
    parameter int unsigned READ_BURST_WORDS=1
) (
    input wire clk,rst,
    output wire init_done,
    output logic passed,failed,
    output logic [11:0] checked_words,source_checked_words,scratch_checked_words,
    output logic [2:0] passed_stages,
    output wire [3:0] stage_code,
    output logic [31:0] failure_word,
    output logic [15:0] expected_data,observed_data,
    output logic [3:0] failure_reason,
    output wire [31:0] completed_elements,
    output wire [31:0] refresh_count,
    output wire [63:0] elapsed_cycles,
    output wire dram_cke,dram_cs_n,dram_ras_n,dram_cas_n,dram_we_n,
    output wire [12:0] dram_addr,
    output wire [1:0] dram_ba,dram_dqm,
    output wire [15:0] dram_dq_out,
    output wire dram_dq_oe,
    input wire [15:0] dram_dq_in,
    output wire [255:0] read_trace
);
    typedef enum logic [3:0] {WAIT_INIT,FILL_REQ,FILL_RSP,SOURCE_REQ,SOURCE_RSP,
        SRAM_FILL_REQ,SRAM_FILL_RSP,SRAM_REQ,SRAM_RSP,DESCRIPTOR,COPY_WAIT,
        CHECK_REQ,CHECK_RSP,FINISHED,WAIT_REFRESH} state_t;
    state_t state_q;
    assign stage_code=state_q;
    logic [9:0] index_q;
    logic [31:0] refresh_epoch_q;
    wire desc_ready,maint_req_ready,maint_rsp_valid,maint_rsp_error;
    wire [15:0] maint_rsp_data;
    wire done,error;
    wire [9:0] source_index=TRANSPOSE ? {index_q[4:0],index_q[9:5]} : index_q;
    wire host_write=state_q==FILL_REQ || state_q==SRAM_FILL_REQ;
    wire host_destination=state_q==SRAM_FILL_REQ || state_q==SRAM_REQ || state_q==CHECK_REQ;
    wire host_request=host_write || state_q==SOURCE_REQ || state_q==SRAM_REQ || state_q==CHECK_REQ;
    wire host_response=state_q==FILL_RSP || state_q==SOURCE_RSP || state_q==SRAM_FILL_RSP ||
                       state_q==SRAM_RSP || state_q==CHECK_RSP;
    function automatic logic [15:0] pattern(input logic [9:0] index);
        return (16'(index)*16'd73)^16'ha55a;
    endfunction
    wire [15:0] scratch_pattern=pattern(index_q)^16'h3c69;
    tma_sdram_copy_system #(.PIPELINED(PIPELINED),.SWIZZLE(SWIZZLE),.READ_BURST_WORDS(READ_BURST_WORDS)) system (
        .clk(clk),.rst(rst),.desc_valid(state_q==DESCRIPTOR),.desc_ready(desc_ready),
        .desc_src_base(32'h010007f0),.desc_dst_base(32'd0),.desc_rows(16'd32),.desc_cols(16'd32),
        .desc_src_row_stride(32'd64),.desc_src_col_stride(32'd2),
        .desc_dst_row_stride(TRANSPOSE ? 32'd2 : 32'd64),
        .desc_dst_col_stride(TRANSPOSE ? 32'd64 : 32'd2),
        .maint_req_valid(host_request),.maint_req_ready(maint_req_ready),
        .maint_req_write(host_write),.maint_req_dst(host_destination),
        .maint_req_addr(host_destination ? {21'd0,index_q,1'b0} : 32'h010007f0+{21'd0,index_q,1'b0}),
        .maint_req_data(state_q==SRAM_FILL_REQ ? scratch_pattern : pattern(index_q)),
        .maint_rsp_valid(maint_rsp_valid),.maint_rsp_ready(host_response),
        .maint_rsp_data(maint_rsp_data),.maint_rsp_error(maint_rsp_error),
        .busy(),.done(done),.error(error),.error_code(),.completed_elements(completed_elements),
        .elapsed_cycles(elapsed_cycles),.read_wait_cycles(),.write_wait_cycles(),
        .dst_bank_conflict_cycles(),.*
    );
    always_ff @(posedge clk) begin
        if(rst) begin
            state_q<=WAIT_INIT;index_q<=0;passed<=0;failed<=0;refresh_epoch_q<=0;
            checked_words<=0;source_checked_words<=0;scratch_checked_words<=0;passed_stages<=0;
            failure_word<=0;expected_data<=0;observed_data<=0;failure_reason<=0;
        end else begin
            case(state_q)
                WAIT_INIT: if(init_done) state_q<=SRAM_FILL_REQ;
                SRAM_FILL_REQ: if(maint_req_ready) state_q<=SRAM_FILL_RSP;
                SRAM_FILL_RSP: if(maint_rsp_valid) begin
                    if(maint_rsp_error) begin
                        failed<=1;failure_reason<=7;failure_word<={22'b0,index_q};state_q<=FINISHED;
                    end else if(index_q==1023) begin index_q<=0;state_q<=SRAM_REQ;end
                    else begin index_q<=index_q+1'b1;state_q<=SRAM_FILL_REQ;end
                end
                SRAM_REQ: if(maint_req_ready) state_q<=SRAM_RSP;
                SRAM_RSP: if(maint_rsp_valid) begin
                    if(maint_rsp_error || maint_rsp_data!==scratch_pattern) begin
                        failed<=1;failure_reason<=maint_rsp_error ? 4'd8 : 4'd9;
                        failure_word<={22'b0,index_q};expected_data<=scratch_pattern;
                        observed_data<=maint_rsp_data;state_q<=FINISHED;
                    end else begin
                        scratch_checked_words<=scratch_checked_words+1'b1;
                        if(index_q==1023) begin
                            passed_stages[0]<=1;index_q<=0;state_q<=FILL_REQ;
                        end else begin index_q<=index_q+1'b1;state_q<=SRAM_REQ;end
                    end
                end
                FILL_REQ: if(maint_req_ready) state_q<=FILL_RSP;
                FILL_RSP: if(maint_rsp_valid) begin
                    if(maint_rsp_error) begin
                        failed<=1;failure_reason<=1;failure_word<={22'b0,index_q};state_q<=FINISHED;
                    end else if(index_q==1023) begin index_q<=0;state_q<=SOURCE_REQ;end
                    else begin index_q<=index_q+1'b1;state_q<=FILL_REQ;end
                end
                SOURCE_REQ: if(maint_req_ready) state_q<=SOURCE_RSP;
                SOURCE_RSP: if(maint_rsp_valid) begin
                    if(maint_rsp_error || maint_rsp_data!==pattern(index_q)) begin
                        failed<=1;failure_reason<=maint_rsp_error ? 4'd5 : 4'd6;
                        failure_word<={22'b0,index_q};expected_data<=pattern(index_q);
                        observed_data<=maint_rsp_data;state_q<=FINISHED;
                    end else begin
                        source_checked_words<=source_checked_words+1'b1;
                        if(index_q==1023) begin
                            passed_stages[1]<=1;index_q<=0;
                            refresh_epoch_q<=refresh_count;state_q<=WAIT_REFRESH;
                        end else begin index_q<=index_q+1'b1;state_q<=SOURCE_REQ;end
                    end
                end
                // Start both fitted engine variants at the same refresh phase.
                // Descriptor acceptance is two core edges after refresh launch.
                WAIT_REFRESH: if(refresh_count!=refresh_epoch_q) state_q<=DESCRIPTOR;
                DESCRIPTOR: if(desc_ready) state_q<=COPY_WAIT;
                COPY_WAIT: if(done) begin
                    if(error || completed_elements!=1024) begin failed<=1;failure_reason<=2;state_q<=FINISHED;end
                    else begin passed_stages[2]<=1;state_q<=CHECK_REQ;end
                end
                CHECK_REQ: if(maint_req_ready) state_q<=CHECK_RSP;
                CHECK_RSP: if(maint_rsp_valid) begin
                    if(maint_rsp_error || maint_rsp_data!==pattern(source_index)) begin
                        failed<=1;failure_word<={22'b0,index_q};failure_reason<=maint_rsp_error ? 4'd3 : 4'd4;
                        expected_data<=pattern(source_index);observed_data<=maint_rsp_data;
                        state_q<=FINISHED;
                    end else begin
                        checked_words<=checked_words+1'b1;
                        if(index_q==1023) begin passed<=1;state_q<=FINISHED;end
                        else begin index_q<=index_q+1'b1;state_q<=CHECK_REQ;end
                    end
                end
                default: begin end
            endcase
        end
    end
endmodule
`default_nettype wire
