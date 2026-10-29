`timescale 1ns/1ps
`default_nettype none

// Independent pin-level subset model, authored for this project. Not a vendor
// model. Checks BL1/BL4 reads, single writes, CL3, startup, timing and refresh.
module tma_sdram_model #(
    parameter realtime T_AC = 5.4,
    parameter int READ_SKEW_CYCLES = 0,
    parameter logic [15:0] READ_XOR_MASK = 16'b0
) (
    input wire dram_clk,
    input wire power_reset,
    input wire cke, cs_n, ras_n, cas_n, we_n,
    input wire [12:0] addr,
    input wire [1:0] ba, dqm,
    input wire controller_oe,
    inout wire [15:0] dq,
    output integer reads = 0, writes = 0, refreshes = 0,
    output integer max_refresh_gap = 0
);
    logic [15:0] memory [longint unsigned];
    logic [12:0] open_row [4];
    bit opened [4];
    realtime last_act [4], last_pre [4], last_write [4];
    realtime started = 0, last_ref = -1000, last_mrs = -1000;
    bit configured = 0, precharged = 0;
    int initial_refs = 0, cycle = 0, read_due = -1, release_due = -1, ref_cycle = 0;
    logic [15:0] pending_data [4];
    logic [15:0] dq_data;
    int read_length=1,read_beats=0;
    bit dq_oe = 0;
    wire [2:0] cmd = {ras_n,cas_n,we_n};
    assign dq = dq_oe ? dq_data : 16'hzzzz;
    realtime last_control_change=-1000,last_data_change=-1000;
    realtime last_command_edge=-1000,last_write_edge=-1000;
    bit sampled_command=0;
    // These pin checks use elapsed nanoseconds, independently of FSM cycles.
    // They do not replace fitted timing or model FPGA/PCB propagation delay.
    always @(addr or ba or cs_n or ras_n or cas_n or we_n or dqm) begin
        if(!power_reset && sampled_command && $realtime-last_command_edge<0.8)
            $fatal(1,"SDRAM_MODEL command hold");
        last_control_change=$realtime;
    end
    always @(dq) begin
        if(!power_reset && $realtime-last_write_edge<0.8)
            $fatal(1,"SDRAM_MODEL write data hold");
        last_data_change=$realtime;
    end

    initial begin
        for (int b=0;b<4;b++) begin
            opened[b]=0; last_act[b]=-1000; last_pre[b]=-1000; last_write[b]=-1000;
        end
    end
    always @(posedge dram_clk) begin : memory_clock
        longint unsigned key;
        cycle++;
        if (power_reset) begin
            started=$realtime; configured=0; precharged=0; initial_refs=0;
            last_ref=-1000; last_mrs=-1000; ref_cycle=cycle;
            read_due=-1; release_due=-1; dq_oe=0;read_length=1;
            sampled_command=0;last_command_edge=-1000;last_write_edge=-1000;
            for (int b=0;b<4;b++) begin
                opened[b]=0; last_act[b]=-1000; last_pre[b]=-1000; last_write[b]=-1000;
            end
        end else begin
            if (controller_oe && dq_oe) $fatal(1,"SDRAM_MODEL bus contention");
            if (configured && cycle-ref_cycle > 390)
                $fatal(1,"SDRAM_MODEL refresh deadline missed gap=%0d",cycle-ref_cycle);
            for (int b=0;b<4;b++)
                if (opened[b] && $realtime-last_act[b]>100000)
                    $fatal(1,"SDRAM_MODEL tRAS maximum exceeded");
            if (cycle == release_due) dq_oe <= #2.5 0;
            if (read_due>=0 && cycle>=read_due && cycle<read_due+read_length) begin
                dq_data <= #(T_AC) pending_data[cycle-read_due];
                dq_oe <= #(T_AC) 1;
                read_beats++;
            end
            if (!cke) $fatal(1,"SDRAM_MODEL CKE must stay high");
            sampled_command=!cs_n && cmd!=3'b111;
            last_command_edge=$realtime;
            if (!cs_n && cmd != 3'b111) begin
                if($realtime-last_control_change<1.5) $fatal(1,"SDRAM_MODEL command setup");
                if ($realtime-started < 200000)
                    $fatal(1,"SDRAM_MODEL command before 200us startup");
                if ($realtime-last_ref < 60) $fatal(1,"SDRAM_MODEL tRC refresh recovery");
                if ($realtime-last_mrs < 40) $fatal(1,"SDRAM_MODEL tMRD");
                case (cmd)
                    3'b010: begin // PRECHARGE
                        if(configured && read_due>=0 && cycle<=release_due)
                            $fatal(1,"SDRAM_MODEL precharge before read burst completed");
                        if (!addr[10]) $fatal(1,"SDRAM_MODEL requires PRECHARGE ALL");
                        for (int b=0;b<4;b++) begin
                            if (opened[b] && $realtime-last_act[b]<42) $fatal(1,"SDRAM_MODEL tRAS");
                            if (opened[b] && $realtime-last_write[b]<14) $fatal(1,"SDRAM_MODEL tDPL");
                            opened[b]=0; last_pre[b]=$realtime;
                        end
                        precharged=1; initial_refs=0;
                    end
                    3'b001: begin // AUTO REFRESH
                        if (!precharged) $fatal(1,"SDRAM_MODEL refresh before initial precharge");
                        for (int b=0;b<4;b++) begin
                            if (opened[b]) $fatal(1,"SDRAM_MODEL refresh with open row");
                            if ($realtime-last_pre[b]<18) $fatal(1,"SDRAM_MODEL refresh tRP");
                        end
                        if (configured && cycle-ref_cycle>max_refresh_gap) max_refresh_gap=cycle-ref_cycle;
                        ref_cycle=cycle; last_ref=$realtime; refreshes++; initial_refs++;
                    end
                    3'b000: begin
                        if ((addr!==13'h030 && addr!==13'h232) || ba!==0)
                            $fatal(1,"SDRAM_MODEL expected BL1/BL4 sequential CL3 single-write mode");
                        if (initial_refs<8) $fatal(1,"SDRAM_MODEL expected eight initialization refreshes");
                        for (int b=0;b<4;b++) if (opened[b]) $fatal(1,"SDRAM_MODEL mode with open row");
                        configured=1; last_mrs=$realtime; ref_cycle=cycle;
                        read_length=addr[1] ? 4 : 1;
                    end
                    3'b011: begin // ACTIVATE
                        if (!configured || opened[ba]) $fatal(1,"SDRAM_MODEL invalid ACTIVATE");
                        if ($realtime-last_pre[ba]<18) $fatal(1,"SDRAM_MODEL ACT tRP");
                        if ($realtime-last_act[ba]<60) $fatal(1,"SDRAM_MODEL ACT tRC");
                        for (int b=0;b<4;b++)
                            if (b!=int'(ba) && $realtime-last_act[b]<14) $fatal(1,"SDRAM_MODEL tRRD");
                        open_row[ba]=addr; opened[ba]=1; last_act[ba]=$realtime;
                    end
                    3'b100,3'b101: begin
                        if (!configured || !opened[ba]) $fatal(1,"SDRAM_MODEL column without ACTIVATE");
                        if ($realtime-last_act[ba]<18) $fatal(1,"SDRAM_MODEL tRCD");
                        if (addr[12:10]!==0 || dqm!==0) $fatal(1,"SDRAM_MODEL address/mask policy");
                        key=(longint'(ba)<<23) | (longint'(open_row[ba])<<10) | longint'(addr[9:0]);
                        if (cmd==3'b100) begin
                            if (!controller_oe || $isunknown(dq)) $fatal(1,"SDRAM_MODEL missing WRITE data");
                            if($realtime-last_data_change<1.5) $fatal(1,"SDRAM_MODEL write data setup");
                            last_write_edge=$realtime;
                            memory[key]=dq; last_write[ba]=$realtime; writes++;
                        end else begin
                            if (controller_oe) $fatal(1,"SDRAM_MODEL driving during READ");
                            if (read_length==1 && !memory.exists(key))
                                $fatal(1,"SDRAM_MODEL read of uninitialized word %h",key);
                            for(int beat=0;beat<read_length;beat++) begin
                                // SDRAM wraps within its programmed burst block.
                                // Unseeded prefetched neighbors have unspecified data.
                                key=((longint'(ba)<<23) | (longint'(open_row[ba])<<10) |
                                    (longint'(addr[9:0]) & ~longint'(read_length-1))) |
                                    ((longint'(addr[9:0])+longint'(beat)) & longint'(read_length-1));
                                pending_data[beat]=memory.exists(key) ? memory[key]^READ_XOR_MASK : 16'hxxxx;
                            end
                            read_due=cycle+2+READ_SKEW_CYCLES;
                            release_due=read_due+read_length;
                            reads++;
                        end
                    end
                    default: $fatal(1,"SDRAM_MODEL unsupported command");
                endcase
            end
        end
    end
endmodule

`default_nettype wire
