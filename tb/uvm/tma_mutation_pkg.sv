`timescale 1ns/1ps
// Campaign-only stimulus. The production RTL and existing UVM suite are unchanged.
package tma_mutation_pkg;
    import uvm_pkg::*;
    import tma_uvm_pkg::*;
    `include "uvm_macros.svh"

    class tma_mutation_sequence extends tma_regression_sequence;
        `uvm_object_utils(tma_mutation_sequence)
        function new(string name="tma_mutation_sequence"); super.new(name); endfunction
        task body();
            // Seed distinct words with the same column in different banks/rows,
            // then read without intervening writes. Per-descriptor source
            // seeding invalidates the line and would mask a truncated tag.
            host_item=tma_item::type_id::create("mutation_host_command");
            `uvm_info("TMA_MUTATION_PROBES","bank/row tags, write invalidation and every burst offset",UVM_NONE)
            host(1,0,32'h00000400,16'h1357);
            host(1,0,32'h01000400,16'h2468);
            host(1,0,32'h00000c00,16'h369c);
            host(0,0,32'h00000400);
            host(0,0,32'h01000400);
            host(0,0,32'h00000400);
            host(0,0,32'h00000c00);
            host(0,0,32'h00000400);
            host(1,0,32'h00000400,16'h55aa);
            host(0,0,32'h00000400);
            for(int offset=0;offset<4;offset++)
                host(1,0,32'h00000400+32'(offset*2),16'h6a00+16'(offset));
            for(int offset=0;offset<4;offset++)
                host(0,0,32'h00000400+32'(offset*2));
            `uvm_info("TMA_MUTATION_PROBES_DONE","All directed cache probes completed",UVM_NONE)
            super.body();
        endtask
    endclass

    class tma_mutation_test extends tma_uvm_test;
        `uvm_component_utils(tma_mutation_test)
        function new(string name,uvm_component parent); super.new(name,parent); endfunction
        function void build_phase(uvm_phase phase);
            tma_regression_sequence::type_id::set_type_override(tma_mutation_sequence::get_type());
            super.build_phase(phase);
        endfunction
    endclass
endpackage
