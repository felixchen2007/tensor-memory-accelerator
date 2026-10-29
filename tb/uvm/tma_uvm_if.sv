`timescale 1ns/1ps
interface tma_uvm_if(input logic clk,input logic rst);
    logic desc_valid=0,desc_ready;
    logic [31:0] desc_src_base=0,desc_dst_base=0;
    logic [15:0] desc_rows=0,desc_cols=0;
    logic [31:0] desc_src_row_stride=0,desc_src_col_stride=0;
    logic [31:0] desc_dst_row_stride=0,desc_dst_col_stride=0;
    logic maint_req_valid=0,maint_req_ready,maint_req_write=0,maint_req_dst=0;
    logic [31:0] maint_req_addr=0;
    logic [15:0] maint_req_data=0;
    logic maint_rsp_valid,maint_rsp_ready=0,maint_rsp_error;
    logic [15:0] maint_rsp_data;
    logic init_done,busy,done,error;
    logic [2:0] error_code;
    logic [31:0] completed_elements;
    logic [63:0] elapsed_cycles;
    // Passive taps at the engine's actual request/response interfaces.
    // No RAM contents or controller state are exposed to the scoreboard.
    logic rd_valid,rd_ready,rd_rsp_valid,rd_rsp_ready,rd_error;
    logic [31:0] rd_addr;
    logic [15:0] rd_data;
    logic wr_valid,wr_ready,wr_rsp_valid,wr_rsp_ready,wr_error;
    logic [31:0] wr_addr;
    logic [15:0] wr_data;
    clocking cb @(posedge clk);
        default input #1step output #0;
        input rst,init_done,desc_ready,maint_req_ready,maint_rsp_valid,maint_rsp_error,maint_rsp_data;
        input busy,done,error,error_code,completed_elements,elapsed_cycles;
        output desc_valid,desc_src_base,desc_dst_base,desc_rows,desc_cols;
        output desc_src_row_stride,desc_src_col_stride,desc_dst_row_stride,desc_dst_col_stride;
        output maint_req_valid,maint_req_write,maint_req_dst,maint_req_addr,maint_req_data,maint_rsp_ready;
    endclocking
    clocking mon @(posedge clk);
        default input #1step;
        input rst,init_done,desc_valid,desc_ready,desc_src_base,desc_dst_base,desc_rows,desc_cols;
        input desc_src_row_stride,desc_src_col_stride,desc_dst_row_stride,desc_dst_col_stride;
        input maint_req_valid,maint_req_ready,maint_req_write,maint_req_dst,maint_req_addr,maint_req_data;
        input maint_rsp_valid,maint_rsp_ready,maint_rsp_error,maint_rsp_data;
        input busy,done,error,error_code,completed_elements,elapsed_cycles;
        input rd_valid,rd_ready,rd_addr,rd_rsp_valid,rd_rsp_ready,rd_data,rd_error;
        input wr_valid,wr_ready,wr_addr,wr_data,wr_rsp_valid,wr_rsp_ready,wr_error;
    endclocking
endinterface
