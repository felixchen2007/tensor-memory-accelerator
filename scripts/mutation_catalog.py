"""Targeted first-order RTL defects; every anchor must match exactly once."""
from dataclasses import dataclass
import hashlib


@dataclass(frozen=True)
class Mutation:
    name: str
    source: str
    before: str
    after: str
    checker_ids: tuple[str, ...]
    requirement: str
    model_diagnostic: str = ""

    def apply(self, original: bytes) -> bytes:
        old, new = self.before.encode(), self.after.encode()
        if original.count(old) != 1:
            raise ValueError(f"{self.name}: anchor must occur exactly once")
        mutated = original.replace(old, new, 1)
        if mutated == original:
            raise ValueError(f"{self.name}: mutation made no change")
        return mutated

    def identity(self, original: bytes) -> dict:
        return {"source_sha256": hashlib.sha256(original).hexdigest(),
                "mutated_sha256": hashlib.sha256(self.apply(original)).hexdigest()}


PIPE = "rtl/tma_copy_engine_pipelined.sv"
ADDR = "rtl/tma_addr_gen.sv"
SDRAM = "rtl/tma_sdram_controller.sv"
MUTATIONS = [
    Mutation("fifo_data_bit_flipped", PIPE,
             "fifo_data[tail_q] <= rd_rsp_data;", "fifo_data[tail_q] <= rd_rsp_data ^ 16'h0001;",
             ("TMA_WRITE_DATA",), "FIFO data must equal the ordered read response"),
    Mutation("fifo_destination_bit_flipped", PIPE,
             "fifo_dst[tail_q] <= pending_dst_q;", "fifo_dst[tail_q] <= pending_dst_q ^ ADDR_W'(2);",
             ("TMA_WRITE_DATA",), "FIFO must retain each response's destination address"),
    Mutation("fifo_head_skips_entry", PIPE,
             "if (pop) head_q <= head_q + 1'b1;", "if (pop) head_q <= head_q + 2'd2;",
             ("TMA_WRITE_DATA",), "Write ordering must advance exactly one FIFO entry"),
    Mutation("fifo_head_never_advances", PIPE,
             "if (pop) head_q <= head_q + 1'b1;", "if (pop) head_q <= head_q;",
             ("TMA_WRITE_DATA",), "Consecutive writes must not reuse a consumed FIFO entry"),
    Mutation("write_offered_when_fifo_empty", PIPE,
             "!drop_writes_q && (used_q != 0)", "!drop_writes_q && (used_q == 0)",
             ("TMA_WRITE_DATA", "TMA_WRITE_COUNT"), "An empty FIFO must never produce a write"),
    Mutation("completion_count_increments_twice", PIPE,
             "completed_elements <= completed_elements + 1'b1;", "completed_elements <= completed_elements + 2'd2;",
             ("TMA_STATUS",), "Completed elements count acknowledged writes exactly once"),
    Mutation("completion_before_drain", PIPE,
             "if (allocation_done_q && !slot_valid_q && !read_pending_q &&\n                        (used_q == 0) && !write_pending_q)",
             "if (allocation_done_q)", ("TMA_READ_STABILITY", "TMA_STATUS", "TMA_INCOMPLETE"),
             "Descriptor completion must wait for all reads and writes to drain"),
    Mutation("late_bounds_check_disabled", PIPE,
             "wire bad_pair = (gen_src > SRC_LAST) || (gen_dst > DST_LAST);", "wire bad_pair = 1'b0;",
             ("TMA_READ_COUNT", "TMA_WRITE_COUNT", "TMA_STATUS"),
             "Out-of-bounds descriptors must stop at the legal committed prefix"),
    Mutation("source_column_uses_row_stride", ADDR,
             "src_addr <= src_addr + src_col_stride_q;", "src_addr <= src_addr + src_row_stride_q;",
             ("TMA_READ_ADDRESS",), "Source column addresses use the source column stride"),
    Mutation("destination_column_uses_row_stride", ADDR,
             "dst_addr <= dst_addr + dst_col_stride_q;", "dst_addr <= dst_addr + dst_row_stride_q;",
             ("TMA_WRITE_DATA",), "Destination column addresses use the destination column stride"),
    Mutation("source_row_uses_column_stride", ADDR,
             "src_addr <= src_row_base_q + src_row_stride_q;", "src_addr <= src_row_base_q + src_col_stride_q;",
             ("TMA_READ_ADDRESS",), "The first source element in a row uses the row base"),
    Mutation("destination_row_uses_column_stride", ADDR,
             "dst_addr <= dst_row_base_q + dst_row_stride_q;", "dst_addr <= dst_row_base_q + dst_col_stride_q;",
             ("TMA_WRITE_DATA",), "The first destination element in a row uses the row base"),
    Mutation("burst_hit_returns_word_zero", SDRAM,
             "rd_rsp_data <= line_words_q[rd_req_addr[2:1]];", "rd_rsp_data <= line_words_q[2'b00];",
             ("TMA_MEMORY_DATA",), "Each buffered burst offset must return its own word"),
    Mutation("burst_tag_ignores_bank", SDRAM,
             "line_tag_q==rd_req_addr[25:3]", "line_tag_q[20:0]==rd_req_addr[23:3]",
             ("TMA_MEMORY_DATA",), "Read-buffer identity includes the physical SDRAM bank"),
    Mutation("burst_tag_ignores_row", SDRAM,
             "line_tag_q==rd_req_addr[25:3]",
             "{line_tag_q[22:21],line_tag_q[7:0]}=={rd_req_addr[25:24],rd_req_addr[10:3]}",
             ("TMA_MEMORY_DATA",), "Read-buffer identity includes the physical SDRAM row"),
    Mutation("write_does_not_invalidate_buffer", SDRAM,
             "// Every write invalidates the read-only prefetch line.\n                            line_valid_q <= 0;",
             "// Every write invalidates the read-only prefetch line.\n                            line_valid_q <= line_valid_q;",
             ("TMA_MEMORY_DATA",), "Every accepted write invalidates the prefetch line"),
    Mutation("burst_miss_selects_wrong_beat", SDRAM,
             "if(read_beat_q==word_q[1:0]) read_data_q <= dq_capture_q;",
             "if(read_beat_q==(word_q[1:0]^2'b01)) read_data_q <= dq_capture_q;",
             ("TMA_MEMORY_DATA",), "A burst miss returns the requested beat"),
    Mutation("invalid_write_reports_success", SDRAM,
             "wr_rsp_error <= wr_req_addr[0] || |wr_req_addr[31:26];", "wr_rsp_error <= 1'b0;",
             ("TMA_MAINT_ERROR",), "Invalid maintenance writes must return an address error"),
    Mutation("held_response_valid_dropped", SDRAM,
             "if (rd_rsp_valid && rd_rsp_ready) rd_rsp_valid <= 0;", "if (rd_rsp_valid) rd_rsp_valid <= 0;",
             ("TMA_RESPONSE_STABILITY",), "Read response valid remains asserted until accepted"),
    Mutation("held_response_data_changes", SDRAM,
             "if (rd_rsp_valid && rd_rsp_ready) rd_rsp_valid <= 0;",
             "if (rd_rsp_valid && rd_rsp_ready) rd_rsp_valid <= 0;\n            if (rd_rsp_valid && !rd_rsp_ready) rd_rsp_data <= rd_rsp_data + 16'd1;",
             ("TMA_RESPONSE_STABILITY",), "Held read response data must remain stable"),
    Mutation("refresh_blocked_by_held_response", SDRAM,
             "if (due) state_q <= REFRESH;", "if (due && !rd_rsp_valid && !wr_rsp_valid) state_q <= REFRESH;",
             (), "Refresh continues while a completed response is held",
             "SDRAM_MODEL refresh deadline missed"),
]
