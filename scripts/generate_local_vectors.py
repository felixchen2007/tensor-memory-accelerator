"""Select copy-oracle cases for integration with the actual synthesizable RAMs."""

import json
from pathlib import Path


def generate_local_vectors(output_dir: Path, copy_manifest: dict,
                           random_cases: int = 12) -> dict:
    if random_cases < 0:
        raise ValueError("random_cases must be nonnegative")
    words = copy_manifest["endpoint_words"]
    selected = []
    random_selected = 0
    with (output_dir / "copy_vectors.txt").open(encoding="ascii") as source, \
            (output_dir / "local_vectors.txt").open("w", encoding="ascii") as target:
        for case in copy_manifest["cases"]:
            header = [int(value, 16) for value in source.readline().split()]
            if len(header) != 16:
                raise ValueError("Malformed copy vector header")
            body_count = words + header[13] + header[14]
            body = [source.readline() for _ in range(body_count)]
            if any(not line for line in body):
                raise ValueError("Truncated copy vector body")
            is_random = case["name"].startswith("random_")
            if header[9] != 0 or (is_random and random_selected >= random_cases):
                continue  # Physical RAM adapters do not inject read/write faults.
            if is_random:
                random_selected += 1
            header[8] = 0  # Actual endpoints have a synchronous one-cycle response.
            header[15] = 5 * case["elements"] + 1 if case["error_code"] == 0 else 0
            target.write(" ".join(f"{value:x}" for value in header) + "\n")
            target.writelines(body)
            selected.append({**case, "source_case_id": case["id"], "id": len(selected),
                             "timing_mode": 0, "expected_cycles": header[15]})
    manifest = {
        "total_descriptors": len(selected), "random_descriptors": random_selected,
        "directed_descriptors": len(selected) - random_selected,
        "endpoint_words": words, "whole_memory_checks": len(selected) * words,
        "cases": selected,
    }
    (output_dir / "local_manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest
