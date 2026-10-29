`timescale 1ns/1ps
package tma_dpi_pkg;
    import uvm_pkg::*;
    import tma_uvm_pkg::*;
    import tma_mutation_pkg::*;
    `include "uvm_macros.svh"
    `uvm_analysis_imp_decl(_cpp)
    import "DPI-C" function chandle tma_ref_create(input int unsigned src_bytes,dst_bytes);
    import "DPI-C" function void tma_ref_destroy(input chandle handle);
    import "DPI-C" function string tma_ref_error(input chandle handle);
    import "DPI-C" function int unsigned tma_ref_reset(input chandle handle);
    import "DPI-C" function int unsigned tma_ref_seed(input chandle handle,input int unsigned dst,addr,data);
    import "DPI-C" function int unsigned tma_ref_read(input chandle handle,input int unsigned dst,addr,output int unsigned data);
    import "DPI-C" function int unsigned tma_ref_begin(input chandle handle,input int unsigned sb,db,rows,cols,srs,scs,drs,dcs);
    import "DPI-C" function int unsigned tma_ref_beat(input chandle handle,input int unsigned index,output int unsigned src,dst,data);
    import "DPI-C" function int unsigned tma_ref_prediction(input chandle handle,input int unsigned sb,db,rows,cols,srs,scs,drs,dcs);
    import "DPI-C" function int unsigned tma_ref_event(input chandle handle,input int unsigned kind,addr,data,error,count,code);
    import "DPI-C" function longint unsigned tma_ref_metric(input chandle handle,input int unsigned which);
    import "DPI-C" function longint unsigned tma_ref_clock_ns();
    import "DPI-C" function longint unsigned tma_ref_peak_bytes();
    import "DPI-C" function int unsigned tma_ref_noop(input int unsigned value);

    // Subclass only reuses acceptance counters/reporting. Expected memory,
    // addresses, data, transaction ordering and committed state live in C++.
    // The inherited SV observations port is never connected in cpp mode.
    class tma_cpp_scoreboard extends tma_scoreboard;
        `uvm_component_utils(tma_cpp_scoreboard)
        uvm_analysis_imp_cpp #(tma_observation,tma_cpp_scoreboard) cpp_observations;
        chandle native_model;
        function new(string name,uvm_component parent);
            super.new(name,parent);cpp_observations=new("cpp_observations",this);
        endfunction
        function void build_phase(uvm_phase phase);
            super.build_phase(phase);
            native_model=tma_ref_create(67108864,8192);
            if(native_model==null) `uvm_fatal("TMA_CPP_API",tma_ref_error(native_model))
            model_check(tma_ref_reset(native_model));
        endfunction
        function void model_check(int unsigned code);
            string id;
            case(code)
                0:return;
                4:id="TMA_CPP_READ_ADDRESS";
                5:id="TMA_CPP_READ_DATA";
                6:id="TMA_CPP_WRITE_DATA";
                7:id="TMA_CPP_WRITE_ERROR";
                8:id="TMA_CPP_STATUS";
                9:id="TMA_CPP_PENDING";
                11:id="TMA_CPP_READ_COUNT";
                12:id="TMA_CPP_WRITE_COUNT";
                13:id="TMA_CPP_RESPONSE";
                default:begin `uvm_fatal("TMA_CPP_API",tma_ref_error(native_model)) return;end
            endcase
            `uvm_error(id,tma_ref_error(native_model))
        endfunction
        function void write_cpp(tma_observation e);
            tma_item command;
            bit bad;
            int unsigned expected_data;
            case(e.kind)
                MREQ:maintenance_pending.push_back(e.item);
                MRSP:begin
                    if(maintenance_pending.size()==0) begin `uvm_error("TMA_CPP_RESPONSE","Maintenance response without request") return;end
                    command=maintenance_pending.pop_front();
                    bad=command.addr[0] || (command.dst ? command.addr>=8192:command.addr>=67108864);
                    if(e.error!==bad) begin `uvm_error("TMA_CPP_MAINT_ERROR","Maintenance address-error response differs") return;end
                    if(!bad) begin
                        if(command.op==HOST_WRITE)
                            model_check(tma_ref_seed(native_model,int'(command.dst),command.addr,32'(16'(command.data))));
                        else begin
                            model_check(tma_ref_read(native_model,int'(command.dst),command.addr,expected_data));
                            if(e.data!==16'(expected_data))
                                `uvm_error("TMA_CPP_MEMORY_DATA",$sformatf("Maintenance addr=%h data=%h expected=%h",command.addr,e.data,16'(expected_data)))
                            memory_checks++;
                        end
                    end
                end
                DESC:model_check(tma_ref_begin(native_model,e.item.sb,e.item.db,e.item.rows,e.item.cols,e.item.srs,e.item.scs,e.item.drs,e.item.dcs));
                RD_REQ:begin
                    if($isunknown(e.addr)) begin `uvm_error("TMA_CPP_READ_ADDRESS","DMA read address contains X/Z") return;end
                    model_check(tma_ref_event(native_model,0,e.addr,0,0,0,0));
                end
                RD_RSP:begin
                    if($isunknown({e.data,e.error})) begin `uvm_error("TMA_CPP_READ_DATA","DMA read data/error contains X/Z") return;end
                    model_check(tma_ref_event(native_model,1,0,32'(e.data),32'(e.error),0,0));read_checks++;
                end
                WR_REQ:begin
                    if($isunknown({e.addr,e.data})) begin `uvm_error("TMA_CPP_WRITE_DATA","DMA write address/data contains X/Z") return;end
                    model_check(tma_ref_event(native_model,2,e.addr,32'(e.data),0,0,0));write_checks++;
                end
                WR_RSP:begin
                    if($isunknown(e.error)) begin `uvm_error("TMA_CPP_WRITE_ERROR","DMA write error contains X/Z") return;end
                    model_check(tma_ref_event(native_model,3,0,0,32'(e.error),0,0));
                end
                DONE:begin
                    if($isunknown({e.code,e.error,e.count})) begin `uvm_error("TMA_CPP_STATUS","Completion contains X/Z") return;end
                    model_check(tma_ref_event(native_model,4,0,0,32'(e.error),e.count,32'(e.code)));descriptors++;
                end
            endcase
        endfunction
        function void check_phase(uvm_phase phase);
            super.check_phase(phase);
            model_check(tma_ref_event(native_model,5,0,0,0,0,0));
        endfunction
        function void report_phase(uvm_phase phase);
            `uvm_info("TMA_CPP_METRICS",$sformatf("calls=%0d api_ns=%0d predict_ns=%0d process_peak_bytes=%0d",tma_ref_metric(native_model,0),tma_ref_metric(native_model,1),tma_ref_metric(native_model,2),tma_ref_peak_bytes()),UVM_NONE)
        endfunction
        function void final_phase(uvm_phase phase);
            tma_ref_destroy(native_model);native_model=null;
        endfunction
    endclass

    class tma_sv_baseline extends tma_scoreboard;
        tma_scoreboard acceptance;
        function new(string name,uvm_component parent);super.new(name,parent);endfunction
        function void check_phase(uvm_phase phase);
            planned_descriptors=acceptance.planned_descriptors;super.check_phase(phase);
        endfunction
    endclass

    class tma_cpp_env extends tma_env;
        `uvm_component_utils(tma_cpp_env)
        tma_sv_baseline sv_baseline;
        function new(string name,uvm_component parent);super.new(name,parent);endfunction
        function void build_phase(uvm_phase phase);
            string mode="dual";
            super.build_phase(phase);void'($value$plusargs("TMA_CHECKER=%s",mode));
            if(mode=="dual") begin sv_baseline=new("sv_baseline",this);sv_baseline.acceptance=scoreboard;end
        endfunction
        function void connect_phase(uvm_phase phase);
            tma_cpp_scoreboard cpp;
            if(!$cast(cpp,scoreboard)) `uvm_fatal("TMA_CPP_CONFIG","C++ scoreboard instance override missing")
            agent.monitor.ap.connect(cpp.cpp_observations);
            dma_monitor.ap.connect(cpp.cpp_observations);
            agent.monitor.ap.connect(coverage.analysis_export);
            if(sv_baseline!=null) begin
                agent.monitor.ap.connect(sv_baseline.observations);dma_monitor.ap.connect(sv_baseline.observations);
            end
        endfunction
    endclass

    class tma_dpi_test extends tma_uvm_test;
        `uvm_component_utils(tma_dpi_test)
        function new(string name,uvm_component parent);super.new(name,parent);endfunction
        function void build_phase(uvm_phase phase);
            string mode="dual";int probes=0;
            void'($value$plusargs("TMA_CHECKER=%s",mode));
            void'($value$plusargs("TMA_MUTATION_PROBES=%d",probes));
            if(!(mode inside {"sv","cpp","dual"})) `uvm_fatal("TMA_CPP_CONFIG","Unknown checker mode")
            if(mode!="sv") begin
                tma_env::type_id::set_type_override(tma_cpp_env::get_type());
                tma_scoreboard::type_id::set_inst_override(tma_cpp_scoreboard::get_type(),"uvm_test_top.env.scoreboard");
            end
            if(probes) tma_regression_sequence::type_id::set_type_override(tma_mutation_sequence::get_type());
            super.build_phase(phase);
            `uvm_info("TMA_CHECKER_MODE",mode,UVM_NONE)
        endfunction
        function void report_phase(uvm_phase phase);
            super.report_phase(phase);
            `uvm_info("TMA_PROCESS_METRICS",$sformatf("process_peak_bytes=%0d",tma_ref_peak_bytes()),UVM_NONE)
        endfunction
    endclass
endpackage
