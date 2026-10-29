"""Validate published engineering evidence and links using only Python stdlib.

This reads recorded results. It does not run RTL, fit an FPGA or access hardware.
"""
import hashlib
import json
from pathlib import Path
import re
import sys
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from model.board_benchmark import compare_runs
from model.board_status import decode_samples, decode_read_trace


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check_source_hashes(hashes: dict) -> None:
    for name, expected in hashes.items():
        path = ROOT / name
        require(path.is_file() and digest(path) == expected,
                f"Tested source differs: {name}; retain historical evidence and record a new run")


def check_exports() -> int:
    entries = read_json(ROOT / "evidence/manifest.json")["files"]
    require(len({entry["path"] for entry in entries}) == len(entries), "Duplicate evidence paths")
    for entry in entries:
        path = (ROOT / entry["path"]).resolve()
        require(path.is_relative_to((ROOT / "evidence").resolve()), "Evidence path escaped its directory")
        require(path.is_file() and digest(path) == entry["published_sha256"],
                f"Published evidence changed: {entry['path']}")
    return len(entries)


def check_hardware() -> dict:
    folder = ROOT / "evidence/hardware/2026-10-29"
    runs = []
    for directory in sorted(p for p in folder.iterdir() if p.is_dir()):
        run = read_json(directory / "run.json")
        probe = read_json(directory / "probe.json")
        build = read_json(directory / "board_results.json")
        check_source_hashes(run["source_sha256"])
        check_source_hashes(build["sha256"])
        decoded = decode_samples(probe["raw_snapshots"])
        require(decoded == probe["status"] == run["status"],
                f"Hardware packet/result mismatch: {directory.name}")
        raw_log = (directory / "probe.log").read_text(encoding="utf-8")
        frames = re.findall(r"^TMA_PROBE_HEX=([0-9a-fA-F]+)\s*$", raw_log, re.M)
        require(frames == probe["raw_snapshots"], f"Raw packet/JSON mismatch: {directory.name}")
        traces = re.findall(r"^TMA_READ_TRACE_HEX=([0-9a-fA-F]+)\s*$", raw_log, re.M)
        require(len(traces) == 3 and all(decode_read_trace(frame) == probe["read_trace"] for frame in traces),
                f"Raw trace/JSON mismatch: {directory.name}")
        require(build["status"] == "pass" and build["sof_sha256"] == run["sof_sha256"],
                f"Wrong fitted image: {directory.name}")
        require(build["configuration"] == run["configuration"], "Fitted configuration mismatch")
        require(all(item["slack_ns"] >= 0 for item in build["timing"]), "Negative recorded timing")
        require(len(build["pins"]) == 50, "Expected 50 fitted user pins")
        require(any("15064" in warning["message"] for warning in build["warnings"]),
                "The documented clock-routing warning must remain in the record")
        runs.append(run)
    require(len(runs) == 6, "Require all six physical configurations")
    result = compare_runs(runs)
    saved = read_json(folder / "results.json")
    for key in ("engines", "cycle_speedup", "burst_speedup_vs_serialized", "burst_speedup_vs_pipelined"):
        require(result[key] == saved[key], f"Hardware comparison changed: {key}")
    return result


def check_uvm() -> int:
    folder = ROOT / "evidence/uvm/2026-10-29"
    result = read_json(folder / "results.json")
    require(result["status"] == "pass" and result["uvm_version"] == "1.2", "Missing native UVM pass")
    require(result["mode"] == "starter-seeded-procedural-stimulus", "Unexpected recorded UVM mode")
    require(result["sv_constrained_randomization_executed"] is False
            and result["sv_covergroups_executed"] is False, "Do not claim unexecuted licensed features")
    check_source_hashes(result["sha256"])
    expected = {f"p{p}_b{b}_s{s}" for p in (0, 1) for b in (1, 4) for s in (0, 1)}
    profiles = result["profiles"]
    require(set(profiles) == expected | {"data_fault_control"}, "Incomplete UVM matrix")
    for name in sorted(expected):
        report = (folder / f"{name}.log").read_text(encoding="utf-8")
        for severity in ("WARNING", "ERROR", "FATAL"):
            require(re.search(rf"UVM_{severity}\s*:\s*0\b", report), f"Nonzero/missing UVM severity: {name}")
        match = re.search(r"\[TMA_UVM_PASS\] ([^\r\n]+)", report)
        require(match is not None, f"No UVM pass marker: {name}")
        actual = {key: int(value) for key, value in (field.split("=", 1) for field in match[1].split())}
        require(actual == profiles[name], f"UVM summary disagrees with transcript: {name}")
        require(actual["descriptors"] == 46 and actual["bank_family_bins"] == 20, "UVM scenario count changed")
        require("bank_family=20/20 offsets=1111 statuses=1111 sizes=11111 stalls=111 busy=1 long_hold=1" in report,
                f"Required UVM scenarios missing: {name}")
    fault = (folder / "data_fault_control.log").read_text(encoding="utf-8")
    require("[TMA_READ_DATA] DMA read" in fault and "[TMA_UVM_PASS]" not in fault
            and re.search(r"UVM_ERROR\s*:\s*1\b", fault), "UVM data-fault checker did not detect corruption")
    parent = read_json(ROOT / "evidence/simulation/2026-10-29/results.json")
    require(parent["status"] == "pass" and parent["summaries"]["uvm"] == result,
            "Focused simulation result and UVM result disagree")
    return sum(profiles[name]["descriptors"] for name in expected)


def check_links() -> int:
    paths = [ROOT / "README.md", ROOT / "THIRD_PARTY.md"]
    paths += list((ROOT / "docs").rglob("*.md")) + list((ROOT / "evidence").rglob("*.md"))
    checked = 0
    for path in paths:
        text = path.read_text(encoding="utf-8")
        text = re.sub(r"```.*?```", "", text, flags=re.S)
        for match in re.finditer(r"!?\[[^\]\n]*\]\((?:<([^>]+)>|([^\s)]+))\)", text):
            target = match[1] or match[2]
            url = urlsplit(target)
            if url.scheme or url.netloc or not url.path:
                continue
            local = (path.parent / unquote(url.path)).resolve()
            require(local.is_relative_to(ROOT), f"Link escapes repository: {path.name}: {target}")
            require(local.exists(), f"Broken link: {path.relative_to(ROOT)} -> {target}")
            checked += 1
    return checked


def main() -> int:
    exports = check_exports()
    hardware = check_hardware()
    descriptors = check_uvm()
    links = check_links()
    print(f"PORTFOLIO_CHECK_PASS exports={exports} physical_runs=6 uvm_descriptors={descriptors} "
          f"local_links={links} measured_speedup={hardware['burst_speedup_vs_serialized']:.5f}x")
    print("Scope: recorded evidence and source identity; no fresh RTL simulation or hardware access.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, KeyError, ValueError) as exc:
        print(f"PORTFOLIO_CHECK_FAILED: {exc}", file=sys.stderr)
        raise SystemExit(1)
