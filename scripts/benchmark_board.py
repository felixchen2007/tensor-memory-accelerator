"""Compare saved board runs, or explicitly program validated volatile images with --hardware."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from model.board_benchmark import compare_runs
from scripts.build_board import find_quartus_bin


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check_sources(record: dict) -> None:
    if record["status"] != "pass" or any(digest(ROOT / n) != h for n, h in record["sha256"].items()):
        raise RuntimeError("Validation is missing or source hashes changed; no programming performed")


def hardware_runs(include_burst: bool = False) -> tuple[list[dict], Path]:
    sim_path = ROOT / "build/sdram_sim/results.json"
    sim = json.loads(sim_path.read_text())
    check_sources(sim)
    variants = {}
    configurations = [("serialized", "de10_lite_serialized", "serialized", 1, "de10_lite_serialized"),
                      ("pipelined", "de10_lite", "pipelined", 1, "de10_lite")]
    if include_burst:
        configurations.append(("pipelined_burst4", "de10_lite_burst4", "pipelined", 4, "de10_lite_burst4"))
    for variant, directory, engine, read_burst, sim_name in configurations:
        path = ROOT / "build/quartus" / directory
        board_path = path / "board_results.json"
        board = json.loads(board_path.read_text())
        check_sources(board)
        if board["configuration"] != {"engine": engine, "operation": "transpose32", "refresh_aligned": True,
                                      "read_burst_words": read_burst}:
            raise RuntimeError("Unexpected fitted benchmark configuration")
        image = path / "output_files/tma_de10_lite.sof"
        if digest(image) != board["sof_sha256"]:
            raise RuntimeError("Programming image differs from its fitted validation")
        test = sim["summaries"][sim_name]
        if (test["decoded_probe"]["engine"] != engine or test["decoded_probe"]["status"] != "pass"
                or test["decoded_probe"]["read_burst_words"] != read_burst):
            raise RuntimeError("Missing passing simulation for the fitted engine")
        variants[variant] = (board_path, board, image)
    if any(v[1]["sha256"] != variants["serialized"][1]["sha256"] for v in variants.values()):
        raise RuntimeError("The two fits used different sources or constraints")

    tool_dir = find_quartus_bin()
    suffix = ".exe" if os.name == "nt" else ""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    folder = ROOT / "build/hardware" / f"{stamp}_engine_benchmark"
    folder.mkdir(parents=True)
    shutil.copy2(sim_path, folder / "simulation_results.json")
    sources = dict(sim["sha256"])
    sources.update(variants["pipelined"][1]["sha256"])
    for name, expected in sources.items():
        source = (ROOT / name).resolve()
        if not source.is_relative_to(ROOT) or digest(source) != expected:
            raise RuntimeError("Source snapshot changed")
        target = folder / "sources" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    runs = []
    # Alternate images and finish with the optimized version loaded.
    order = list(variants) * 2
    for index, variant in enumerate(order):
        board_path, board, image = variants[variant]
        engine = board["configuration"]["engine"]
        check_sources(board)
        if digest(image) != board["sof_sha256"]:
            raise RuntimeError("Image changed during benchmark")
        run_dir = folder / f"{index}_{variant}"
        run_dir.mkdir()
        shutil.copy2(image, run_dir / image.name)
        shutil.copy2(board_path, run_dir / "board_results.json")
        scan = subprocess.run([str(tool_dir / f"jtagconfig{suffix}"), "--debug"],
                              text=True, capture_output=True)
        (run_dir / "jtag_scan.log").write_text(scan.stdout + scan.stderr, encoding="utf-8")
        if (scan.returncode or "031050DD" not in scan.stdout or "USB-Blaster [USB-0]" not in scan.stdout
                or "JTAG chain broken" in scan.stdout):
            raise RuntimeError(f"Expected board is not connected; see {run_dir / 'jtag_scan.log'}")
        programmed = subprocess.run([str(tool_dir / f"quartus_pgm{suffix}"), "-m", "JTAG",
            "-c", "USB-Blaster [USB-0]", "-o", f"p;{image}@1"], text=True, capture_output=True)
        output = programmed.stdout + programmed.stderr
        (run_dir / "programming.log").write_text(output, encoding="utf-8")
        success = (programmed.returncode == 0 and "Configuration succeeded -- 1 device(s) configured" in output
                   and "Successfully performed operation(s)" in output)
        record = {"timestamp_utc": datetime.now(timezone.utc).isoformat(), "scope": "volatile FPGA configuration",
                  "configuration": board["configuration"], "programming_succeeded": success,
                  "sof_sha256": board["sof_sha256"], "source_sha256": board["sha256"],
                  "resources": board["resources"], "nominal_core_hz": 50_000_000}
        record_path = run_dir / "run.json"
        record_path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
        if not success:
            raise RuntimeError(f"Volatile programming failed; see {run_dir}")
        read = subprocess.run([sys.executable, str(ROOT / "scripts/read_board_status.py"), "--hardware"],
                              cwd=ROOT, text=True, capture_output=True)
        if read.returncode:
            (run_dir / "read_error.log").write_text(read.stdout + read.stderr, encoding="utf-8")
            raise RuntimeError(f"Probe read failed; see {run_dir}")
        probe = json.loads(read.stdout)
        transcript = Path(probe["transcript"])
        shutil.copy2(transcript, run_dir / "probe.log")
        (run_dir / "probe.json").write_text(json.dumps(probe, indent=2) + "\n", encoding="utf-8")
        record["status"] = probe["status"]
        record_path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
        status = record["status"]
        if (status["status"] != "pass" or status["engine"] != engine
                or status["read_burst_words"] != board["configuration"]["read_burst_words"]):
            raise RuntimeError(f"Hardware did not pass as the expected engine; see {record_path}")
        runs.append(record)
        print(f"BOARD_RUN_PASS variant={variant} cycles={status['elapsed_cycles']} record={record_path}", flush=True)
    check_sources(sim)
    return runs, folder


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--hardware", action="store_true", help="Program each validated SOF twice; no flash writes")
    mode.add_argument("--records", nargs="+", type=Path, help="Analyze four saved run.json files without hardware")
    parser.add_argument("--include-burst", action="store_true", help="Also measure the validated pipelined BL4 image")
    args = parser.parse_args()
    if args.hardware:
        runs, folder = hardware_runs(args.include_burst)
    else:
        runs = [json.loads(path.read_text()) for path in args.records]
        folder = None
    result = compare_runs(runs)
    if folder:
        result["timestamp_utc"] = datetime.now(timezone.utc).isoformat()
        result["run_records"] = [str(p.relative_to(ROOT)) for p in sorted(folder.glob("*/run.json"))]
        (folder / "results.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        print(f"BENCHMARK_RECORD={folder / 'results.json'}", flush=True)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError, ValueError, KeyError) as exc:
        print(f"BOARD_BENCHMARK_FAILED: {exc}", file=sys.stderr)
        raise SystemExit(1)
