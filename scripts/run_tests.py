"""Run address and data-copy regressions, or explicitly select model-only."""

import argparse
import csv
import hashlib
import json
import os
import re
from pathlib import Path
import shutil
import subprocess
import sys
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.generate_vectors import generate_vectors
from scripts.generate_copy_vectors import generate_copy_vectors
from scripts.generate_local_vectors import generate_local_vectors
from scripts.generate_pipeline_vectors import generate_pipeline_vectors
from scripts.generate_swizzle_vectors import generate_swizzle_vectors
from scripts.run_sdram_tests import SDRAM_SOURCES, run_sdram_suite
from scripts.run_uvm_tests import UVM_SOURCES, run_uvm_suite


def run(command: list[str], cwd: Path) -> str:
    result = subprocess.run(command, cwd=cwd, text=True, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, errors="replace")
    print(result.stdout, end="", flush=True)
    if result.returncode:
        raise RuntimeError(f"{Path(command[0]).name} exited with {result.returncode}")
    return result.stdout


def find_questa() -> Path:
    candidates = []
    if os.environ.get("QUESTA_BIN"):
        candidates.append(Path(os.environ["QUESTA_BIN"]))
    on_path = shutil.which("vsim")
    if on_path:
        candidates.append(Path(on_path).parent)
    for root in (Path("C:/altera_lite"), Path("C:/intelFPGA_lite")):
        if root.is_dir():
            candidates.extend(sorted(root.glob("*/questa_fse/win64"), reverse=True))
    suffix = ".exe" if os.name == "nt" else ""
    for candidate in candidates:
        if all((candidate / f"{tool}{suffix}").is_file()
               for tool in ("vlib", "vlog", "vsim")):
            return candidate
    raise RuntimeError("Questa not found. Set QUESTA_BIN or use --model-only explicitly.")


def run_pipeline_comparison(tool, output_dir: Path, manifest: dict) -> dict:
    (output_dir / "pipeline_metrics.csv").unlink(missing_ok=True)
    transcript = run([
        tool("vsim"), "-c", "-onfinish", "stop", "-l", "pipeline_simulation.log",
        "work.tb_tma_pipeline_comparison", "+PIPELINE_VECTORS=pipeline_vectors.txt",
        f"+TIMING_SEED={manifest['timing_seed']:x}", "-do", "do run_sim.do"
    ], output_dir)
    (output_dir / "pipeline_console.log").write_text(transcript, encoding="utf-8")
    match = re.search(r"# TMA_PIPELINE_COMPARISON_PASS ([^\r\n]+)", transcript)
    if not match:
        raise RuntimeError("Paired pipeline comparison did not report its pass marker")
    fields = dict(field.split("=", 1) for field in match.group(1).split())
    summary = {k: int(v) if v.isdecimal() else v for k, v in fields.items()}
    with (output_dir / "pipeline_metrics.csv").open(newline="", encoding="ascii") as stream:
        metrics = [{k: int(v) for k, v in row.items()} for row in csv.DictReader(stream)]
    if len(metrics) != manifest["total_descriptors"]:
        raise RuntimeError("Pipeline comparison omitted descriptors")
    for measured, expected in zip(metrics, manifest["cases"]):
        for key in ("id", "completed_elements", "error_code", "write_requests"):
            if measured[key] != expected[key]:
                raise RuntimeError(f"Pipeline metrics disagree with oracle: {key}")
        if measured["baseline_reads"] != expected["minimum_reads"]:
            raise RuntimeError("Baseline request count changed")
        if not expected["minimum_reads"] <= measured["pipeline_reads"] <= expected["maximum_reads"]:
            raise RuntimeError("Pipeline prefetch escaped its legal read prefix")
        for name in ("baseline", "pipeline"):
            expected_cycles = expected[f"{name}_expected_cycles"]
            if expected_cycles and measured[f"{name}_cycles"] != expected_cycles:
                raise RuntimeError("Pipeline comparison ideal schedule mismatch")
        measured["name"] = expected["name"]
        measured["speedup"] = (measured["baseline_cycles"] / measured["pipeline_cycles"]
                               if expected["error_code"] == 0 else None)
    (output_dir / "pipeline_metrics.json").write_text(
        json.dumps(metrics, indent=2) + "\n", encoding="utf-8")
    lines = ["# Paired transfer-engine measurements", "",
             "Both engines use identical data and per-transaction service delays.",
             "Ratios compare this project's serialized and pipelined RTL; no hardware frequency or board bandwidth is measured.", "",
             "| Case | Timing mode | Serialized cycles | Pipelined cycles | Speedup |",
             "| --- | --- | --- | --- | --- |"]
    for measured, expected in zip(metrics, manifest["cases"]):
        if expected["error_code"] == 0 and (expected["mode"] == 0 or
                expected["name"] == "copy_32x32_variable_latency"):
            lines.append(f"| {expected['name']} | {expected['mode']} | {measured['baseline_cycles']} | "
                         f"{measured['pipeline_cycles']} | {measured['speedup']:.3f}x |")
    lines += ["", "Mode 0: always-ready requests and next-cycle responses.",
              "Mode 2: deterministic transaction-indexed request gaps and response delays.",
              "Single-word transfers expose pipeline startup/drain overhead.", ""]
    (output_dir / "pipeline_comparison.md").write_text("\n".join(lines), encoding="utf-8")
    return summary


