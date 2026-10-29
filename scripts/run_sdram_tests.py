"""Run the SDRAM subset, including deliberate failures of the checking model."""
import csv
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from model.board_status import decode_snapshot
SDRAM_SOURCES = [
    "rtl/tma_sdram_controller.sv", "rtl/tma_sdram_copy_system.sv",
    "rtl/tma_sdram_selftest.sv", "rtl/tma_board_clocks.sv", "rtl/tma_de10_lite.sv",
    "tb/tma_sdram_model.sv", "tb/tb_tma_sdram_controller.sv",
    "tb/tb_tma_sdram_copy_system.sv", "tb/tb_tma_de10_lite.sv",
    "scripts/run_sdram_tests.py", "scripts/build_board.py", "tests/test_board_reports.py", "quartus/build_board.tcl",
    "quartus/de10_lite_pins.tcl", "quartus/de10_lite.sdc", "quartus/report_board.tcl",
    "quartus/read_board_probe.tcl",
    "model/board_status.py", "tests/test_board_status.py", "scripts/read_board_status.py",
    "model/board_benchmark.py", "tests/test_board_benchmark.py", "scripts/benchmark_board.py",
]
DEPENDENCIES = ["rtl/tma_addr_gen.sv", "rtl/tma_copy_engine.sv",
    "rtl/tma_copy_engine_pipelined.sv", "rtl/tma_copy_engine_select.sv",
    "rtl/tma_ram_bank.sv", "rtl/tma_scratchpad.sv", "rtl/tma_scratchpad_endpoint.sv"]


