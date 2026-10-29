`timescale 1ns/1ps
package tma_uvm_pkg;
    import uvm_pkg::*;
    `include "uvm_macros.svh"
    typedef enum {HOST_WRITE,HOST_READ,DESCRIPTOR,WAIT_REFRESH,DELAY} tma_op_e;
    typedef enum {MREQ,MRSP,DESC,DONE,RD_REQ,RD_RSP,WR_REQ,WR_RSP,BUSY_BLOCKED} tma_obs_e;
    class tma_item extends uvm_sequence_item;
        `uvm_object_utils(tma_item)
        tma_op_e op;
        bit dst,probe_busy;
        bit [31:0] addr,data,sb,db,srs,scs,drs,dcs;
        int unsigned rows,cols,stall_cycles,delay_cycles;
`ifdef TMA_UVM_FULL
        rand int unsigned family,bank,offset,source_row,destination_word,nrows,ncols;
        constraint shapes { family inside {[0:4]};bank inside {[0:3]};offset inside {[0:3]};
            source_row inside {[0:4]};destination_word inside {[0:1024]};
            nrows inside {[1:8]};ncols inside {[1:8]}; }
`else
        int unsigned family,bank,offset,source_row,destination_word,nrows,ncols;
`endif
        function new(string name="tma_item");super.new(name);endfunction
        function void derive();
            op=DESCRIPTOR;rows=nrows;cols=ncols;
            sb=(bank<<24)+source_row*2048+offset*2;db=destination_word*2;
            srs=cols*2;scs=2;drs=cols*2;dcs=2;
            case(family)
                1:begin drs=2;dcs=rows*2;end
                2:begin srs=cols*2+6;drs=cols*2+10;end
                3:begin srs=2;scs=2048;end
                4:scs=0;
            endcase
        endfunction
    endclass
    class tma_observation extends uvm_sequence_item;
        `uvm_object_utils(tma_observation)
        tma_obs_e kind;
        tma_item item;
        logic [31:0] addr,count;
        logic [15:0] data;
        logic error;
        logic [2:0] code;
        int stall;
        function new(string name="tma_observation");super.new(name);endfunction
    endclass
    typedef struct packed {logic [31:0] src,dst;logic [15:0] data;} tma_expected_beat;
    `include "tma_uvm_agent.svh"
    `include "tma_uvm_scoreboard.svh"
    `include "tma_uvm_coverage.svh"
    `include "tma_uvm_sequences.svh"
    class tma_env extends uvm_env;
        `uvm_component_utils(tma_env)
        tma_agent agent;
        tma_dma_monitor dma_monitor;
        tma_scoreboard scoreboard;
        tma_coverage coverage;
        function new(string name,uvm_component parent);super.new(name,parent);endfunction
        function void build_phase(uvm_phase phase);
            super.build_phase(phase);
            agent=tma_agent::type_id::create("agent",this);
            dma_monitor=tma_dma_monitor::type_id::create("dma_monitor",this);
            scoreboard=tma_scoreboard::type_id::create("scoreboard",this);
            coverage=tma_coverage::type_id::create("coverage",this);
        endfunction
        function void connect_phase(uvm_phase phase);
            agent.monitor.ap.connect(scoreboard.observations);
            agent.monitor.ap.connect(coverage.analysis_export);
            dma_monitor.ap.connect(scoreboard.observations);
        endfunction
    endclass
    class tma_uvm_test extends uvm_test;
        `uvm_component_utils(tma_uvm_test)
        tma_env env;
        int pipelined,swizzle,burst_words;
        function new(string name,uvm_component parent);super.new(name,parent);endfunction
        function void build_phase(uvm_phase phase);
            super.build_phase(phase);env=tma_env::type_id::create("env",this);
            void'(uvm_config_db#(int)::get(this,"","pipelined",pipelined));
            void'(uvm_config_db#(int)::get(this,"","swizzle",swizzle));
            void'(uvm_config_db#(int)::get(this,"","burst_words",burst_words));
        endfunction
        function void end_of_elaboration_phase(uvm_phase phase);uvm_top.print_topology();endfunction
        task run_phase(uvm_phase phase);
            tma_regression_sequence seq=tma_regression_sequence::type_id::create("seq");
            phase.raise_objection(this);seq.start(env.agent.sequencer);
            env.scoreboard.planned_descriptors=seq.descriptor_count;
            phase.drop_objection(this);
        endtask
        function void report_phase(uvm_phase phase);
            uvm_report_server server=uvm_report_server::get_server();
            if(server.get_severity_count(UVM_ERROR)==0 && server.get_severity_count(UVM_FATAL)==0)
                `uvm_info("TMA_UVM_PASS",$sformatf("descriptors=%0d read_checks=%0d write_checks=%0d memory_checks=%0d bank_family_bins=%0d pipelined=%0d swizzle=%0d burst_words=%0d",env.scoreboard.descriptors,env.scoreboard.read_checks,env.scoreboard.write_checks,env.scoreboard.memory_checks,env.coverage.bank_family_count(),pipelined,swizzle,burst_words),UVM_NONE)
        endfunction
    endclass
endpackage
