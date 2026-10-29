"""Paired-engine vectors: identical data and per-transaction memory timing."""

import json
from pathlib import Path

from model.address_model import Descriptor
from model.copy_model import copy_tensor


def generate_pipeline_vectors(output_dir: Path, copy_manifest: dict, seed: int) -> dict:
    words = copy_manifest["endpoint_words"]
    cases = []
    with (output_dir / "pipeline_vectors.txt").open("w", encoding="ascii") as output:
        def emit(name, desc, source, initial, mode, kind=0, fault_index=0, stress=0):
            result = copy_tensor(desc, source, initial,
                                 fault_index if kind == 1 else None,
                                 fault_index if kind == 2 else None)
            # Prefetch after a memory fault may read additional legal addresses,
            # but every write must still match the original functional oracle.
            legal_reads = copy_tensor(desc, source, initial).reads
            count = desc.element_count
            baseline_cycles = 5 * count + 1 if mode == 0 and result.error_code == 0 else 0
            pipeline_cycles = count + 6 if mode == 0 and result.error_code == 0 else 0
            header = (desc.src_base, desc.dst_base, desc.rows, desc.cols,
                      desc.src_row_stride, desc.src_col_stride,
                      desc.dst_row_stride, desc.dst_col_stride,
                      mode, kind, fault_index, int(result.error_code), result.completed_elements,
                      len(result.reads), len(result.writes), baseline_cycles,
                      len(legal_reads), stress)
            output.write(" ".join(f"{value:x}" for value in header) + "\n")
            for src, dst, expected in zip(source, initial, result.destination):
                output.write(f"{src:04x} {dst:04x} {expected:04x}\n")
            for address in result.reads:
                output.write(f"{address:x}\n")
            for address, value in result.writes:
                output.write(f"{address:x} {value:04x}\n")
            for address in legal_reads:
                output.write(f"{address:x}\n")
            cases.append({
                "id": len(cases), "name": name, "elements": count,
                "mode": mode, "stress": stress, "fault_kind": kind,
                "error_code": int(result.error_code),
                "completed_elements": result.completed_elements,
                "minimum_reads": len(result.reads), "maximum_reads": len(legal_reads),
                "write_requests": len(result.writes),
                "baseline_expected_cycles": baseline_cycles,
                "pipeline_expected_cycles": pipeline_cycles,
            })

        with (output_dir / "copy_vectors.txt").open(encoding="ascii") as stream:
            for case in copy_manifest["cases"]:
                header = [int(value, 16) for value in stream.readline().split()]
                if len(header) != 16:
                    raise ValueError("Malformed copy input for pipeline comparison")
                source, initial = [], []
                for _ in range(words):
                    src, dst, _ = (int(value, 16) for value in stream.readline().split())
                    source.append(src)
                    initial.append(dst)
                for _ in range(header[13] + header[14]):
                    if not stream.readline():
                        raise ValueError("Truncated copy input")
                emit(case["name"], Descriptor(*header[:8]), source, initial,
                     2 if header[8] else 0, header[9], header[10])

        for rows, cols in [(8, 8), (16, 16), (8, 32), (32, 8)]:
            source = [((i * 73) ^ 0x3D2A) & 0xFFFF for i in range(words)]
            initial = [(0xA55A ^ i) & 0xFFFF for i in range(words)]
            emit(f"copy_{rows}x{cols}_minimum_latency",
                 Descriptor(0, 2048, rows, cols, cols * 2, 2, cols * 2, 2), source, initial, 0)
        emit("transpose_32x32_minimum_latency",
             Descriptor(0, 2048, 32, 32, 64, 2, 2, 64), source, initial, 0)
        emit("read_fault_with_stalled_write_and_full_fifo",
             Descriptor(0, 2048, 1, 32, 64, 2, 64, 2), source, initial, 0, 1, 4, 1)
        emit("write_fault_with_offered_read_stalled",
             Descriptor(0, 2048, 1, 32, 64, 2, 64, 2), source, initial, 0, 2, 0, 2)

    manifest = {"total_descriptors": len(cases), "endpoint_words": words,
                "timing_seed": seed ^ 0x74A913E5,
                "whole_memory_checks_per_engine": len(cases) * words, "cases": cases}
    (output_dir / "pipeline_manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest
