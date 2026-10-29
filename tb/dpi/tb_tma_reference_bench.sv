`timescale 1ns/1ps
package tma_reference_bench_pkg;
    import uvm_pkg::*;
    import tma_uvm_pkg::*;
    import tma_dpi_pkg::*;
    `include "uvm_macros.svh"
    // This is a model-computation microbenchmark, not an RTL acceptance test.
    class tma_prediction_bench_scoreboard extends tma_scoreboard;
        function new(string name,uvm_component parent);super.new(name,parent);endfunction
        function void check_phase(uvm_phase phase);endfunction
    endclass
    class tma_reference_bench_test extends uvm_test;
        `uvm_component_utils(tma_reference_bench_test)
        tma_prediction_bench_scoreboard sv_model;
        chandle cpp_model;
        function new(string name,uvm_component parent);super.new(name,parent);endfunction
        function void build_phase(uvm_phase phase);
            super.build_phase(phase);sv_model=new("prediction_only",this);
        endfunction
        task run_phase(uvm_phase phase);
            int sides[5]='{1,8,16,32,64};
            tma_item d;
            int unsigned status,sa,da,data,checksum=0,sv_checksum=0;
            longint unsigned start_ns,sv_ns,cpp_ns,base_ns,dpi_ns;
            phase.raise_objection(this);
            cpp_model=tma_ref_create(67108864,8192);
            if(cpp_model==null) `uvm_fatal("TMA_CPP_API",tma_ref_error(cpp_model))
            for(int word=0;word<4096;word++) begin
                sv_model.source_memory[64'(word)]=16'((word*73)^16'ha55a);
                status=tma_ref_seed(cpp_model,0,32'(word*2),32'(sv_model.source_memory[64'(word)]));
                if(status) `uvm_fatal("TMA_CPP_API",tma_ref_error(cpp_model))
            end
            foreach(sides[s]) begin
                d=tma_item::type_id::create("shape");d.sb=0;d.db=0;d.rows=sides[s];d.cols=sides[s];
                d.srs=32'(sides[s]*2);d.scs=2;d.drs=2;d.dcs=d.srs;
                repeat(3) begin
                    sv_model.predict(d);
                    status=tma_ref_prediction(cpp_model,d.sb,d.db,d.rows,d.cols,d.srs,d.scs,d.drs,d.dcs);
                end
                for(int repetition=0;repetition<7;repetition++) begin
                    start_ns=tma_ref_clock_ns();
                    repeat(100) sv_model.predict(d);
                    sv_ns=tma_ref_clock_ns()-start_ns;
                    start_ns=tma_ref_clock_ns();
                    repeat(100) status=tma_ref_prediction(cpp_model,d.sb,d.db,d.rows,d.cols,d.srs,d.scs,d.drs,d.dcs);
                    cpp_ns=tma_ref_clock_ns()-start_ns;
                    if(status || tma_ref_metric(cpp_model,3)!=sv_model.expected.size() || tma_ref_metric(cpp_model,4)!=0)
                        `uvm_fatal("TMA_BENCH_MISMATCH","Prediction status/count mismatch")
                    foreach(sv_model.expected[i]) begin
                        status=tma_ref_beat(cpp_model,32'(i),sa,da,data);
                        if(status || sa!==sv_model.expected[i].src || da!==sv_model.expected[i].dst || 16'(data)!==sv_model.expected[i].data)
                            `uvm_fatal("TMA_BENCH_MISMATCH","Predicted address/data mismatch")
                    end
                    $display("TMA_PREDICT_BENCH side=%0d repetition=%0d loops=100 sv_ns=%0d dpi_ns=%0d",sides[s],repetition,sv_ns,cpp_ns);
                end
            end
            for(int repetition=0;repetition<7;repetition++) begin
                checksum=0;sv_checksum=0;
                start_ns=tma_ref_clock_ns();
                for(int i=0;i<1000000;i++)
                    sv_checksum={sv_checksum[30:0],sv_checksum[31]}^32'(i)^32'ha55aa55a;
                base_ns=tma_ref_clock_ns()-start_ns;
                start_ns=tma_ref_clock_ns();
                for(int i=0;i<1000000;i++)
                    checksum={checksum[30:0],checksum[31]}^tma_ref_noop(32'(i));
                dpi_ns=tma_ref_clock_ns()-start_ns;
                if(checksum!==sv_checksum) `uvm_fatal("TMA_BENCH_MISMATCH","DPI dispatch checksum differs from equivalent SV body")
                $display("TMA_DPI_OVERHEAD repetition=%0d calls=1000000 sv_body_ns=%0d dpi_body_ns=%0d checksum=%0d",repetition,base_ns,dpi_ns,checksum);
            end
            tma_ref_destroy(cpp_model);cpp_model=null;
            `uvm_info("TMA_REFERENCE_BENCH_PASS",$sformatf("prediction_shapes=5 repetitions=7 process_peak_bytes=%0d",tma_ref_peak_bytes()),UVM_NONE)
            phase.drop_objection(this);
        endtask
    endclass
endpackage
module tb_tma_reference_bench;
    import uvm_pkg::*;
    import tma_reference_bench_pkg::*;
    initial run_test("tma_reference_bench_test");
endmodule
