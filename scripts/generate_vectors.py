"""Generate deterministic independent address expectations for the RTL scoreboard."""

import json
import random
from pathlib import Path

from model.address_model import Descriptor, addresses


def generate_vectors(output_dir: Path, seed: int, random_cases: int) -> dict:
    if random_cases < 0:
        raise ValueError("random_cases must be nonnegative")
    rng = random.Random(seed)
    cases = [
        Descriptor(0x1000, 0x2000, 1, 1, 2, 2, 2, 2),
        Descriptor(0x1000, 0x2000, 1, 9, 32, 2, 32, 2),
        Descriptor(0x1000, 0x2000, 9, 1, 32, 2, 48, 2),
        Descriptor(0x1000, 0x2000, 2, 3, 6, 2, 2, 4),
        Descriptor(0x1000, 0x2000, 7, 5, 128, 2, 256, 2),
        Descriptor(0, 0, 0, 0, 0, 0, 0, 0),
        Descriptor(0, 0, 0, 7, 0, 0, 0, 0),
        Descriptor(0, 0, 7, 0, 0, 0, 0, 0),
        Descriptor(0x80, 0x80, 3, 4, 0, 0, 0, 0),
        Descriptor(0xFFFFFFFE, 0xFFFFFFFC, 3, 4, 16, 2, 32, 4),
        Descriptor(0x1000, 0x2000, 65535, 1, 2, 2, 4, 2),
        Descriptor(0x1000, 0x2000, 1, 65535, 2, 2, 4, 2),
    ]
    for _ in range(random_cases):
        cases.append(Descriptor(
            rng.getrandbits(32), rng.getrandbits(32),
            rng.randrange(13), rng.randrange(13),
            rng.getrandbits(32), rng.getrandbits(32),
            rng.getrandbits(32), rng.getrandbits(32)))

    output_dir.mkdir(parents=True, exist_ok=True)
    with (output_dir / "vectors.txt").open("w", encoding="ascii") as stream:
        for desc in cases:
            desc.validate()
            fields = (desc.src_base, desc.dst_base, desc.rows, desc.cols,
                      desc.src_row_stride, desc.src_col_stride,
                      desc.dst_row_stride, desc.dst_col_stride, desc.element_count)
            stream.write(" ".join(f"{value:x}" for value in fields) + "\n")
            for src, dst, last in addresses(desc):
                stream.write(f"{src:08x} {dst:08x} {int(last):x}\n")
    manifest = {
        "descriptor_seed": seed,
        "random_descriptors": random_cases,
        "directed_descriptors": len(cases) - random_cases,
        "total_descriptors": len(cases),
        "expected_address_pairs": sum(d.element_count for d in cases),
        "empty_descriptors": sum(d.is_empty for d in cases),
        "addr_width": 32,
        "count_width": 16,
        "stall_seed": "0x6d2b79f5",
    }
    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest
