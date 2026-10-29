`timescale 1ns/1ps
package tma_dpi_smoke_pkg;
    import uvm_pkg::*;
    `include "uvm_macros.svh"
    import "DPI-C" function longint unsigned tma_dpi_probe(
        input int unsigned a, input longint unsigned b, output int unsigned value);
    class tma_dpi_smoke_test extends uvm_test;
        `uvm_component_utils(tma_dpi_smoke_test)
        function new(string name,uvm_component parent);super.new(name,parent);endfunction
        task run_phase(uvm_phase phase);
            int unsigned result;
            longint unsigned wide;
            phase.raise_objection(this);
            wide=tma_dpi_probe(32'hfedcba98,64'hffffffffffffffff,result);
            if(result!==32'h5b861fc2 || wide!==64'h00000000fedcba97)
                `uvm_fatal("TMA_DPI_ABI","32/64-bit unsigned or output argument ABI mismatch")
            `uvm_info("TMA_DPI_SMOKE_PASS","C++17 DPI scalar input/output and unsigned wrap verified",UVM_NONE)
            phase.drop_objection(this);
        endtask
    endclass
endpackage
module tb_tma_dpi_smoke;
    import uvm_pkg::*;
    import tma_dpi_smoke_pkg::*;
    initial run_test("tma_dpi_smoke_test");
endmodule
