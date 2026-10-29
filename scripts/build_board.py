"""Compile the DE10-Lite image and reject failed timing; never program hardware."""
from datetime import datetime, timezone
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def validate_timing(summary: str, sta: str) -> tuple[list[dict], list[str]]:
    timing = [{"type": name.strip(), "slack_ns": float(slack)} for name, slack in
              re.findall(r"Type\s*:\s*([^\r\n]+)\s+Slack\s*:\s*([-\d.]+)", summary)]
    if len(timing) < 18 or any(item["slack_ns"] < 0 for item in timing):
        raise RuntimeError("Fitted timing failed or expected corner reports missing")
    # Quartus 24.1 emits two exceptions for dynamic PLL phase-control registers
    # even when those ports are PORT_UNUSED and the registers have no fanout.
    # Match only each known empty vendor filter and its immediately following
    # exception warning. Keep them in the evidence; never waive user SDC warnings.
    reviewed = []
    allowed_filter = False
    for line in sta.splitlines():
        if not re.match(r"\s*(?:Critical )?Warning \(", line):
            continue
        empty_filter = re.match(r"Warning \(332174\): Ignored filter at qsta_default_script\.tcl\(\d+\): "
                                r"\*(phasedone_state|internal_phasestep)\* could not be matched", line)
        empty_exception = re.match(r"Warning \(332049\): Ignored set_false_path at qsta_default_script\.tcl\(\d+\): "
                                   r"Argument <to> is not an object ID", line)
        if empty_filter:
            allowed_filter = True
            reviewed.append(line)
        elif empty_exception and allowed_filter:
            allowed_filter = False
            reviewed.append(line)
        else:
            raise RuntimeError("Timing report has an unreviewed warning: " + line)
    for kind in ("setup", "hold"):
        if f"Design is fully constrained for {kind} requirements" not in sta:
            raise RuntimeError(f"Unconstrained {kind} paths remain")
    return timing, reviewed


def validate_pins(report: str) -> list[dict]:
    user_pins = []
    dedicated_jtag = {"altera_reserved_tck": "G2", "altera_reserved_tms": "H2",
                      "altera_reserved_tdi": "L4", "altera_reserved_tdo": "M5"}
    for line in report.splitlines():
        columns = [c.strip() for c in line.split(":")]
        # Quartus also reports fixed configuration/JTAG pins as input/output.
        # Their ~ALTERA_* names are not top-level user ports and are reserved.
        if len(columns) != 7 or columns[0].startswith("~ALTERA_"):
            continue
        if columns[0] in dedicated_jtag:
            if columns[1] != dedicated_jtag[columns[0]]:
                raise RuntimeError("Unexpected dedicated JTAG pin location")
            continue
        if columns[2] in ("input", "output", "bidir"):
            if columns[6] != "Y" or columns[3] != "3.3-V LVTTL":
                raise RuntimeError(f"Unassigned or wrong-standard board pin: {columns[0]}")
            user_pins.append({"signal": columns[0], "pin": columns[1], "direction": columns[2]})
    if len(user_pins) != 50 or len({p["pin"] for p in user_pins}) != 50:
        raise RuntimeError("Unexpected board pin count or aliases")
    return user_pins


