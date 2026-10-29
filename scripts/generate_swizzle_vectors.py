"""Fixed logical requests and independent bank-occupancy expectations."""

import json
from pathlib import Path
import random

from model.bank_layout import BankLayout


def generate_swizzle_vectors(output_dir: Path, seed: int) -> dict:
    rng = random.Random(seed ^ 0x5A17B34C)
    layouts = [BankLayout(), *(BankLayout(swizzle=True, shift=s) for s in (3, 4, 5))]
    variants = ["linear", "xor3", "xor4", "xor5"]
    cases = []

    def add(name, family, words, *, rows=0, cols=0, pitch=0, stalled=False, write=False):
        expected = [layout.service_cycles(words) for layout in layouts]
        expected_denied = []
        for layout in layouts:
            occupancy = [0] * 4
            for word in words:
                occupancy[layout.decode(word)[0]] += 1
            expected_denied.append(sum(count * (count - 1) // 2 for count in occupancy))
        cases.append({
            "id": len(cases), "name": name, "family": family, "words": words,
            "rows": rows, "cols": cols, "pitch": pitch, "stalled": int(stalled),
            "write": int(write), "write_word": rng.randrange(4096) if write else 0,
            "write_data": rng.getrandbits(16) if write else 0,
            "expected_issue_cycles": expected,
            "expected_conflict_cycles": [cycles - 1 for cycles in expected],
            "expected_denied_requests": expected_denied,
        })

    # Full readback before and after workload writes checks every logical word.
    for start in range(0, 4096, 4):
        add(f"initial_readback_{start}", "initial_readback", list(range(start, start + 4)))
    for rows, cols, pitch in [(8, 8, 8), (16, 16, 16), (32, 32, 32),
                              (8, 32, 32), (32, 8, 8), (8, 16, 16), (16, 8, 8),
                              (8, 8, 12), (8, 8, 20), (8, 8, 36),
                              (16, 16, 20), (8, 32, 36)]:
        base = 128
        for row in range(rows):
            for col in range(0, cols, 4):
                add(f"row_{rows}x{cols}_pitch{pitch}_r{row}_c{col}", "row",
                    [base + row * pitch + col + lane for lane in range(4)],
                    rows=rows, cols=cols, pitch=pitch)
        for col in range(cols):
            for row in range(0, rows, 4):
                add(f"column_{rows}x{cols}_pitch{pitch}_r{row}_c{col}", "column",
                    [base + (row + lane) * pitch + col for lane in range(4)],
                    rows=rows, cols=cols, pitch=pitch)
    add("diagonal_stride33", "diagonal", [0, 33, 66, 99])
    add("diagonal_stride17", "diagonal", [0, 17, 34, 51])
    add("diagonal_stride9", "diagonal", [0, 9, 18, 27])
    add("buffer_boundary", "boundary", [2046, 2047, 2048, 2049])
    add("last_four_words", "boundary", [4092, 4093, 4094, 4095])
    add("repeated_same_word", "repeated", [99, 99, 99, 99])
    for stride in (1, 2, 3, 4, 5, 7, 8, 12, 15, 16, 17, 20, 31, 32, 33, 36, 63, 64, 65, 128, 129):
        for base in (0, 1, 31):
            add(f"stride{stride}_base{base}", "stride",
                [base + lane * stride for lane in range(4)], write=bool(rng.getrandbits(1)))
    for index in range(100):
        add(f"random_{index}", "random", [rng.randrange(4096) for _ in range(4)], write=index % 3 == 0)
    for index in range(32):
        add(f"backpressure_{index}", "backpressure", [rng.randrange(4096) for _ in range(4)],
            stalled=True, write=True)
    for start in range(0, 4096, 4):
        add(f"final_readback_{start}", "final_readback", list(range(start, start + 4)))

    output_dir.mkdir(parents=True, exist_ok=True)
    with (output_dir / "swizzle_vectors.txt").open("w", encoding="ascii") as stream:
        for case in cases:
            fields = (*case["words"], *case["expected_issue_cycles"], case["stalled"],
                      case["write"], case["write_word"], case["write_data"])
            stream.write(" ".join(f"{value:x}" for value in fields) + "\n")
    manifest = {
        "seed": seed ^ 0x5A17B34C, "variants": variants, "total_batches": len(cases),
        "expected_responses": len(cases) * 4 * 4, "full_readback_words_per_variant": 8192,
        "workload_writes": sum(case["write"] for case in cases), "cases": cases,
    }
    (output_dir / "swizzle_manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest
