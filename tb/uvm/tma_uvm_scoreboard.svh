class tma_scoreboard extends uvm_component;
    `uvm_component_utils(tma_scoreboard)
    uvm_analysis_imp #(tma_observation,tma_scoreboard) observations;
    logic [15:0] source_memory [longint unsigned];
    logic [15:0] destination_memory [longint unsigned];
    tma_item maintenance_pending[$];
    tma_expected_beat expected[$],reads_pending[$],writes_pending[$];
    bit descriptor_active;
    int expected_error,read_issued,write_issued,write_committed;
    int descriptors,read_checks,write_checks,memory_checks,planned_descriptors;
    function new(string name,uvm_component parent);
        super.new(name,parent);observations=new("observations",this);
    endfunction
    function void predict(tma_item d);
        longint unsigned sa,da;
        tma_expected_beat beat;
        expected.delete();read_issued=0;write_issued=0;write_committed=0;expected_error=0;
        if(d.rows==0 || d.cols==0) begin expected_error=1;return;end
        if((d.sb|d.db|d.srs|d.scs|d.drs|d.dcs)&1) begin expected_error=2;return;end
        if(d.sb>67108862 || d.srs>67108862 || d.scs>67108862 ||
           d.db>8190 || d.drs>8190 || d.dcs>8190) begin expected_error=3;return;end
        // Independent wide arithmetic, without the RTL address generator or RAM arrays.
        for(int r=0;r<d.rows;r++) for(int c=0;c<d.cols;c++) begin
            sa=64'(d.sb)+64'(r)*64'(d.srs)+64'(c)*64'(d.scs);
            da=64'(d.db)+64'(r)*64'(d.drs)+64'(c)*64'(d.dcs);
            if(sa>=67108864 || da>=8192) begin expected_error=3;return;end
            if(!source_memory.exists(sa>>1))
                `uvm_fatal("TMA_STIMULUS",$sformatf("Descriptor source %h was never seeded",sa))
            beat.src=32'(sa);beat.dst=32'(da);beat.data=source_memory[sa>>1];expected.push_back(beat);
        end
    endfunction
    function void write(tma_observation e);
        tma_item command;
        tma_expected_beat beat;
        bit bad;
        logic [15:0] expected_data;
        longint unsigned key;
        case(e.kind)
            MREQ:maintenance_pending.push_back(e.item);
            MRSP:begin
                if(maintenance_pending.size()==0) begin `uvm_error("TMA_ORPHAN_RESPONSE","Maintenance response without a request") return;end
                command=maintenance_pending.pop_front();key=longint'(command.addr>>1);
                bad=command.addr[0] || (command.dst ? command.addr>=8192 : command.addr>=67108864);
                if(e.error!==bad) `uvm_error("TMA_MAINT_ERROR","Maintenance address-error response is incorrect")
                if(!bad && !e.error) begin
                    if(command.op==HOST_WRITE) begin
                        if(command.dst) destination_memory[key]=16'(command.data);
                        else source_memory[key]=16'(command.data);
                    end else begin
                        if(command.dst) begin
                            if(!destination_memory.exists(key)) `uvm_fatal("TMA_STIMULUS","Unseeded scratchpad read")
                            expected_data=destination_memory[key];
                        end else begin
                            if(!source_memory.exists(key)) `uvm_fatal("TMA_STIMULUS","Unseeded SDRAM read")
                            expected_data=source_memory[key];
                        end
                        if(e.data!==expected_data)
                            `uvm_error("TMA_MEMORY_DATA",$sformatf("Maintenance addr=%h got=%h expected=%h",command.addr,e.data,expected_data))
                        memory_checks++;
                    end
                end
            end
            DESC:begin
                if(descriptor_active || reads_pending.size()!=0 || writes_pending.size()!=0)
                    `uvm_error("TMA_OVERLAP","Descriptor accepted with unfinished work")
                descriptor_active=1;predict(e.item);
            end
            RD_REQ:begin
                if(!descriptor_active || read_issued>=expected.size()) begin
                    `uvm_error("TMA_READ_COUNT","Unexpected DMA read request") return;
                end
                beat=expected[read_issued++];
                if(e.addr!==beat.src) `uvm_error("TMA_READ_ADDRESS",$sformatf("Read addr=%h expected=%h",e.addr,beat.src))
                reads_pending.push_back(beat);
            end
            RD_RSP:begin
                if(reads_pending.size()==0) begin `uvm_error("TMA_READ_ORPHAN","Read response without request") return;end
                beat=reads_pending.pop_front();
                if(e.error!==0 || e.data!==beat.data)
                    `uvm_error("TMA_READ_DATA",$sformatf("DMA read addr=%h got=%h expected=%h error=%b",beat.src,e.data,beat.data,e.error))
                read_checks++;
            end
            WR_REQ:begin
                if(!descriptor_active || write_issued>=expected.size()) begin
                    `uvm_error("TMA_WRITE_COUNT","Unexpected DMA write request") return;
                end
                beat=expected[write_issued++];
                if(e.addr!==beat.dst || e.data!==beat.data)
                    `uvm_error("TMA_WRITE_DATA",$sformatf("DMA write addr=%h data=%h expected_addr=%h data=%h",e.addr,e.data,beat.dst,beat.data))
                writes_pending.push_back(beat);write_checks++;
            end
            WR_RSP:begin
                if(writes_pending.size()==0) begin `uvm_error("TMA_WRITE_ORPHAN","Write response without request") return;end
                beat=writes_pending.pop_front();
                if(e.error!==0) `uvm_error("TMA_WRITE_ERROR","Legal scratchpad write returned an error")
                destination_memory[longint'(beat.dst>>1)]=beat.data;write_committed++;
            end
            DONE:begin
                if(!descriptor_active) `uvm_error("TMA_DONE_ORPHAN","Completion without accepted descriptor")
                if(e.code!==3'(expected_error) || e.error!==(expected_error!=0) || e.count!==32'(expected.size()))
                    `uvm_error("TMA_STATUS",$sformatf("status code=%0d count=%0d expected_code=%0d count=%0d",e.code,e.count,expected_error,expected.size()))
                if(reads_pending.size()!=0 || writes_pending.size()!=0 || read_issued!=expected.size() ||
                   write_issued!=expected.size() || write_committed!=expected.size())
                    `uvm_error("TMA_INCOMPLETE","Completion did not drain exactly the predicted read/write prefix")
                descriptor_active=0;descriptors++;
            end
        endcase
    endfunction
    function void check_phase(uvm_phase phase);
        if(descriptor_active || maintenance_pending.size()!=0 || reads_pending.size()!=0 || writes_pending.size()!=0)
            `uvm_error("TMA_PENDING","Simulation ended with pending transactions")
        if(descriptors!=planned_descriptors || descriptors<34 || read_checks<2600 || memory_checks<20000)
            `uvm_error("TMA_COVERAGE_GAP",$sformatf("Missing planned work descriptors=%0d expected=%0d reads=%0d memory_checks=%0d",descriptors,planned_descriptors,read_checks,memory_checks))
    endfunction
endclass