def find_quartus_bin() -> Path:
    candidates = []
    if os.environ.get("QUARTUS_BIN"):
        candidates.append(Path(os.environ["QUARTUS_BIN"]))
    found = shutil.which("quartus_sh")
    if found:
        candidates.append(Path(found).parent)
    for root in (Path("C:/altera_lite"), Path("C:/intelFPGA_lite")):
        if root.is_dir():
            candidates.extend(sorted(root.glob("*/quartus/bin64"), reverse=True))
    suffix = ".exe" if os.name == "nt" else ""
    tool_dir = next((p for p in candidates if (p / f"quartus_sh{suffix}").is_file()), None)
    if tool_dir is None:
        raise RuntimeError("Quartus not found; set QUARTUS_BIN")
    return tool_dir


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine", choices=("serialized", "pipelined"), default="pipelined")
    parser.add_argument("--read-burst", type=int, choices=(1, 4), default=1)
    args = parser.parse_args()
    pipeline = int(args.engine == "pipelined")
    tool_dir = find_quartus_bin()
    suffix = ".exe" if os.name == "nt" else ""
    source_paths = sorted((ROOT / "rtl").glob("*.sv")) + [
        ROOT / "quartus" / name for name in ("build_board.tcl", "report_board.tcl",
                                              "de10_lite.sdc", "de10_lite_pins.tcl")]
    source_paths.append(Path(__file__).resolve())
    hashes = {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in source_paths}
    directory = ("de10_lite" if pipeline else "de10_lite_serialized") + ("_burst4" if args.read_burst == 4 else "")
    build = ROOT / "build" / "quartus" / directory
    build.mkdir(parents=True, exist_ok=True)
    result_path = build / "board_results.json"
    result_path.unlink(missing_ok=True)
    for tool, script, log in [("quartus_sh", "build_board.tcl", "board_compile.log"),
                               ("quartus_sta", "report_board.tcl", "board_timing.log")]:
        with (build / log).open("w", encoding="utf-8") as stream:
            result = subprocess.run([str(tool_dir / f"{tool}{suffix}"), "-t", str(ROOT / "quartus" / script),
                                     str(pipeline), str(args.read_burst)],
                cwd=ROOT, text=True, stdout=stream, stderr=subprocess.STDOUT)
        if result.returncode:
            raise RuntimeError(f"{tool} failed; inspect {build / log}")
    reports = build / "output_files"
    summary = (reports / "tma_de10_lite.sta.summary").read_text()
    sta = (reports / "tma_de10_lite.sta.rpt").read_text()
    timing, reviewed = validate_timing(summary, sta)
    fitter = (reports / "tma_de10_lite.fit.summary").read_text()
    if "Fitter Status : Successful" not in fitter:
        raise RuntimeError("Fitter did not succeed")
    resources = {}
    for key in ("Total logic elements", "Total registers", "Total memory bits", "Total PLLs"):
        match = re.search(re.escape(key) + r"\s*:\s*([\d,]+)", fitter)
        if not match:
            raise RuntimeError(f"Missing fitted resource metric: {key}")
        resources[key] = int(match.group(1).replace(",", ""))
    # Check every fitted user pin is fixed by a user assignment; no automatic
    # placement is accepted for this board image.
    pins = (reports / "tma_de10_lite.pin").read_text()
    user_pins = validate_pins(pins)
    if any(hashlib.sha256((ROOT / name).read_bytes()).hexdigest() != expected for name, expected in hashes.items()):
        raise RuntimeError("Sources changed during compilation")
    sof = reports / "tma_de10_lite.sof"
    if not sof.is_file():
        raise RuntimeError("No volatile programming image produced")
    warnings = []
    for report in reports.glob("*.rpt"):
        warnings += [{"report": report.name, "message": m.strip()}
                     for m in report.read_text(errors="replace").splitlines()
                     if re.match(r"\s*(?:Critical )?Warning \(", m)]
    result_path.write_text(json.dumps({"status": "pass", "scope": "fitted-board-build",
        "configuration": {"engine": args.engine, "operation": "transpose32", "refresh_aligned": True,
                          "read_burst_words": args.read_burst},
        "timestamp_utc": datetime.now(timezone.utc).isoformat(), "board_tested": False,
        "external_delay_assumptions": "quartus/de10_lite.sdc: PCB min0.1/max0.5ns per clock/data leg",
        "resources": resources, "timing": timing, "pins": user_pins,
        "warnings": warnings, "reviewed_empty_vendor_pll_exceptions": reviewed,
        "sha256": hashes, "sof_sha256": hashlib.sha256(sof.read_bytes()).hexdigest()},
        indent=2) + "\n", encoding="utf-8")
    print(f"FITTED_BOARD_BUILD_PASS: {result_path.relative_to(ROOT).as_posix()}")
    print(json.dumps(resources))
    print(f"Worst setup: {min(t['slack_ns'] for t in timing if ' Setup ' in t['type']):.3f} ns; "
          f"worst hold: {min(t['slack_ns'] for t in timing if ' Hold ' in t['type']):.3f} ns")
    print("Physical-board self-test has not been run.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"BOARD_BUILD_FAILED: {exc}", file=sys.stderr)
        raise SystemExit(1)
