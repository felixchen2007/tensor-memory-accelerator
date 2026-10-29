class tma_driver extends uvm_driver #(tma_item);
    `uvm_component_utils(tma_driver)
    virtual tma_uvm_if vif;
    function new(string name,uvm_component parent);super.new(name,parent);endfunction
    function void build_phase(uvm_phase phase);
        super.build_phase(phase);
        if(!uvm_config_db#(virtual tma_uvm_if)::get(this,"","vif",vif))
            `uvm_fatal("TMA_CONFIG","Driver virtual interface is missing")
    endfunction
    task host(bit wr,bit dst,bit [31:0] addr,bit [15:0] data,int hold_cycles);
        int timeout_count=0;
        vif.cb.maint_req_write<=wr;vif.cb.maint_req_dst<=dst;
        vif.cb.maint_req_addr<=addr;vif.cb.maint_req_data<=data;
        vif.cb.maint_rsp_ready<=(hold_cycles==0);vif.cb.maint_req_valid<=1;
        do begin
            @(vif.cb);timeout_count++;
            if(timeout_count>100000) `uvm_fatal("TMA_TIMEOUT","Maintenance request blocked")
        end while(vif.cb.maint_req_ready!==1'b1);
        vif.cb.maint_req_valid<=0;timeout_count=0;
        while(vif.cb.maint_rsp_valid!==1'b1) begin
            @(vif.cb);timeout_count++;
            if(timeout_count>100000) `uvm_fatal("TMA_TIMEOUT","Maintenance response missing")
        end
        if(hold_cycles!=0) begin
            repeat(hold_cycles) @(vif.cb);
            vif.cb.maint_rsp_ready<=1;@(vif.cb);
        end
        vif.cb.maint_rsp_ready<=0;
    endtask
    task descriptor(tma_item item);
        int timeout_count=0;
        vif.cb.desc_src_base<=item.sb;vif.cb.desc_dst_base<=item.db;
        vif.cb.desc_rows<=item.rows;vif.cb.desc_cols<=item.cols;
        vif.cb.desc_src_row_stride<=item.srs;vif.cb.desc_src_col_stride<=item.scs;
        vif.cb.desc_dst_row_stride<=item.drs;vif.cb.desc_dst_col_stride<=item.dcs;
        vif.cb.desc_valid<=1;
        do begin
            @(vif.cb);timeout_count++;
            if(timeout_count>100000) `uvm_fatal("TMA_TIMEOUT","Descriptor request blocked")
        end while(vif.cb.desc_ready!==1'b1);
        vif.cb.desc_valid<=0;
        fork
            begin
                int done_timeout=0;
                do begin
                    @(vif.cb);done_timeout++;
                    if(done_timeout>100000) `uvm_fatal("TMA_TIMEOUT","Descriptor never completed")
                end while(vif.cb.done!==1'b1);
            end
            begin
                // A valid maintenance request must remain blocked during DMA,
                // then be accepted after completion. It reads the resulting RAM.
                if(item.probe_busy) host(0,1,0,0,item.stall_cycles);
            end
        join
    endtask
    task run_phase(uvm_phase phase);
        vif.cb.desc_valid<=0;vif.cb.maint_req_valid<=0;vif.cb.maint_rsp_ready<=0;
        do @(vif.cb); while(vif.cb.rst || !vif.cb.init_done);
        forever begin
            seq_item_port.get_next_item(req);
            case(req.op)
                HOST_WRITE:host(1,req.dst,req.addr,16'(req.data),req.stall_cycles);
                HOST_READ:host(0,req.dst,req.addr,0,req.stall_cycles);
                DESCRIPTOR:descriptor(req);
                WAIT_REFRESH:repeat(400) @(vif.cb);
                DELAY:repeat(req.delay_cycles) @(vif.cb);
            endcase
            seq_item_port.item_done();
        end
    endtask
endclass

class tma_host_monitor extends uvm_monitor;
    `uvm_component_utils(tma_host_monitor)
    virtual tma_uvm_if vif;
    uvm_analysis_port #(tma_observation) ap;
    bit req_stalled,desc_stalled,rsp_stalled,blocked;
    logic [49:0] held_request;
    logic [223:0] held_descriptor;
    logic [16:0] held_response;
    int response_stalls;
    function new(string name,uvm_component parent);super.new(name,parent);ap=new("ap",this);endfunction
    function void build_phase(uvm_phase phase);
        if(!uvm_config_db#(virtual tma_uvm_if)::get(this,"","vif",vif))
            `uvm_fatal("TMA_CONFIG","Host monitor virtual interface is missing")
    endfunction
    task run_phase(uvm_phase phase);
        forever begin
            tma_observation event_item;
            logic [49:0] request_bits;
            logic [223:0] descriptor_bits;
            @(vif.mon);
            request_bits={vif.mon.maint_req_write,vif.mon.maint_req_dst,vif.mon.maint_req_addr,vif.mon.maint_req_data};
            descriptor_bits={vif.mon.desc_src_base,vif.mon.desc_dst_base,vif.mon.desc_rows,vif.mon.desc_cols,
                vif.mon.desc_src_row_stride,vif.mon.desc_src_col_stride,vif.mon.desc_dst_row_stride,vif.mon.desc_dst_col_stride};
            if(vif.mon.rst) begin
                req_stalled=0;desc_stalled=0;rsp_stalled=0;response_stalls=0;blocked=0;
                continue;
            end
            if(!vif.mon.init_done && (vif.mon.desc_ready || vif.mon.maint_req_ready))
                `uvm_error("TMA_EARLY_READY","Control interface ready before SDRAM initialization")
            if(vif.mon.busy && vif.mon.maint_req_ready)
                `uvm_error("TMA_BUSY","Maintenance admitted while DMA is busy")
            if(req_stalled && (vif.mon.maint_req_valid!==1 || request_bits!==held_request))
                `uvm_error("TMA_HOST_STABILITY","Stalled maintenance request changed")
            if(desc_stalled && (vif.mon.desc_valid!==1 || descriptor_bits!==held_descriptor))
                `uvm_error("TMA_DESC_STABILITY","Stalled descriptor changed")
            if(rsp_stalled && (vif.mon.maint_rsp_valid!==1 ||
                    {vif.mon.maint_rsp_error,vif.mon.maint_rsp_data}!==held_response))
                `uvm_error("TMA_RESPONSE_STABILITY","Stalled maintenance response changed")
            if(vif.mon.desc_valid && vif.mon.desc_ready) begin
                event_item=tma_observation::type_id::create("descriptor");event_item.kind=DESC;
                event_item.item=tma_item::type_id::create("accepted_descriptor");
                event_item.item.sb=vif.mon.desc_src_base;event_item.item.db=vif.mon.desc_dst_base;
                event_item.item.rows=vif.mon.desc_rows;event_item.item.cols=vif.mon.desc_cols;
                event_item.item.srs=vif.mon.desc_src_row_stride;event_item.item.scs=vif.mon.desc_src_col_stride;
                event_item.item.drs=vif.mon.desc_dst_row_stride;event_item.item.dcs=vif.mon.desc_dst_col_stride;
                ap.write(event_item);
            end
            if(vif.mon.done) begin
                event_item=tma_observation::type_id::create("completion");event_item.kind=DONE;
                event_item.code=vif.mon.error_code;event_item.error=vif.mon.error;
                event_item.count=vif.mon.completed_elements;ap.write(event_item);
            end
            if(vif.mon.maint_req_valid && vif.mon.maint_req_ready) begin
                event_item=tma_observation::type_id::create("maintenance_request");event_item.kind=MREQ;
                event_item.item=tma_item::type_id::create("accepted_maintenance");
                event_item.item.op=vif.mon.maint_req_write ? HOST_WRITE : HOST_READ;
                event_item.item.dst=vif.mon.maint_req_dst;event_item.item.addr=vif.mon.maint_req_addr;
                event_item.item.data=vif.mon.maint_req_data;ap.write(event_item);
            end
            if(vif.mon.maint_rsp_valid && !vif.mon.maint_rsp_ready) response_stalls++;
            if(vif.mon.maint_rsp_valid && vif.mon.maint_rsp_ready) begin
                event_item=tma_observation::type_id::create("maintenance_response");event_item.kind=MRSP;
                event_item.data=vif.mon.maint_rsp_data;event_item.error=vif.mon.maint_rsp_error;
                event_item.stall=response_stalls;response_stalls=0;ap.write(event_item);
            end
            if(vif.mon.maint_req_valid && !vif.mon.maint_req_ready && vif.mon.busy) begin
                if(!blocked) begin
                    event_item=tma_observation::type_id::create("busy_blocked");event_item.kind=BUSY_BLOCKED;
                    ap.write(event_item);
                end
                blocked=1;
            end else blocked=0;
            req_stalled=vif.mon.maint_req_valid && !vif.mon.maint_req_ready;
            desc_stalled=vif.mon.desc_valid && !vif.mon.desc_ready;
            rsp_stalled=vif.mon.maint_rsp_valid && !vif.mon.maint_rsp_ready;
            held_request=request_bits;held_descriptor=descriptor_bits;
            held_response={vif.mon.maint_rsp_error,vif.mon.maint_rsp_data};
        end
    endtask
endclass

class tma_dma_monitor extends uvm_monitor;
    `uvm_component_utils(tma_dma_monitor)
    virtual tma_uvm_if vif;
    uvm_analysis_port #(tma_observation) ap;
    bit rd_stall,wr_stall,rr_stall,wa_stall;
    logic [31:0] rd_hold;
    logic [47:0] wr_hold;
    logic [16:0] rr_hold;
    logic wa_hold;
    function new(string name,uvm_component parent);super.new(name,parent);ap=new("ap",this);endfunction
    function void build_phase(uvm_phase phase);
        if(!uvm_config_db#(virtual tma_uvm_if)::get(this,"","vif",vif))
            `uvm_fatal("TMA_CONFIG","DMA monitor virtual interface is missing")
    endfunction
    function void send_event(tma_obs_e kind,logic [31:0] addr,logic [15:0] data,logic error);
        tma_observation e=tma_observation::type_id::create("dma_observation");
        e.kind=kind;e.addr=addr;e.data=data;e.error=error;ap.write(e);
    endfunction
    task run_phase(uvm_phase phase);
        forever begin
            @(vif.mon);
            if(vif.mon.rst) begin rd_stall=0;wr_stall=0;rr_stall=0;wa_stall=0;continue;end
            if(rd_stall && (vif.mon.rd_valid!==1 || vif.mon.rd_addr!==rd_hold))
                `uvm_error("TMA_READ_STABILITY","Stalled DMA read request changed")
            if(wr_stall && (vif.mon.wr_valid!==1 || {vif.mon.wr_addr,vif.mon.wr_data}!==wr_hold))
                `uvm_error("TMA_WRITE_STABILITY","Stalled DMA write request changed")
            if(rr_stall && (vif.mon.rd_rsp_valid!==1 || {vif.mon.rd_error,vif.mon.rd_data}!==rr_hold))
                `uvm_error("TMA_READ_RESPONSE_STABILITY","Stalled DMA read response changed")
            if(wa_stall && (vif.mon.wr_rsp_valid!==1 || vif.mon.wr_error!==wa_hold))
                `uvm_error("TMA_WRITE_RESPONSE_STABILITY","Stalled DMA write response changed")
            // Retire old responses before accepting a replacement on the same edge.
            if(vif.mon.rd_rsp_valid && vif.mon.rd_rsp_ready) send_event(RD_RSP,0,vif.mon.rd_data,vif.mon.rd_error);
            if(vif.mon.wr_rsp_valid && vif.mon.wr_rsp_ready) send_event(WR_RSP,0,0,vif.mon.wr_error);
            if(vif.mon.rd_valid && vif.mon.rd_ready) send_event(RD_REQ,vif.mon.rd_addr,0,0);
            if(vif.mon.wr_valid && vif.mon.wr_ready) send_event(WR_REQ,vif.mon.wr_addr,vif.mon.wr_data,0);
            rd_stall=vif.mon.rd_valid && !vif.mon.rd_ready;rd_hold=vif.mon.rd_addr;
            wr_stall=vif.mon.wr_valid && !vif.mon.wr_ready;wr_hold={vif.mon.wr_addr,vif.mon.wr_data};
            rr_stall=vif.mon.rd_rsp_valid && !vif.mon.rd_rsp_ready;rr_hold={vif.mon.rd_error,vif.mon.rd_data};
            wa_stall=vif.mon.wr_rsp_valid && !vif.mon.wr_rsp_ready;wa_hold=vif.mon.wr_error;
        end
    endtask
endclass

class tma_agent extends uvm_agent;
    `uvm_component_utils(tma_agent)
    uvm_sequencer #(tma_item) sequencer;
    tma_driver driver;
    tma_host_monitor monitor;
    function new(string name,uvm_component parent);super.new(name,parent);endfunction
    function void build_phase(uvm_phase phase);
        super.build_phase(phase);
        sequencer=uvm_sequencer#(tma_item)::type_id::create("sequencer",this);
        driver=tma_driver::type_id::create("driver",this);
        monitor=tma_host_monitor::type_id::create("monitor",this);
    endfunction
    function void connect_phase(uvm_phase phase);driver.seq_item_port.connect(sequencer.seq_item_export);endfunction
endclass
