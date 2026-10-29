"""Validate published engineering evidence and links using only Python stdlib.

This reads recorded results. It does not run RTL, fit an FPGA or access hardware.
"""
import hashlib
import json
from pathlib import Path
import re
import sys
from dataclasses import asdict
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from model.board_benchmark import compare_runs
from model.board_status import decode_samples, decode_read_trace
from scripts.mutation_catalog import MUTATIONS
from scripts.run_mutation_tests import ADDITIONAL, classify, nominal_result
from scripts.run_uvm_tests import RTL_SOURCES, UVM_SOURCES


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


def check_mutations() -> int:
    folder = ROOT / "evidence/mutation/2026-10-29"
    result = read_json(folder / "results.json")
    require(result["status"] == "pass" and result["source_files_unchanged"] is True,
            "Mutation campaign did not pass with unchanged sources")
    require(result["configuration"] == {"pipelined": 1, "burst_words": 4, "swizzle": 0}
            and result["seed"] == 20261029 and result["random_cases"] == 0,
            "Unexpected mutation campaign scope")
    require(result["uvm_version"] == "1.2" and result["sv_constrained_randomization_executed"] is False
            and result["sv_covergroups_executed"] is False, "Unexpected mutation UVM mode")
    expected_sources = set(RTL_SOURCES + UVM_SOURCES + ADDITIONAL + ["tb/tma_sdram_model.sv"])
    require(set(result["sha256"]) == expected_sources, "Mutation campaign source list is incomplete")
    check_source_hashes(result["sha256"])
    require(digest(folder / "tb_tma_mutation_top.sv") == result["generated_top_sha256"],
            "Generated mutation top differs from the executed top")
    for side in ("before", "after"):
        control = result["controls"][side]
        report = (folder / f"nominal_{side}.log").read_text(encoding="utf-8")
        require(control["outcome"] == "pass" and nominal_result(report, control["returncode"]) == control["summary"],
                f"Mutation nominal {side} control mismatch")
    records = result["mutations"]
    require(len(records) == len(MUTATIONS) and {r["name"] for r in records} == {m.name for m in MUTATIONS},
            "Mutation campaign must retain the complete catalog")
    for mutation in MUTATIONS:
        record = next(r for r in records if r["name"] == mutation.name)
        for key, value in asdict(mutation).items():
            require(record[key] == (list(value) if isinstance(value, tuple) else value),
                    f"Mutation patch or expected diagnosis changed: {mutation.name}/{key}")
        for key, value in mutation.identity((ROOT / mutation.source).read_bytes()).items():
            require(record[key] == value, f"Mutated source identity mismatch: {mutation.name}")
        report = (folder / f"{mutation.name}.log").read_text(encoding="utf-8")
        verdict = classify(report, mutation, record["returncode"])
        require(verdict["outcome"] == "detected" and all(record[k] == v for k, v in verdict.items()),
                f"Mutation diagnosis disagrees with transcript: {mutation.name}")
    for name in ["nominal_before", "nominal_after"] + [m.name for m in MUTATIONS]:
        report = (folder / f"{name}.compile.log").read_text(encoding="utf-8")
        require(re.search(r"Errors:\s*0,\s*Warnings:\s*0", report), f"Mutation compilation failed: {name}")
    require(result["detected"] == result["total"] == len(MUTATIONS), "Mutation count mismatch")
    matrix_folder = folder / "nominal_matrix"
    matrix = read_json(matrix_folder / "results.json")
    require(matrix["status"] == "pass" and matrix["timestamp_utc"] > result["completed_utc"],
            "Expected a fresh nominal UVM matrix after mutation testing")
    check_source_hashes(matrix["sha256"])
    expected_profiles = {f"p{p}_b{b}_s{s}" for p in (0, 1) for b in (1, 4) for s in (0, 1)}
    require(set(matrix["profiles"]) == expected_profiles | {"data_fault_control"}, "Missing follow-up UVM profiles")
    for name in expected_profiles:
        report = (matrix_folder / f"{name}.log").read_text(encoding="utf-8")
        require("** Error:" not in report and "** Fatal:" not in report, f"UVM matrix tool failure: {name}")
        marker = re.search(r"\[TMA_UVM_PASS\] ([^\r\n]+)", report)
        require(marker is not None, f"Missing follow-up UVM pass marker: {name}")
        values = {k: int(v) for k, v in (field.split("=", 1) for field in marker[1].split())}
        require(values == matrix["profiles"][name] and values["descriptors"] == 46,
                f"Follow-up UVM summary mismatch: {name}")
        for severity in ("WARNING", "ERROR", "FATAL"):
            require(re.search(rf"UVM_{severity}\s*:\s*0\b", report), f"Follow-up UVM severity: {name}")
    report = (matrix_folder / "data_fault_control.log").read_text(encoding="utf-8")
    require("[TMA_READ_DATA]" in report and "[TMA_UVM_PASS]" not in report
            and "** Fatal:" not in report and "** Error:" not in report
            and re.search(r"UVM_ERROR\s*:\s*1\b", report), "Follow-up data fault was not caught cleanly")
    return len(records)


def main() -> int:
    exports = check_exports()
    hardware = check_hardware()
    descriptors = check_uvm()
    mutants = check_mutations()
    from scripts.check_cpp_evidence import validate as check_cpp
    cpp = check_cpp()
    links = check_links()
    print(f"PORTFOLIO_CHECK_PASS exports={exports} physical_runs=6 uvm_descriptors={descriptors} "
          f"mutants_detected={mutants} cpp_matrix_descriptors={cpp['matrix_descriptors']} "
          f"local_links={links} measured_speedup={hardware['burst_speedup_vs_serialized']:.5f}x")
    print("Scope: recorded evidence and source identity; no fresh RTL simulation or hardware access.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, KeyError, ValueError, RuntimeError) as exc:
        print(f"PORTFOLIO_CHECK_FAILED: {exc}", file=sys.stderr)
        raise SystemExit(1)
