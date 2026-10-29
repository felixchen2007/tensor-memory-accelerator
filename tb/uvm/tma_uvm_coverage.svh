class tma_coverage extends uvm_subscriber #(tma_observation);
    `uvm_component_utils(tma_coverage)
    tma_item active_descriptor;
    int bank_family_hits[4][5];
    bit [3:0] offsets,statuses;
    bit [4:0] sizes;
    bit [2:0] stalls;
    bit busy_blocked,long_stall;
`ifdef TMA_UVM_FULL
    covergroup descriptor_cg with function sample(int bank,int offset,int family,int status,int elements);
        option.per_instance=1;
        bank_cp:coverpoint bank {bins banks[]={[0:3]};}
        offset_cp:coverpoint offset {bins offsets[]={[0:3]};}
        family_cp:coverpoint family {bins families[]={[0:4]};}
        status_cp:coverpoint status {bins codes[]={[0:3]};}
        size_cp:coverpoint elements {bins empty_size={0};bins one_element={1};bins size_small={[2:64]};bins size_medium={[65:256]};bins size_large={[257:1024]};}
        bank_family:cross bank_cp,family_cp;
    endgroup
`endif
    function new(string name,uvm_component parent);
        super.new(name,parent);
`ifdef TMA_UVM_FULL
        descriptor_cg=new;
`endif
    endfunction
    function int classify(tma_item d);
        if(d.scs==0) return 4;
        if(d.scs>2) return 3;
        if(d.drs==2 && d.dcs>2) return 1;
        if(d.srs>d.cols*2 || d.drs>d.cols*2) return 2;
        return 0;
    endfunction
    function int bank_family_count();
        int n=0;
        foreach(bank_family_hits[b,f]) if(bank_family_hits[b][f]!=0) n++;
        return n;
    endfunction
    function void write(tma_observation t);
        int bank,family,elements,offset;
        if(t.kind==DESC) active_descriptor=t.item;
        if(t.kind==BUSY_BLOCKED) busy_blocked=1;
        if(t.kind==MRSP) begin
            if(t.stall==0) stalls[0]=1;
            else if(t.stall<=2) stalls[1]=1;
            else stalls[2]=1;
            if(t.stall>=800) long_stall=1;
        end
        if(t.kind==DONE && active_descriptor!=null) begin
            bank=int'(active_descriptor.sb[25:24]);family=classify(active_descriptor);
            offset=int'(active_descriptor.sb[2:1]);elements=active_descriptor.rows*active_descriptor.cols;
            bank_family_hits[bank][family]++;offsets[offset]=1;
            if(t.code<=3) statuses[t.code]=1;
            if(elements==0) sizes[0]=1;
            else if(elements==1) sizes[1]=1;
            else if(elements<=64) sizes[2]=1;
            else if(elements<=256) sizes[3]=1;
            else sizes[4]=1;
`ifdef TMA_UVM_FULL
            descriptor_cg.sample(bank,offset,family,int'(t.code),elements);
`endif
            active_descriptor=null;
        end
    endfunction
    function void check_phase(uvm_phase phase);
        if(bank_family_count()!=20 || offsets!=4'hf || statuses!=4'hf || sizes!=5'h1f ||
           stalls!=3'b111 || !busy_blocked || !long_stall)
            `uvm_error("TMA_FEATURE_GAP",$sformatf("scenario bins bank_family=%0d/20 offsets=%b statuses=%b sizes=%b stalls=%b busy=%b long_hold=%b",bank_family_count(),offsets,statuses,sizes,stalls,busy_blocked,long_stall))
    endfunction
    function void report_phase(uvm_phase phase);
`ifdef TMA_UVM_FULL
        `uvm_info("TMA_COVERGROUP",$sformatf("functional_coverage=%0.2f",descriptor_cg.get_inst_coverage()),UVM_NONE)
`else
        `uvm_info("TMA_SCENARIOS",$sformatf("bank_family=%0d/20 offsets=%b statuses=%b sizes=%b stalls=%b busy=%b long_hold=%b; procedural counters, no SV covergroups",bank_family_count(),offsets,statuses,sizes,stalls,busy_blocked,long_stall),UVM_NONE)
`endif
    endfunction
endclass