def run_sdram_suite(tool, output_dir: Path) -> dict:
    summaries = {}

    def simulation(stem, top, args, marker=None, expected_failure=None):
        command = [tool("vsim"), "-c", "-L", "altera_mf_ver", "-L", "fiftyfivenm_ver",
                   "-onfinish", "stop", "-l", f"{stem}_simulation.log",
                   f"work.{top}", *args, "-do", "do run_sim.do"]
        result = subprocess.run(command, cwd=output_dir, text=True,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, errors="replace")
        (output_dir / f"{stem}_console.log").write_text(result.stdout, encoding="utf-8")
        if expected_failure:
            if expected_failure not in result.stdout or "** Fatal:" not in result.stdout:
                raise RuntimeError(f"{stem}: deliberate fault did not trigger its expected checker")
            if "_PASS " in result.stdout:
                raise RuntimeError(f"{stem}: deliberate fault incorrectly reported pass")
            print(f"EXPECTED_FAILURE_DETECTED: {stem}: {expected_failure}", flush=True)
            summaries[stem] = {"expected_failure_detected": True, "check": expected_failure}
            return
        match = re.search(r"# " + marker + r" ([^\r\n]+)", result.stdout)
        if result.returncode or not match:
            print(result.stdout, flush=True)
            raise RuntimeError(f"{stem} did not pass")
        fields = dict(field.split("=", 1) for field in match.group(1).split())
        summaries[stem] = {k: int(v) if v.isdecimal() else v for k, v in fields.items()}
        if top == "tb_tma_de10_lite":
            frame = re.search(r"# TMA_DEBUG_HEX=([0-9a-fA-F]+)", result.stdout)
            if not frame:
                raise RuntimeError(f"{stem}: diagnostic frame is missing")
            decoded = decode_snapshot(frame.group(1))
            expected = "pass" if marker == "TMA_DE10_LITE_PASS" else "fail"
            if decoded["status"] != expected:
                raise RuntimeError(f"{stem}: probe decoder disagrees with RTL verdict")
            summaries[stem]["decoded_probe"] = decoded
        print(marker + " " + match.group(1), flush=True)

    for stem, args in [("sdram_controller", []),
                       ("sdram_controller_early_data", ["-gT_AC=0.0"]),
                       ("sdram_controller_board_phase", ["-gSDRAM_PHASE_NS=5.0"]),
                       ("sdram_controller_refresh_stress", ["-gREFRESH_CYCLES=32"])]:
        simulation(stem, "tb_tma_sdram_controller", args, "TMA_SDRAM_CONTROLLER_PASS")
        if summaries[stem]["checks"] != 713 or summaries[stem]["dual_requests"] != 24:
            raise RuntimeError("Controller regression coverage changed")
    simulation("sdram_negative_refresh", "tb_tma_sdram_controller", ["+BREAK_REFRESH"],
               expected_failure="SDRAM_MODEL refresh deadline missed")
    simulation("sdram_negative_cas", "tb_tma_sdram_controller", ["-gREAD_SKEW_CYCLES=1"],
               expected_failure="SDRAM data mismatch")
    simulation("sdram_negative_setup", "tb_tma_sdram_controller", ["-gSDRAM_PHASE_NS=0.5"],
               expected_failure="SDRAM_MODEL command setup")
    simulation("sdram_negative_hold", "tb_tma_sdram_controller", ["-gSDRAM_PHASE_NS=19.5"],
               expected_failure="SDRAM_MODEL command hold")
    metrics = {}
    for pipeline in (0, 1):
        for swizzle in (0, 1):
            stem = f"sdram_copy_p{pipeline}_s{swizzle}"
            path = output_dir / f"{stem}_metrics.csv"
            path.unlink(missing_ok=True)
            simulation(stem, "tb_tma_sdram_copy_system",
                       [f"-gPIPELINED={pipeline}", f"-gSWIZZLE={swizzle}", f"+METRICS={path.name}"],
                       "TMA_SDRAM_COPY_PASS")
            if summaries[stem]["cases"] != 12 or summaries[stem]["destination_checks"] != 49152:
                raise RuntimeError("SDRAM integration coverage changed")
            with path.open(newline="", encoding="ascii") as stream:
                rows = [{k: v if k == "name" else int(v) for k, v in row.items()}
                        for row in csv.DictReader(stream)]
            if len(rows) != 12 or len({r["name"] for r in rows}) != 12:
                raise RuntimeError("SDRAM integration metrics missing cases")
            metrics[(pipeline, swizzle)] = rows
    for pipeline in (0, 1):
        # A one-lane scratchpad writer must have identical timings in both maps.
        left, right = metrics[(pipeline, 0)], metrics[(pipeline, 1)]
        for a, b in zip(left, right):
            for key in ("name", "completed_elements", "error_code", "elapsed_cycles"):
                if a[key] != b[key]:
                    raise RuntimeError(f"Layout changed single-stream SDRAM result: {key}")
    for a, b in zip(metrics[(0, 0)], metrics[(1, 0)]):
        for key in ("name", "completed_elements", "error_code"):
            if a[key] != b[key]:
                raise RuntimeError(f"Engine SDRAM results differ: {key}")
    simulation("de10_lite", "tb_tma_de10_lite", [], "TMA_DE10_LITE_PASS")
    simulation("de10_lite_serialized", "tb_tma_de10_lite", ["-gPIPELINED=0"], "TMA_DE10_LITE_PASS")
    for stem, engine in (("de10_lite", "pipelined"), ("de10_lite_serialized", "serialized")):
        if summaries[stem]["decoded_probe"]["engine"] != engine or summaries[stem]["refresh_phase"] != 1:
            raise RuntimeError("Board benchmark identity or refresh phase is incorrect")
    simulation("de10_lite_injected_failure", "tb_tma_de10_lite",
               ["-gEXPECT_FAIL=1", "-gREAD_XOR_MASK=1", "-gFAULT_STAGE=1"], "TMA_DE10_LITE_FAIL_DETECTED")
    simulation("de10_lite_scratch_failure", "tb_tma_de10_lite",
               ["-gEXPECT_FAIL=1", "-gFAULT_STAGE=2"], "TMA_DE10_LITE_FAIL_DETECTED")
    simulation("de10_lite_tensor_failure", "tb_tma_de10_lite",
               ["-gEXPECT_FAIL=1", "-gFAULT_STAGE=3"], "TMA_DE10_LITE_FAIL_DETECTED")
    lines = ["# SDRAM baseline comparison", "",
             "Pin-level simulation at 50 MHz, BL1, close-page policy, identical refresh start phase.",
             "These are simulated core cycles, not measured hardware bandwidth.", "",
             "| Workload | Serialized cycles | Pipelined cycles | Ratio |",
             "| --- | --- | --- | --- |"]
    comparison = []
    for a, b in zip(metrics[(0, 0)], metrics[(1, 0)]):
        if a["error_code"]:
            continue
        ratio = a["elapsed_cycles"] / b["elapsed_cycles"]
        lines.append(f"| {a['name']} | {a['elapsed_cycles']} | {b['elapsed_cycles']} | {ratio:.3f}x |")
        comparison.append({"name": a["name"], "serialized_cycles": a["elapsed_cycles"],
                           "pipelined_cycles": b["elapsed_cycles"], "ratio": ratio})
    (output_dir / "sdram_comparison.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    summaries["comparison"] = comparison
    for stem, args in (("sdram_burst_controller", ["-gREAD_BURST_WORDS=4", "-gSDRAM_PHASE_NS=5.0"]),
                       ("sdram_burst_early_stress", ["-gREAD_BURST_WORDS=4", "-gT_AC=0.0", "-gREFRESH_CYCLES=32"])):
        simulation(stem, "tb_tma_sdram_controller", args, "TMA_SDRAM_CONTROLLER_PASS")
        if summaries[stem]["checks"] != 721 or summaries[stem]["read_beats"] != 4*summaries[stem]["reads"]:
            raise RuntimeError("Burst controller coverage or beat count changed")
    simulation("sdram_negative_burst_mode", "tb_tma_sdram_controller", ["-gREAD_BURST_WORDS=4", "+BAD_BURST_MODE"],
               expected_failure="SDRAM_MODEL expected BL1/BL4 sequential CL3 single-write mode")
    burst_metrics = {}
    for pipeline in (0, 1):
        for swizzle in (0, 1):
            stem = f"sdram_burst_copy_p{pipeline}_s{swizzle}"
            path = output_dir / f"{stem}_metrics.csv"
            path.unlink(missing_ok=True)
            simulation(stem, "tb_tma_sdram_copy_system", [f"-gPIPELINED={pipeline}", f"-gSWIZZLE={swizzle}",
                       "-gREAD_BURST_WORDS=4", f"+METRICS={path.name}"], "TMA_SDRAM_COPY_PASS")
            if summaries[stem]["cases"] != 12 or summaries[stem]["destination_checks"] != 49152:
                raise RuntimeError("Burst integration coverage changed")
            with path.open(newline="", encoding="ascii") as stream:
                rows = [{k: v if k == "name" else int(v) for k, v in row.items()} for row in csv.DictReader(stream)]
            if len(rows) != 12:
                raise RuntimeError("Burst metrics missing cases")
            for baseline, burst in zip(metrics[(pipeline, swizzle)], rows):
                for key in ("name", "completed_elements", "error_code"):
                    if baseline[key] != burst[key]:
                        raise RuntimeError("Burst changed logical transfer results")
                if burst["read_beats"] != 4*burst["read_commands"]:
                    raise RuntimeError("Burst physical traffic count is inconsistent")
            burst_metrics[(pipeline, swizzle)] = rows
        if burst_metrics[(pipeline, 0)] != [dict(row, swizzle=0) for row in burst_metrics[(pipeline, 1)]]:
            raise RuntimeError("Layout changed burst single-stream behavior")
    simulation("de10_lite_burst4", "tb_tma_de10_lite", ["-gREAD_BURST_WORDS=4"], "TMA_DE10_LITE_PASS")
    simulation("de10_lite_burst_failure", "tb_tma_de10_lite",
               ["-gREAD_BURST_WORDS=4", "-gEXPECT_FAIL=1", "-gREAD_XOR_MASK=1", "-gFAULT_STAGE=1"],
               "TMA_DE10_LITE_FAIL_DETECTED")
    if summaries["de10_lite_burst4"]["decoded_probe"]["read_burst_words"] != 4:
        raise RuntimeError("Burst board identity is incorrect")
    burst_comparison = []
    lines = ["# Four-word read-prefetch comparison", "", "Simulated descriptors; identical refresh start phase.", "",
             "| Workload | Pipelined BL1 cycles | Pipelined BL4 cycles | Ratio | BL1 / BL4 READ commands | BL1 / BL4 data beats |",
             "| --- | --- | --- | --- | --- | --- |"]
    for base, burst in zip(metrics[(1, 0)], burst_metrics[(1, 0)]):
        if base["error_code"]:
            continue
        ratio = base["elapsed_cycles"]/burst["elapsed_cycles"]
        lines.append(f"| {base['name']} | {base['elapsed_cycles']} | {burst['elapsed_cycles']} | {ratio:.3f}x | "
                     f"{base['read_commands']} / {burst['read_commands']} | {base['read_beats']} / {burst['read_beats']} |")
        burst_comparison.append({"name": base["name"], "bl1_cycles": base["elapsed_cycles"],
            "bl4_cycles": burst["elapsed_cycles"], "ratio": ratio, "bl1_read_commands": base["read_commands"],
            "bl4_read_commands": burst["read_commands"], "bl1_read_beats": base["read_beats"],
            "bl4_read_beats": burst["read_beats"]})
    (output_dir / "burst_comparison.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    summaries["burst_comparison"] = burst_comparison
    return summaries


def main() -> int:
    from scripts.run_tests import find_questa, run
    from scripts.run_uvm_tests import UVM_SOURCES, run_uvm_suite
    names = DEPENDENCIES + SDRAM_SOURCES
    hashes = {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in names + UVM_SOURCES}
    output = ROOT / "build" / "sdram_sim"
    output.mkdir(parents=True, exist_ok=True)
    result_path = output / "results.json"
    result_path.unlink(missing_ok=True)
    tool_dir = find_questa()
    suffix = ".exe" if os.name == "nt" else ""
    tool = lambda name: str(tool_dir / f"{name}{suffix}")
    if not (output / "work").exists():
        run([tool("vlib"), "work"], output)
    run([tool("vlog"), "-sv", "-work", "work",
         *[str(ROOT / name) for name in names if name.endswith(".sv")]], output)
    (output / "run_sim.do").write_text("onerror {quit -code 1}\nrun -all\nquit -code 0\n", encoding="ascii")
    summaries = run_sdram_suite(tool, output)
    summaries["uvm"] = run_uvm_suite(tool_dir, output / "uvm" / "starter")
    if any(hashlib.sha256((ROOT / name).read_bytes()).hexdigest() != expected
           for name, expected in hashes.items()):
        raise RuntimeError("Sources changed during SDRAM verification")
    result_path.write_text(json.dumps({"status": "pass", "scope": "sdram-only",
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "simulator_directory": str(tool_dir), "summaries": summaries, "sha256": hashes}, indent=2) + "\n",
        encoding="utf-8")
    print("SDRAM_ONLY_PASS: build/sdram_sim/results.json; earlier suites were not rerun.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (RuntimeError, OSError, ValueError) as exc:
        print(f"SDRAM_REGRESSION_FAILED: {exc}", file=sys.stderr)
        raise SystemExit(1)
