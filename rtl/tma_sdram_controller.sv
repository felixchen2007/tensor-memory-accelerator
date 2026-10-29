`default_nettype none

// Bring-up baseline for 4 banks x 8192 rows x 1024 columns x 16 bits.
// Fixed 50 MHz core; the board uses a PLL-shifted 50 MHz SDRAM clock.
// Selectable BL1 or BL4 read-prefetch line, CL3, explicit close-page precharge.
module tma_sdram_controller #(
    parameter int unsigned INIT_CYCLES = 10000,
    parameter int unsigned REFRESH_CYCLES = 350,
    parameter int unsigned READ_BURST_WORDS = 1
) (
    input wire clk, rst,
    input wire rd_req_valid,
    output wire rd_req_ready,
    input wire [31:0] rd_req_addr,
    output logic rd_rsp_valid,
    input wire rd_rsp_ready,
    output logic [15:0] rd_rsp_data,
    output logic rd_rsp_error,
    input wire wr_req_valid,
    output wire wr_req_ready,
    input wire [31:0] wr_req_addr,
    input wire [15:0] wr_req_data,
    output logic wr_rsp_valid,
    input wire wr_rsp_ready,
    output logic wr_rsp_error,
    output logic init_done,
    output logic [31:0] refresh_count,
    output wire active,
    output wire dram_cke,
    output wire dram_cs_n,
    output logic dram_ras_n, dram_cas_n, dram_we_n,
    output logic [12:0] dram_addr,
    output logic [1:0] dram_ba,
    output logic [1:0] dram_dqm,
    output wire [15:0] dram_dq_out,
    output logic dram_dq_oe,
    input wire [15:0] dram_dq_in,
    output wire [255:0] read_trace
);
    typedef enum logic [4:0] {
        POWER_WAIT, INIT_PRE, INIT_RP, INIT_REF, INIT_RFC,
        MODE, MODE_WAIT, IDLE, ACTIVATE, RCD_WAIT, READ_CMD,
        READ_WAIT, WRITE_CMD, WRITE_WAIT, PRECHARGE, RP_WAIT,
        REFRESH, REFRESH_WAIT
    } state_t;
    state_t state_q;
    logic [13:0] wait_q;
    logic [8:0] refresh_age_q;
    logic [3:0] init_refresh_q;
    logic write_q, last_write_q;
    logic [24:0] word_q;
    logic [15:0] data_q, read_data_q;
    logic line_valid_q;
    logic [22:0] line_tag_q;
    logic [15:0] line_words_q [4];
    logic [1:0] read_beat_q;
    wire line_hit = READ_BURST_WORDS==4 && line_valid_q && line_tag_q==rd_req_addr[25:3];
    // Unconditional, unreset capture permits an IOE input register. The FSM
    // consumes its previous value one cycle after the valid DQ capture edge.
    logic [15:0] dq_capture_q;
    always_ff @(posedge clk) dq_capture_q <= dram_dq_in;
    logic [191:0] trace_samples_q;
    logic [31:0] trace_addr_q;
    logic [3:0] trace_count_q;
    logic trace_running_q;
    wire [3:0] consumed_sample = 4'd8 + (READ_BURST_WORDS==4 ? {2'b00,trace_addr_q[2:1]} : 4'd0);
    assign read_trace={16'h5254,8'h01,consumed_sample,trace_count_q,trace_addr_q,trace_samples_q};
    // Observe the existing input register without adding another DQ pad load.
    // Sample 0 is the IOE value from the edge before request acceptance.
    always_ff @(posedge clk) begin
        if(rst) begin
            trace_samples_q<=0;trace_addr_q<=0;trace_count_q<=0;trace_running_q<=0;
        end else if(rd_req_valid && rd_req_ready && !rd_req_addr[0] && !(|rd_req_addr[31:26]) && !line_hit) begin
            trace_addr_q<=rd_req_addr;trace_samples_q<=0;
            trace_samples_q[15:0]<=dq_capture_q;trace_count_q<=1;trace_running_q<=1;
        end else if(trace_running_q) begin
            trace_samples_q[16*trace_count_q +: 16]<=dq_capture_q;
            trace_count_q<=trace_count_q+1'b1;
            if(trace_count_q==11) trace_running_q<=0;
        end
    end
    logic [2:0] command;
    logic [12:0] command_addr;
    logic [1:0] command_ba;
    wire due = refresh_age_q >= 9'(REFRESH_CYCLES);
    wire available = !rst && init_done && state_q == IDLE && !due &&
                     !rd_rsp_valid && !wr_rsp_valid;
    // Alternate when both channels compete; never accept two requests together.
    assign rd_req_ready = available && (!wr_req_valid || last_write_q);
    assign wr_req_ready = available && (!rd_req_valid || !last_write_q);
    assign active = state_q != IDLE || rd_rsp_valid || wr_rsp_valid;
    assign dram_cke = 1'b1;
    assign dram_cs_n = 1'b0;
    assign dram_dq_out = data_q;
    // One registered output stage. Commands/address/OE launch together, with
    // the read capture delayed one core cycle to account for this stage.
    always_ff @(posedge clk) begin
        if(rst) begin
            {dram_ras_n,dram_cas_n,dram_we_n}<=3'b111;
            dram_addr<=0;dram_ba<=0;dram_dqm<=2'b11;dram_dq_oe<=0;
        end else begin
            {dram_ras_n,dram_cas_n,dram_we_n}<=command;
            dram_addr<=command_addr;dram_ba<=command_ba;
            dram_dqm<=init_done ? 2'b00 : 2'b11;
            dram_dq_oe<=state_q==WRITE_CMD;
        end
    end

    always_comb begin
        command = 3'b111; // NOP
        command_addr = 13'b0;
        command_ba = word_q[24:23];
        if (!rst) begin
            case (state_q)
                INIT_PRE, PRECHARGE: begin
                    command = 3'b010;
                    command_addr[10] = 1'b1; // PRECHARGE ALL
                end
                INIT_REF, REFRESH: command = 3'b001;
                MODE: begin
                    command = 3'b000;
                    command_ba = 2'b0;
                    // BL4 reads with single-location writes (M9=1).
                    command_addr = READ_BURST_WORDS==4 ? 13'h232 : 13'h030;
                end
                ACTIVATE: begin command = 3'b011; command_addr = word_q[22:10]; end
                READ_CMD, WRITE_CMD: begin
                    command = state_q == WRITE_CMD ? 3'b100 : 3'b101;
                    command_addr[9:0] = word_q[9:0];
                    if(READ_BURST_WORDS==4 && state_q==READ_CMD)
                        command_addr[1:0] = 2'b00; // aligned eight-byte line, never crosses a row
                    // A10=0: explicit precharge after data/recovery.
                end
                default: begin end
            endcase
        end
    end

    always_ff @(posedge clk) begin
        if (rst) begin
            state_q <= POWER_WAIT;
            wait_q <= 14'(INIT_CYCLES - 1);
            refresh_age_q <= 0;
            init_refresh_q <= 0;
            init_done <= 0;
            refresh_count <= 0;
            write_q <= 0;
            last_write_q <= 0;
            word_q <= 0;
            data_q <= 0;
            read_data_q <= 0;
            line_valid_q <= 0;line_tag_q <= 0;read_beat_q <= 0;
            rd_rsp_valid <= 0;
            rd_rsp_data <= 0;
            rd_rsp_error <= 0;
            wr_rsp_valid <= 0;
            wr_rsp_error <= 0;
        end else begin
            if (rd_rsp_valid && rd_rsp_ready) rd_rsp_valid <= 0;
            if (wr_rsp_valid && wr_rsp_ready) wr_rsp_valid <= 0;
            // This timer and refresh service do not depend on response-ready.
            if (init_done && refresh_age_q != 9'h1ff)
                refresh_age_q <= refresh_age_q + 1'b1;
            case (state_q)
                POWER_WAIT: if (wait_q == 0) state_q <= INIT_PRE;
                            else wait_q <= wait_q - 1'b1;
                INIT_PRE: begin state_q <= INIT_RP; wait_q <= 1; end
                INIT_RP: if (wait_q == 0) state_q <= INIT_REF;
                         else wait_q <= wait_q - 1'b1;
                INIT_REF: begin state_q <= INIT_RFC; wait_q <= 4; end
                INIT_RFC: if (wait_q != 0) wait_q <= wait_q - 1'b1;
                          else if (init_refresh_q == 7) state_q <= MODE;
                          else begin init_refresh_q <= init_refresh_q + 1'b1; state_q <= INIT_REF; end
                MODE: begin state_q <= MODE_WAIT; wait_q <= 1; end
                MODE_WAIT: if (wait_q != 0) wait_q <= wait_q - 1'b1;
                           else begin init_done <= 1; refresh_age_q <= 0; state_q <= IDLE; end
                IDLE: begin
                    if (due) state_q <= REFRESH;
                    else if ((rd_req_valid && rd_req_ready) || (wr_req_valid && wr_req_ready)) begin
                        write_q <= wr_req_valid && wr_req_ready;
                        last_write_q <= wr_req_valid && wr_req_ready;
                        word_q <= wr_req_ready && wr_req_valid ? wr_req_addr[25:1] : rd_req_addr[25:1];
                        data_q <= wr_req_data;
                        if (wr_req_valid && wr_req_ready) begin
                            // Every write invalidates the read-only prefetch line.
                            line_valid_q <= 0;
                            wr_rsp_error <= wr_req_addr[0] || |wr_req_addr[31:26];
                            if (wr_req_addr[0] || |wr_req_addr[31:26]) wr_rsp_valid <= 1;
                            else state_q <= ACTIVATE;
                        end else begin
                            rd_rsp_error <= rd_req_addr[0] || |rd_req_addr[31:26];
                            if (rd_req_addr[0] || |rd_req_addr[31:26]) begin
                                rd_rsp_data <= 0;
                                rd_rsp_valid <= 1;
                            end else if(line_hit) begin
                                rd_rsp_data <= line_words_q[rd_req_addr[2:1]];
                                rd_rsp_valid <= 1;
                            end else begin
                                line_valid_q <= 0;read_beat_q <= 0;state_q <= ACTIVATE;
                            end
                        end
                    end
                end
                ACTIVATE: begin state_q <= RCD_WAIT; wait_q <= 1; end
                RCD_WAIT: if (wait_q != 0) wait_q <= wait_q - 1'b1;
                          else state_q <= write_q ? WRITE_CMD : READ_CMD;
                READ_CMD: begin state_q <= READ_WAIT; wait_q <= 3; end
                // CL=3: first data is driven after the second subsequent SDRAM
                // rising edge; the IOE samples on the following core rising
                // edge, and the FSM consumes that registered sample next cycle.
                READ_WAIT: if (wait_q != 0) wait_q <= wait_q - 1'b1;
                           else if(READ_BURST_WORDS==4) begin
                               line_words_q[read_beat_q] <= dq_capture_q;
                               if(read_beat_q==word_q[1:0]) read_data_q <= dq_capture_q;
                               if(read_beat_q==3) begin
                                   line_valid_q<=1;line_tag_q<=word_q[24:2];state_q<=PRECHARGE;
                               end else read_beat_q<=read_beat_q+1'b1;
                           end else begin read_data_q <= dq_capture_q; state_q <= PRECHARGE; end
                WRITE_CMD: begin state_q <= WRITE_WAIT; wait_q <= 1; end
                WRITE_WAIT: if (wait_q != 0) wait_q <= wait_q - 1'b1;
                            else state_q <= PRECHARGE;
                PRECHARGE: begin state_q <= RP_WAIT; wait_q <= 1; end
                RP_WAIT: if (wait_q != 0) wait_q <= wait_q - 1'b1;
                         else begin
                             state_q <= IDLE;
                             if (write_q) wr_rsp_valid <= 1;
                             else begin rd_rsp_valid <= 1; rd_rsp_data <= read_data_q; end
                         end
                REFRESH: begin
                    state_q <= REFRESH_WAIT;
                    wait_q <= 4;
                    refresh_age_q <= 0;
                    refresh_count <= refresh_count + 1'b1;
                end
                REFRESH_WAIT: if (wait_q != 0) wait_q <= wait_q - 1'b1;
                              else state_q <= IDLE;
                default: state_q <= POWER_WAIT;
            endcase
        end
    end
    generate
        if (INIT_CYCLES < 10000 || INIT_CYCLES > 16384 ||
            REFRESH_CYCLES < 32 || REFRESH_CYCLES > 350 ||
            (READ_BURST_WORDS!=1 && READ_BURST_WORDS!=4)) begin : invalid_parameters
            initial $fatal(1, "SDRAM parameters require 50 MHz, >=200 us startup, refresh <=7 us");
        end
    endgenerate
endmodule

`default_nettype wire
