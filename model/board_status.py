"""Decode version-2/3/4 passive board diagnostics; never access hardware."""
import re

STAGES = ("waiting_for_initialization", "sdram_seed_request", "sdram_seed_response",
          "sdram_read_request", "sdram_read_response", "scratchpad_seed_request",
          "scratchpad_seed_response", "scratchpad_read_request", "scratchpad_read_response",
          "descriptor", "tensor_transfer", "tensor_read_request", "tensor_read_response", "finished",
          "waiting_for_refresh_phase")
FAILURES = {0: "none", 1: "sdram_seed_response", 2: "tensor_transfer_status",
            3: "tensor_read_response", 4: "tensor_data_mismatch", 5: "sdram_read_response",
            6: "sdram_data_mismatch", 7: "scratchpad_seed_response",
            8: "scratchpad_read_response", 9: "scratchpad_data_mismatch"}
# Low bit, width; offsets follow the public probe format, not Python byte order.
FIELDS = {"flags": (224, 8), "stage_code": (220, 4), "failure_reason": (216, 4),
          "checked_words": (204, 12), "source_checked_words": (192, 12),
          "scratch_checked_words": (180, 12), "failure_word": (148, 32),
          "expected_data": (132, 16), "observed_data": (116, 16),
          "completed_elements": (84, 32), "elapsed_cycles": (20, 64),
          "refresh_count_low": (4, 16)}


def decode_snapshot(raw: str) -> dict:
    text = raw.strip().removeprefix("0x").removeprefix("0X")
    if not re.fullmatch(r"[0-9a-fA-F]{64}", text):
        raise ValueError("Expected exactly 256 bits of hexadecimal probe data")
    value = int(text, 16)
    version = (value >> 232) & 0xFF
    if value >> 240 != 0x544D or version not in (2, 3, 4):
        raise ValueError("Unknown diagnostic signature/version; this reader requires format 2, 3 or 4")
    if version == 2 and value & 0xF:
        raise ValueError("Reserved diagnostic bits are nonzero")
    if version == 3 and value & 0xE != 0xA:
        raise ValueError("Unknown benchmark workload or refresh alignment")
    if version == 4 and value & 0xE != 0xE:
        raise ValueError("Unknown burst benchmark workload or refresh alignment")
    result = {name: (value >> bit) & ((1 << width) - 1) for name, (bit, width) in FIELDS.items()}
    result.update(format_version=version, engine=("pipelined" if value & 1 else "serialized")
                  if version >= 3 else "unspecified", operation="transpose32" if version >= 3 else "unspecified",
                  refresh_aligned=version >= 3, read_burst_words=4 if version == 4 else 1 if version == 3 else None)
    flags = result["flags"]
    result.update(initialized=bool(flags & 1), passed=bool(flags & 2), failed=bool(flags & 4),
                  reset=bool(flags & 8), pll_locked=bool(flags & 16), passed_stages=flags >> 5)
    reason, stage = result["failure_reason"], result["stage_code"]
    if reason not in FAILURES or stage >= len(STAGES) or (result["passed"] and result["failed"]):
        raise ValueError("Inconsistent diagnostic state")
    if any(result[name] > 1024 for name in ("checked_words", "source_checked_words",
                                           "scratch_checked_words", "completed_elements")):
        raise ValueError("Diagnostic element count exceeds the fixed test size")
    terminal = result["passed"] or result["failed"]
    if terminal and (stage != 13 or not result["pll_locked"] or result["reset"] or not result["initialized"]):
        raise ValueError("Terminal result without a completed, initialized clocked test")
    if result["passed"] and (reason != 0 or result["passed_stages"] != 7 or any(
            result[name] != 1024 for name in ("checked_words", "source_checked_words",
                                             "scratch_checked_words", "completed_elements"))):
        raise ValueError("PASS flag without all three memory checks and transfer completion")
    if result["failed"]:
        expected_stages = {1: 1, 2: 3, 3: 7, 4: 7, 5: 1, 6: 1, 7: 0, 8: 0, 9: 0}
        if reason == 0 or result["passed_stages"] != expected_stages[reason]:
            raise ValueError("Failure reason disagrees with completed preflight stages")
        if result["failure_word"] >= 1024:
            raise ValueError("Failing word lies outside the fixed test tile")
        if reason in (1, 5, 6, 7, 8, 9) and result["completed_elements"] != 0:
            raise ValueError("A preflight failure cannot have completed a tensor transfer")
    if not terminal and reason != 0:
        raise ValueError("Failure reason is set without the FAIL flag")
    result.update(stage=STAGES[stage], failure=FAILURES[reason],
                  status="fail" if result["failed"] else "pass" if result["passed"] else "running")
    if reason in (1, 5, 6):
        result["failure_byte_address"] = 0x010007F0 + 2 * result["failure_word"]
        result["failure_endpoint"] = "sdram"
    elif reason in (3, 4, 7, 8, 9):
        result["failure_byte_address"] = 2 * result["failure_word"]
        result["failure_endpoint"] = "scratchpad"
    return result


def decode_samples(samples: list[str]) -> dict:
    if len(samples) != 3:
        raise ValueError("Require exactly three probe snapshots")
    decoded = [decode_snapshot(sample) for sample in samples]
    stable = lambda item: {k: v for k, v in item.items() if k != "refresh_count_low"}
    if any(stable(item) != stable(decoded[0]) for item in decoded[1:]):
        raise ValueError("Probe result changed across snapshots; no stable result established")
    result = dict(decoded[-1])
    result["refresh_count_low_atomic"] = False
    return result


def decode_read_trace(raw: str) -> dict:
    text = raw.strip().removeprefix("0x").removeprefix("0X")
    if not re.fullmatch(r"[0-9a-fA-F]{64}", text):
        raise ValueError("Expected a 256-bit hexadecimal read trace")
    value = int(text, 16)
    if value >> 240 != 0x5254 or (value >> 232) & 255 != 1:
        raise ValueError("Unknown read-trace signature/version")
    count = (value >> 224) & 15
    consumed = (value >> 228) & 15
    if count == 0 and value & ((1 << 224) - 1) == 0:
        return {"available": False, "byte_address": None, "samples": [],
                "consumed_sample_index": consumed, "consumed_value": None}
    if count != 12 or consumed >= count:
        raise ValueError("Read trace is incomplete or has an invalid capture index")
    samples = [(value >> (16 * i)) & 65535 for i in range(count)]
    return {"available": True, "byte_address": (value >> 192) & 0xFFFFFFFF,
            "consumed_sample_index": consumed, "samples": samples,
            "consumed_value": samples[consumed]}
