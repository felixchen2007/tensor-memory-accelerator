class tma_regression_sequence extends uvm_sequence #(tma_item);
    `uvm_object_utils(tma_regression_sequence)
    tma_item host_item;
    int descriptor_count;
    int unsigned rng=32'h19a74d63;
    function new(string name="tma_regression_sequence");super.new(name);endfunction
    function int unsigned next_random();
        rng^=rng<<13;rng^=rng>>17;rng^=rng<<5;return rng;
    endfunction
    task host(bit wr,bit dst,bit [31:0] addr,bit [15:0] data=0,int hold_cycles=0);
        start_item(host_item);
        host_item.op=wr ? HOST_WRITE : HOST_READ;host_item.dst=dst;
        host_item.addr=addr;host_item.data=data;host_item.stall_cycles=hold_cycles;
        finish_item(host_item);
    endtask
    task scan_destination();
        for(int w=0;w<4096;w++) host(0,1,32'(w*2),0,w%6);
    endtask
    function bit legal_header(tma_item d);
        return d.rows!=0 && d.cols!=0 && !((d.sb|d.db|d.srs|d.scs|d.drs|d.dcs)&1) &&
            d.sb<=67108862 && d.srs<=67108862 && d.scs<=67108862 &&
            d.db<=8190 && d.drs<=8190 && d.dcs<=8190;
    endfunction
    task run_descriptor(tma_item d,bit full_scan=0);
        longint unsigned sa,da;
        bit prefix_stopped=0;
        if(legal_header(d)) begin
            for(int r=0;r<d.rows;r++) for(int c=0;c<d.cols;c++) begin
                if(prefix_stopped) break;
                sa=64'(d.sb)+64'(r)*64'(d.srs)+64'(c)*64'(d.scs);
                da=64'(d.db)+64'(r)*64'(d.drs)+64'(c)*64'(d.dcs);
                if(sa>=67108864 || da>=8192) begin prefix_stopped=1;break;end
                host(1,0,32'(sa),16'((sa>>1)*73 ^ (sa>>13) ^ descriptor_count*997 ^ 16'ha55a),
                     int'(next_random()%6));
            end
        end
        d.op=DESCRIPTOR;d.probe_busy=legal_header(d);d.stall_cycles=2;
        start_item(d);finish_item(d);descriptor_count++;
        if(full_scan) scan_destination();
        else begin
            // Check written addresses through the public RAM interface in
            // addition to checking every DMA request and acknowledged write.
            if(legal_header(d)) begin
                prefix_stopped=0;
                for(int r=0;r<d.rows;r++) for(int c=0;c<d.cols;c++) begin
                    if(prefix_stopped) break;
                    sa=64'(d.sb)+64'(r)*64'(d.srs)+64'(c)*64'(d.scs);
                    da=64'(d.db)+64'(r)*64'(d.drs)+64'(c)*64'(d.dcs);
                    if(sa>=67108864 || da>=8192) begin prefix_stopped=1;break;end
                    host(0,1,32'(da),0,int'(next_random()%6));
                end
            end
            for(int guard_word=0;guard_word<16;guard_word++)
                host(0,1,32'(((guard_word*251+descriptor_count*73)%4096)*2));
        end
    endtask
    function tma_item shape(int family,int bank,int offset,int rows=3,int cols=4);
        tma_item d=tma_item::type_id::create("shape");
        d.family=family;d.bank=bank;d.offset=offset;d.source_row=family;
        d.destination_word=bank*32+family*8;d.nrows=rows;d.ncols=cols;d.derive();return d;
    endfunction
    task body();
        tma_item d;
        int random_cases=12;
        int skip_source_read=0;
        void'($value$plusargs("TMA_RANDOM_CASES=%d",random_cases));
        void'($value$plusargs("TMA_STIMULUS_SEED=%d",rng));
        void'($value$plusargs("TMA_SKIP_SOURCE_READ=%d",skip_source_read));
        host_item=tma_item::type_id::create("host_command");
        for(int w=0;w<4096;w++) host(1,1,32'(w*2),16'(w ^ 16'hca71),w%6);
        scan_destination();
        host(1,0,0,16'ha55a);
        if(!skip_source_read) host(0,0,0,0,850); // refresh must continue while response is held
        host(0,0,1);host(1,0,32'h04000000,0);
        host(0,1,8192);host(1,1,1,0);
        for(int bank=0;bank<4;bank++) for(int family=0;family<5;family++) begin
            d=shape(family,bank,(bank+family)%4);run_descriptor(d);
        end
        d=shape(0,0,0,32,32);d.sb=32'h000007f0;d.db=0;run_descriptor(d,1);
        d=shape(1,3,0,32,32);d.sb=32'h03fff800;d.db=0;run_descriptor(d,1);
        d=shape(2,2,1,8,16);d.sb=32'h020007fa;run_descriptor(d,1);
        d=shape(3,3,0,32,8);run_descriptor(d,1);
        for(int offset=0;offset<4;offset++) begin
            d=shape(0,1,offset,1,1);d.sb=32'h01000400+32'(offset*2);run_descriptor(d);
        end
        d=shape(0,0,0,1,8);d.dcs=0;run_descriptor(d);
        d=shape(0,0,0,0,4);run_descriptor(d);
        d=shape(0,0,0,1,4);d.sb=1;run_descriptor(d);
        d=shape(0,0,0,1,1);d.srs=1;run_descriptor(d); // even unused strides must be aligned
        d=shape(0,0,0,1,2);d.db=8190;run_descriptor(d);
        d=shape(0,3,3,1,2);d.sb=32'h03fffffe;run_descriptor(d);
        repeat(random_cases) begin
            d=tma_item::type_id::create("seeded_shape");
`ifdef TMA_UVM_FULL
            if(!d.randomize()) `uvm_fatal("TMA_RANDOMIZE","Descriptor constraints could not be solved")
`else
            // The Starter license permits UVM but denies randomize/covergroups.
            // This explicit bounded PRNG is reported as procedural stimulus.
            d.family=next_random()%5;d.bank=next_random()%4;d.offset=next_random()%4;
            d.source_row=next_random()%5;d.destination_word=next_random()%1025;
            d.nrows=1+next_random()%8;d.ncols=1+next_random()%8;
`endif
            d.derive();run_descriptor(d);
        end
        start_item(host_item);host_item.op=DELAY;host_item.delay_cycles=1000;finish_item(host_item);
        scan_destination();
    endtask
endclass