def run_swizzle_comparison(tool, output_dir: Path, manifest: dict) -> dict:
    (output_dir / "swizzle_metrics.csv").unlink(missing_ok=True)
    transcript = run([tool("vsim"), "-c", "-onfinish", "stop", "-l", "swizzle_simulation.log",
                      "work.tb_tma_swizzle_comparison", "+SWIZZLE_VECTORS=swizzle_vectors.txt",
                      "-do", "do run_sim.do"], output_dir)
    (output_dir / "swizzle_console.log").write_text(transcript, encoding="utf-8")
    match = re.search(r"# TMA_SWIZZLE_COMPARISON_PASS ([^\r\n]+)", transcript)
    if not match:
        raise RuntimeError("Swizzle comparison did not report its pass marker")
    fields = dict(field.split("=", 1) for field in match.group(1).split())
    summary = {key: int(value) if value.isdecimal() else value for key, value in fields.items()}
    with (output_dir / "swizzle_metrics.csv").open(newline="", encoding="ascii") as stream:
        metrics = [{key: int(value) for key, value in row.items()} for row in csv.DictReader(stream)]
    if len(metrics) != 4 * manifest["total_batches"] or summary["responses"] != manifest["expected_responses"]:
        raise RuntimeError("Swizzle comparison omitted cases/responses")
    for index, measured in enumerate(metrics):
        expected = manifest["cases"][index // 4]
        mode = index % 4
        if measured["id"] != expected["id"] or measured["variant"] != mode:
            raise RuntimeError("Swizzle comparison case order mismatch")
        if measured["stalled"] != expected["stalled"]:
            raise RuntimeError("Swizzle comparison readiness policy mismatch")
        if not expected["stalled"] and (measured["issue_cycles"] != expected["expected_issue_cycles"][mode]
                or measured["completion_cycles"] != expected["expected_issue_cycles"][mode] + 1):
            raise RuntimeError("Swizzle service span differs from bank occupancy oracle")
        if not expected["stalled"] and (
                measured["conflict_cycles"] != expected["expected_conflict_cycles"][mode] or
                measured["denied_requests"] != expected["expected_denied_requests"][mode]):
            raise RuntimeError("Swizzle conflict counters differ from bank occupancy oracle")
        measured.update({key: expected[key] for key in ("name", "family", "rows", "cols", "pitch")})
        measured["layout"] = manifest["variants"][mode]
    (output_dir / "swizzle_metrics.json").write_text(json.dumps(metrics, indent=2) + "\n", encoding="utf-8")
    selections = [("row", 32, 32, 32), ("column", 8, 8, 8), ("column", 16, 16, 16),
                  ("column", 32, 32, 32), ("column", 8, 8, 12), ("column", 8, 8, 20),
                  ("column", 8, 8, 36), ("diagonal_stride33", 0, 0, 0), ("buffer_boundary", 0, 0, 0)]
    lines = ["# Bank-layout comparison", "", "Same four-lane logical requests, data, clock, and response-ready schedule.",
             "Values below are mean request-issue spans for one four-word batch, with all responses ready.", "",
             "| Pattern | Linear | XOR shift 3 | XOR shift 4 | XOR shift 5 |",
             "| --- | --- | --- | --- | --- |"]
    for family, rows, cols, pitch in selections:
        selected = [item for item in metrics if not item["stalled"] and
                    ((item["family"], item["rows"], item["cols"], item["pitch"]) == (family, rows, cols, pitch)
                     or item["name"] == family)]
        values = []
        for mode in range(4):
            data = [item["issue_cycles"] for item in selected if item["variant"] == mode]
            values.append(sum(data) / len(data))
        label = f"{rows}x{cols} {family}, row stride {pitch} words" if rows else family
        lines.append("| " + label + " | " + " | ".join(f"{value:.3f}" for value in values) + " |")
    lines += ["", "A four-word batch completes one cycle after its request-issue span in this all-ready model.",
              "For 32-word column stride, shift 5 changes issue span 4 -> 1 and completion span 5 -> 2.",
              "The stride-33 diagonal regresses: issue span 1 -> 4, completion span 2 -> 5.",
              "These are four-lane scratchpad measurements, not single-stream copy or SDRAM speedups.", ""]
    (output_dir / "swizzle_comparison.md").write_text("\n".join(lines), encoding="utf-8")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-only", action="store_true")
    parser.add_argument("--seed", type=int, default=20261025)
    parser.add_argument("--random-cases", type=int, default=200)
    parser.add_argument("--copy-random-cases", type=int, default=100)
    parser.add_argument("--local-random-cases", type=int, default=12)
    scope = parser.add_mutually_exclusive_group()
    scope.add_argument("--pipeline-only", action="store_true",
                        help="Run the paired pipeline suite only; does not establish a full regression pass")
    scope.add_argument("--swizzle-only", action="store_true",
                       help="Run the four-layout comparison only; does not establish a full regression pass")
    args = parser.parse_args()
    if min(args.random_cases, args.copy_random_cases, args.local_random_cases) < 0:
        parser.error("Random-case counts must be nonnegative")

    sources = ["rtl/tma_addr_gen.sv", "tb/tb_tma_addr_gen.sv",
               "model/address_model.py", "tests/test_address_model.py",
               "scripts/generate_vectors.py", "scripts/run_tests.py",
               "rtl/tma_copy_engine.sv", "tb/tb_tma_copy_engine.sv",
               "model/copy_model.py", "tests/test_copy_model.py",
               "scripts/generate_copy_vectors.py", "scripts/generate_local_vectors.py",
               "rtl/tma_ram_bank.sv", "rtl/tma_scratchpad.sv",
               "rtl/tma_scratchpad_endpoint.sv", "rtl/tma_local_copy_system.sv",
               "tb/tb_tma_scratchpad.sv", "tb/tb_tma_local_copy_system.sv",
               "quartus/synth.tcl", "rtl/tma_copy_engine_pipelined.sv",
               "rtl/tma_copy_engine_select.sv", "tb/tma_paired_memory_model.sv",
               "tb/tb_tma_pipeline_comparison.sv", "scripts/generate_pipeline_vectors.py",
               "model/bank_layout.py", "tests/test_bank_layout.py",
               "scripts/generate_swizzle_vectors.py", "tb/tb_tma_swizzle_comparison.sv"]
    sources += SDRAM_SOURCES
    source_hashes = {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
                     for name in sources + UVM_SOURCES}

    output_dir = ROOT / "build" / "sim"
    output_dir.mkdir(parents=True, exist_ok=True)
    # A failed or model-only rerun must not leave a stale successful RTL summary.
    result_file = "pipeline_only_results.json" if args.pipeline_only else (
        "swizzle_only_results.json" if args.swizzle_only else "results.json")
    result_path = output_dir / result_file
    result_path.unlink(missing_ok=True)
    run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"], ROOT)
    manifest = generate_vectors(output_dir, args.seed, args.random_cases)
    print(json.dumps(manifest, indent=2), flush=True)
    copy_manifest = generate_copy_vectors(output_dir, args.seed, args.copy_random_cases)
    print("Copy vectors: " + json.dumps({k: v for k, v in copy_manifest.items()
                                       if k != "cases"}), flush=True)
    local_manifest = generate_local_vectors(output_dir, copy_manifest, args.local_random_cases)
    print("Local RAM vectors: " + json.dumps({k: v for k, v in local_manifest.items()
                                            if k != "cases"}), flush=True)
    pipeline_manifest = generate_pipeline_vectors(output_dir, copy_manifest, args.seed)
    print("Paired pipeline vectors: " + json.dumps({k: v for k, v in pipeline_manifest.items()
                                                  if k != "cases"}), flush=True)
    swizzle_manifest = generate_swizzle_vectors(output_dir, args.seed)
    print("Bank-layout vectors: " + json.dumps({k: v for k, v in swizzle_manifest.items()
                                              if k != "cases"}), flush=True)
    if args.model_only:
        print("MODEL_ONLY_PASS: RTL simulation was not run.")
        return 0

    tool_dir = find_questa()
    suffix = ".exe" if os.name == "nt" else ""
    tool = lambda name: str(tool_dir / f"{name}{suffix}")
    version = run([tool("vsim"), "-version"], output_dir).strip()
    if not (output_dir / "work").exists():
        run([tool("vlib"), "work"], output_dir)
    run([tool("vlog"), "-sv", "-work", "work",
         str(ROOT / "rtl" / "tma_addr_gen.sv"),
         str(ROOT / "rtl" / "tma_copy_engine.sv"),
         str(ROOT / "rtl" / "tma_copy_engine_pipelined.sv"),
         str(ROOT / "rtl" / "tma_copy_engine_select.sv"),
         str(ROOT / "rtl" / "tma_ram_bank.sv"),
         str(ROOT / "rtl" / "tma_scratchpad.sv"),
         str(ROOT / "rtl" / "tma_scratchpad_endpoint.sv"),
         str(ROOT / "rtl" / "tma_local_copy_system.sv"),
         str(ROOT / "tb" / "tb_tma_addr_gen.sv"),
         str(ROOT / "tb" / "tb_tma_copy_engine.sv"),
         str(ROOT / "tb" / "tb_tma_scratchpad.sv"),
         str(ROOT / "tb" / "tb_tma_local_copy_system.sv"),
         str(ROOT / "tb" / "tma_paired_memory_model.sv"),
         str(ROOT / "tb" / "tb_tma_pipeline_comparison.sv"),
         str(ROOT / "tb" / "tb_tma_swizzle_comparison.sv"),
         *[str(ROOT / name) for name in SDRAM_SOURCES if name.endswith(".sv")]], output_dir)
    (output_dir / "run_sim.do").write_text(
        "onerror {quit -code 1}\nrun -all\nquit -code 0\n", encoding="ascii")
    if args.swizzle_only:
        summary = run_swizzle_comparison(tool, output_dir, swizzle_manifest)
        if any(hashlib.sha256((ROOT / name).read_bytes()).hexdigest() != expected
               for name, expected in source_hashes.items()):
            raise RuntimeError("Sources changed during swizzle-only verification")
        result_path.write_text(json.dumps({"status": "pass", "scope": "swizzle-only",
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "comparison": summary, "sha256": source_hashes}, indent=2) + "\n", encoding="utf-8")
        print("SWIZZLE_ONLY_PASS: full regression was not run.")
        return 0
    if args.pipeline_only:
        summary = run_pipeline_comparison(tool, output_dir, pipeline_manifest)
        if any(hashlib.sha256((ROOT / name).read_bytes()).hexdigest() != expected
               for name, expected in source_hashes.items()):
            raise RuntimeError("Sources changed during pipeline-only verification")
        result_path.write_text(json.dumps({"status": "pass", "scope": "pipeline-only",
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "comparison": summary, "sha256": source_hashes}, indent=2) + "\n", encoding="utf-8")
        print("PIPELINE_ONLY_PASS: full regression was not run.")
        return 0
    transcript = run([
        tool("vsim"), "-c", "-onfinish", "stop", "-l", "simulation.log",
        "work.tb_tma_addr_gen", "+VECTORS=vectors.txt",
        "-do", "do run_sim.do"
    ], output_dir)
    (output_dir / "console.log").write_text(transcript, encoding="utf-8")
    if "TMA_ADDR_GEN_PASS" not in transcript:
        raise RuntimeError("Simulation did not report the required pass marker")
    (output_dir / "copy_metrics.csv").unlink(missing_ok=True)
    copy_transcript = run([
        tool("vsim"), "-c", "-onfinish", "stop", "-l", "copy_simulation.log",
        "work.tb_tma_copy_engine", "+COPY_VECTORS=copy_vectors.txt",
        "-do", "do run_sim.do"
    ], output_dir)
    (output_dir / "copy_console.log").write_text(copy_transcript, encoding="utf-8")
    if "TMA_COPY_ENGINE_PASS" not in copy_transcript:
        raise RuntimeError("Copy simulation did not report the required pass marker")
    with (output_dir / "copy_metrics.csv").open(newline="", encoding="ascii") as stream:
        metrics = [{k: int(v) for k, v in row.items()} for row in csv.DictReader(stream)]
    if len(metrics) != copy_manifest["total_descriptors"]:
        raise RuntimeError("Copy metrics did not cover all generated descriptors")
    for measured, expected in zip(metrics, copy_manifest["cases"]):
        for key in ("id", "completed_elements", "error_code", "read_requests", "write_requests"):
            if measured[key] != expected[key]:
                raise RuntimeError(f"Copy metrics disagree with oracle: {key}")
        measured["name"] = expected["name"]
    (output_dir / "copy_metrics.json").write_text(
        json.dumps(metrics, indent=2) + "\n", encoding="utf-8")
    new_summaries = {}
    for top, stem, marker, plusargs in [
        ("tb_tma_scratchpad", "scratchpad", "TMA_SCRATCHPAD_PASS", []),
        ("tb_tma_scratchpad", "scratchpad_swizzled", "TMA_SCRATCHPAD_PASS", ["-gSWIZZLE=1"]),
        ("tb_tma_local_copy_system", "local", "TMA_LOCAL_COPY_PASS", ["+LOCAL_VECTORS=local_vectors.txt"]),
        ("tb_tma_local_copy_system", "local_pipeline", "TMA_LOCAL_COPY_PASS",
         ["-gPIPELINED=1", "+LOCAL_VECTORS=local_vectors.txt", "+METRICS=local_pipeline_metrics.csv"]),
        ("tb_tma_local_copy_system", "local_pipeline_swizzle", "TMA_LOCAL_COPY_PASS",
         ["-gPIPELINED=1", "-gSWIZZLE=1", "+LOCAL_VECTORS=local_vectors.txt", "+METRICS=local_pipeline_swizzle_metrics.csv"]),
    ]:
        if stem.startswith("local"):
            (output_dir / f"{stem}_metrics.csv").unlink(missing_ok=True)
        transcript = run([tool("vsim"), "-c", "-onfinish", "stop", "-l",
                          f"{stem}_simulation.log", f"work.{top}", *plusargs,
                          "-do", "do run_sim.do"], output_dir)
        (output_dir / f"{stem}_console.log").write_text(transcript, encoding="utf-8")
        match = re.search(r"# " + marker + r" ([^\r\n]+)", transcript)
        if not match:
            raise RuntimeError(f"{top} did not report its required pass marker")
        fields = dict(field.split("=", 1) for field in match.group(1).split())
        new_summaries[stem] = {k: int(v) if v.isdecimal() else v for k, v in fields.items()}
    for stem in ("local", "local_pipeline", "local_pipeline_swizzle"):
        with (output_dir / f"{stem}_metrics.csv").open(newline="", encoding="ascii") as stream:
            local_metrics = [{k: int(v) for k, v in row.items()} for row in csv.DictReader(stream)]
        if len(local_metrics) != local_manifest["total_descriptors"]:
            raise RuntimeError("Local RAM metrics did not cover all generated descriptors")
        for measured, expected in zip(local_metrics, local_manifest["cases"]):
            for key in ("id", "completed_elements", "error_code"):
                if measured[key] != expected[key]:
                    raise RuntimeError(f"Local RAM metrics disagree with oracle: {key}")
            cycles = expected["expected_cycles"]
            if cycles and stem.startswith("local_pipeline"):
                cycles = expected["completed_elements"] + 6
            if cycles and measured["elapsed_cycles"] != cycles:
                raise RuntimeError("Local RAM cycles disagree with the selected engine's schedule")
            measured["name"] = expected["name"]
        (output_dir / f"{stem}_metrics.json").write_text(
            json.dumps(local_metrics, indent=2) + "\n", encoding="utf-8")
    pipeline_summary = run_pipeline_comparison(tool, output_dir, pipeline_manifest)
    swizzle_summary = run_swizzle_comparison(tool, output_dir, swizzle_manifest)
    sdram_summary = run_sdram_suite(tool, output_dir)
    uvm_summary = run_uvm_suite(tool_dir, output_dir / "uvm" / "starter")
    if any(hashlib.sha256((ROOT / name).read_bytes()).hexdigest() != expected
           for name, expected in source_hashes.items()):
        raise RuntimeError("Sources changed during verification; rerun against a stable source tree")
    result = {
        "status": "pass",
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "python_version": sys.version,
        "simulator_directory": str(tool_dir),
        "simulator_version": version,
        "model_tests": "pass",
        "uvm": uvm_summary,
        **manifest,
        "copy_engine": {k: v for k, v in copy_manifest.items() if k != "cases"},
        "copy_reset_stages": 6,
        "scratchpad": new_summaries["scratchpad"],
        "scratchpad_swizzled": new_summaries["scratchpad_swizzled"],
        "local_copy": new_summaries["local"],
        "local_copy_pipelined": new_summaries["local_pipeline"],
        "local_copy_pipelined_swizzled": new_summaries["local_pipeline_swizzle"],
        "pipeline_comparison": pipeline_summary,
        "pipeline_timing_seed": pipeline_manifest["timing_seed"],
        "swizzle_comparison": swizzle_summary,
        "sdram": sdram_summary,
        "sha256": source_hashes,
    }
    result_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print("FULL_REGRESSION_PASS: build/sim/results.json")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"REGRESSION_FAILED: {exc}", file=sys.stderr)
        raise SystemExit(1)
