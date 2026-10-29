"""Generate whole-memory and transaction-trace expectations for copy RTL."""

from dataclasses import dataclass, replace
import json
from pathlib import Path
import random

from model.address_model import Descriptor
from model.copy_model import ErrorCode, copy_tensor

WORDS = 4096  # 8 KiB independent source and destination endpoints.


@dataclass(frozen=True)
class CopyCase:
    name: str
    desc: Descriptor
    timing: int = 1  # 0: always-ready, minimum response latency; 1: random stalls.
    fault_kind: int = 0  # 1: read response error; 2: write response error.
    fault_index: int = 0


def generate_copy_vectors(output_dir: Path, seed: int, random_cases: int) -> dict:
    rng = random.Random(seed ^ 0xC0FFEE)
    tile = Descriptor(0, 2048, 2, 3, 6, 2, 6, 2)
    large = Descriptor(0, 2048, 32, 32, 64, 2, 64, 2)
    cases = [
        CopyCase("single_word_minimum_latency", replace(tile, rows=1, cols=1), 0),
        CopyCase("copy_32x32_minimum_latency", large, 0),
        CopyCase("copy_32x32_variable_latency", large),
        CopyCase("transpose_32x32", replace(large, dst_row_stride=2, dst_col_stride=64)),
        CopyCase("transpose_2x3", replace(tile, dst_row_stride=2, dst_col_stride=4)),
        CopyCase("padded_rows", Descriptor(64, 2048, 8, 16, 64, 2, 96, 2)),
        CopyCase("broadcast_source", replace(tile, src_row_stride=0, src_col_stride=0)),
        CopyCase("repeated_destination", replace(tile, dst_row_stride=0, dst_col_stride=0)),
        CopyCase("empty_rows", replace(tile, rows=0)),
        CopyCase("empty_cols", replace(tile, cols=0)),
        CopyCase("unaligned_source", replace(tile, src_base=1)),
        CopyCase("unaligned_destination", replace(tile, dst_base=2049)),
        CopyCase("unaligned_row_stride", replace(tile, src_row_stride=7)),
        CopyCase("unaligned_column_stride", replace(tile, dst_col_stride=3)),
        CopyCase("invalid_source_base", replace(tile, src_base=8192)),
        CopyCase("invalid_destination_base", replace(tile, dst_base=8192)),
        CopyCase("oversized_stride", replace(tile, src_row_stride=8192)),
        CopyCase("source_column_exceeds_bounds", Descriptor(8190, 0, 1, 2, 0, 2, 0, 2)),
        CopyCase("destination_column_exceeds_bounds", Descriptor(0, 8190, 1, 2, 0, 2, 0, 2)),
        CopyCase("source_row_exceeds_bounds", Descriptor(8188, 0, 3, 1, 2, 0, 2, 0)),
        CopyCase("destination_row_exceeds_bounds", Descriptor(0, 8188, 3, 1, 2, 0, 2, 0)),
    ]
    for fault_kind, label in [(1, "read"), (2, "write")]:
        for index in (0, 2, 5):
            cases.append(CopyCase(f"{label}_error_element_{index}", tile,
                                  fault_kind=fault_kind, fault_index=index))
    directed_count = len(cases)
    for index in range(random_cases):
        rows, cols = rng.randint(1, 12), rng.randint(1, 12)
        transpose = bool(rng.getrandbits(1))
        desc = Descriptor(
            2 * rng.randrange(128), 2048 + 2 * rng.randrange(128), rows, cols,
            2 * (cols + rng.randrange(8)), 2,
            2 if transpose else 2 * (cols + rng.randrange(8)),
            2 * rows if transpose else 2)
        fault_kind = rng.choices([0, 1, 2], weights=[8, 1, 1])[0]
        cases.append(CopyCase(f"random_{index}", desc, fault_kind=fault_kind,
                              fault_index=rng.randrange(rows * cols)))

    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_cases = []
    total_reads = total_writes = total_completed = 0
    with (output_dir / "copy_vectors.txt").open("w", encoding="ascii") as stream:
        for case_id, case in enumerate(cases):
            source = [((i * 73) ^ (case_id * 137)) & 0xFFFF for i in range(WORDS)]
            initial = [(0xA55A ^ i ^ (case_id * 31)) & 0xFFFF for i in range(WORDS)]
            result = copy_tensor(case.desc, source, initial,
                                 case.fault_index if case.fault_kind == 1 else None,
                                 case.fault_index if case.fault_kind == 2 else None)
            desc = case.desc
            expected_cycles = (5 * desc.element_count + 1
                               if case.timing == 0 and result.error_code == ErrorCode.OK
                               else 0)
            header = (desc.src_base, desc.dst_base, desc.rows, desc.cols,
                      desc.src_row_stride, desc.src_col_stride,
                      desc.dst_row_stride, desc.dst_col_stride,
                      case.timing, case.fault_kind, case.fault_index,
                      int(result.error_code), result.completed_elements,
                      len(result.reads), len(result.writes), expected_cycles)
            stream.write(" ".join(f"{v:x}" for v in header) + "\n")
            for src, dst, expected in zip(source, initial, result.destination):
                stream.write(f"{src:04x} {dst:04x} {expected:04x}\n")
            for address in result.reads:
                stream.write(f"{address:x}\n")
            for address, value in result.writes:
                stream.write(f"{address:x} {value:04x}\n")
            manifest_cases.append({
                "id": case_id, "name": case.name, "elements": desc.element_count,
                "error_code": int(result.error_code),
                "completed_elements": result.completed_elements,
                "read_requests": len(result.reads), "write_requests": len(result.writes),
                "timing_mode": case.timing, "expected_cycles": expected_cycles,
            })
            total_reads += len(result.reads)
            total_writes += len(result.writes)
            total_completed += result.completed_elements
    manifest = {
        "seed": seed ^ 0xC0FFEE, "random_descriptors": random_cases,
        "directed_descriptors": directed_count, "total_descriptors": len(cases),
        "endpoint_words": WORDS, "expected_reads": total_reads,
        "expected_writes": total_writes, "expected_completed_elements": total_completed,
        "stall_seed": "0x91e10da5", "cases": manifest_cases,
    }
    (output_dir / "copy_manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest
