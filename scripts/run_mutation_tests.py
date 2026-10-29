"""Run native UVM against isolated RTL mutants; never program hardware.

The optimized p1_b4_s0 configuration is the campaign's explicit scope. Nominal
controls run before and after; existing source files are never overwritten.
"""
import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.mutation_catalog import MUTATIONS, Mutation
from scripts.run_uvm_tests import RTL_SOURCES, UVM_SOURCES

ADDITIONAL = ["tb/uvm/tma_mutation_pkg.sv", "scripts/mutation_catalog.py", "scripts/run_mutation_tests.py"]
UVM_FAILURE = re.compile(r"^#?\s*UVM_(ERROR|FATAL)\b[^\n]*?\[([^\]\n]+)\]\s*([^\r\n]+)", re.M)
# Stop from the module after the actual UVM checker reports an error. Questa
# Starter 2024.3 can SIGSEGV with -onfinish stop during an active sequence.
# Keep that vendor crash out of detection results; do not change checker actions
# or downgrade errors. Nominal runs still finish through normal UVM phases.
ERROR_STOP = """
    always @(negedge clk) begin : mutation_error_stop
        uvm_report_server server;
        server=uvm_report_server::get_server();
        if(server.get_severity_count(UVM_ERROR)>0) begin
            server.report_summarize();
            $display("TMA_MUTATION_STOP_AFTER_UVM_ERROR");
            $finish;
        end
    end
"""


def classify(transcript: str, mutation: Mutation, returncode: int) -> dict:
    """A tool error, arbitrary fatal or external timeout is never a detection."""
    if returncode not in (0, 1) or re.search(r"\*\* (?:Error|Fatal): (?!SDRAM_MODEL)", transcript) or any(s in transcript for s in (
            "Error loading design", "Unable to checkout", "Failure to checkout", "License checkout failed")):
        return {"outcome": "infrastructure_error", "diagnostic": "Simulator/elaboration/license error"}
    if "[TMA_UVM_PASS]" in transcript:
        return {"outcome": "survived", "diagnostic": "Mutated RTL completed the UVM suite"}
    failures = UVM_FAILURE.findall(transcript)
    if failures:
        severity, checker, message = failures[0]
        return {"outcome": "detected" if checker in mutation.checker_ids else "unexpected_failure",
                "checker": checker, "severity": severity, "diagnostic": message}
    if mutation.model_diagnostic:
        match = re.search(r"^#?\s*\*\* Fatal:\s*(" + re.escape(mutation.model_diagnostic) + r"[^\r\n]*)", transcript, re.M)
        if match:
            return {"outcome": "detected", "checker": "SDRAM_PIN_MODEL", "severity": "Fatal",
                    "diagnostic": match[1]}
    return {"outcome": "unexpected_failure", "diagnostic": f"No designated checker diagnosis (exit {returncode})"}


def nominal_result(transcript: str, returncode: int) -> dict:
    if returncode or UVM_FAILURE.search(transcript) or re.search(r"\*\* (?:Error|Fatal):", transcript):
        raise RuntimeError("Nominal UVM control failed")
    marker = re.search(r"\[TMA_UVM_PASS\] ([^\r\n]+)", transcript)
    if (not marker or "[TMA_MUTATION_PROBES_DONE]" not in transcript
            or any(not re.search(rf"UVM_{s}\s*:\s*0\b", transcript) for s in ("WARNING", "ERROR", "FATAL"))):
        raise RuntimeError("Nominal UVM control lacks clean reports or cache probes")
    values = {k: int(v) for k, v in (field.split("=", 1) for field in marker[1].split())}
    if values["descriptors"] != 34 or (values["pipelined"], values["burst_words"], values["swizzle"]) != (1, 4, 0):
        raise RuntimeError("Nominal configuration/descriptor identity mismatch")
    return values


def run_campaign(tool_dir: Path, selected: list[str] | None = None) -> dict:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output = ROOT / "build/mutation" / stamp
    output.mkdir(parents=True, exist_ok=False)
    pointer = ROOT / "build/mutation/current_results.json"
    pointer.unlink(missing_ok=True)  # A failed rerun must not advertise a stale pass.
    names = list(dict.fromkeys(RTL_SOURCES + ["tb/tma_sdram_model.sv"] + UVM_SOURCES + ADDITIONAL))
    hashes = {n: hashlib.sha256((ROOT / n).read_bytes()).hexdigest() for n in names}
    mutations = [m for m in MUTATIONS if not selected or m.name in selected]
    for mutation in mutations:
        mutation.apply((ROOT / mutation.source).read_bytes())
    top = (ROOT / "tb/uvm/tb_tma_uvm.sv").read_text()
    if top.count('run_test("tma_uvm_test");') != 1:
        raise RuntimeError("Cannot identify original UVM test entry point")
    top = top.replace("import tma_uvm_pkg::*;", "import tma_uvm_pkg::*;\n    import tma_mutation_pkg::*;")
    top = top.replace('run_test("tma_uvm_test");', 'run_test("tma_mutation_test");')
    if top.count("endmodule") != 1:
        raise RuntimeError("Cannot identify original UVM top module")
    top = top.replace("endmodule", ERROR_STOP + "endmodule")
    top_path = output / "tb_tma_mutation_top.sv"
    top_path.write_text(top, encoding="utf-8")
    suffix = ".exe" if sys.platform == "win32" else ""
    uvm_src = tool_dir.parent / "verilog_src/uvm-1.2/src"
    dpi = tool_dir.parent / "uvm-1.2/win64/uvm_dpi"
    if not (uvm_src / "uvm_pkg.sv").is_file() or not dpi.with_suffix(".dll").is_file():
        raise RuntimeError("Questa UVM 1.2 sources/DPI not found")

    def call(tool: str, args: list[str], log: Path, timeout: int = 300):
        with log.open("w", encoding="utf-8") as stream:
            try:
                proc = subprocess.run([str(tool_dir / (tool + suffix)), *args], cwd=output,
                                      stdout=stream, stderr=subprocess.STDOUT, timeout=timeout)
            except subprocess.TimeoutExpired as exc:
                raise RuntimeError(f"External tool timeout is not a detected mutant: {log}") from exc
        return proc.returncode, log.read_text(encoding="utf-8", errors="replace")

    version = subprocess.check_output([str(tool_dir / ("vsim" + suffix)), "-version"], text=True).strip()
    for library in ("work", "uvm12"):
        code, _ = call("vlib", [library], output / f"{library}_library.log")
        if code: raise RuntimeError("Could not create simulator library")
    code, _ = call("vlog", ["-sv", "-work", "uvm12", "+incdir+" + str(uvm_src), str(uvm_src / "uvm_pkg.sv")], output / "uvm_compile.log")
    if code: raise RuntimeError("Vendor UVM compilation failed")
    (output / "run.do").write_text("onerror {quit -code 1}\nrun -all\nquit -code 0\n", encoding="ascii")
    result = {"status": "running", "scope": "native UVM RTL mutation campaign; p1_b4_s0 only; no hardware access",
              "timestamp_utc": datetime.now(timezone.utc).isoformat(), "seed": 20261029,
              "configuration": {"pipelined": 1, "burst_words": 4, "swizzle": 0},
              "simulator": version, "uvm_version": "1.2", "random_cases": 0,
              "sv_constrained_randomization_executed": False, "sv_covergroups_executed": False,
              "sha256": hashes, "uvm_package_sha256": hashlib.sha256((uvm_src / "uvm_pkg.sv").read_bytes()).hexdigest(),
              "generated_top_sha256": hashlib.sha256(top_path.read_bytes()).hexdigest(),
              "controls": {}, "mutations": [], "source_files_unchanged": False}

    def save():
        (output / "results.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")

    def one(name: str, mutation: Mutation | None):
        case = output / name
        case.mkdir()
        started = time.monotonic()
        sources = [ROOT / n for n in RTL_SOURCES]
        if mutation:
            original = (ROOT / mutation.source).read_bytes()
            changed = case / Path(mutation.source).name
            changed.write_bytes(mutation.apply(original))
            sources[RTL_SOURCES.index(mutation.source)] = changed
        sources += [ROOT / "tb/tma_sdram_model.sv", ROOT / "tb/uvm/tma_uvm_if.sv",
                    ROOT / "tb/uvm/tma_uvm_pkg.sv", ROOT / "tb/uvm/tma_mutation_pkg.sv", top_path]
        compile_args = ["-sv", "-L", "uvm12", "+incdir+" + str(uvm_src), "+incdir+" + str(ROOT / "tb/uvm")]
        code, _ = call("vlog", compile_args + [str(p) for p in sources], case / "compile.log")
        if code:
            return {"name": name, "outcome": "compile_error", "diagnostic": "Mutant did not compile; not counted as detected"}
        args = ["-c", "-onfinish", "exit", "-L", "uvm12", "-sv_lib", str(dpi), "-sv_seed", "20261029",
                "-l", str(case / "simulation.log"), "work.tb_tma_uvm", "-gPIPELINED=1", "-gREAD_BURST_WORDS=4",
                "-gSWIZZLE=0", "+UVM_VERBOSITY=UVM_LOW", "+UVM_MAX_QUIT_COUNT=0,YES",
                "+TMA_STIMULUS_SEED=20261029", "+TMA_RANDOM_CASES=0", "-do", "do run.do"]
        code, transcript = call("vsim", args, case / "console.log")
        if mutation:
            verdict = {"name": name, **asdict(mutation), **mutation.identity(original),
                       **classify(transcript, mutation, code)}
        else:
            verdict = {"name": name, "outcome": "pass", "summary": nominal_result(transcript, code)}
        verdict.update(elapsed_seconds=round(time.monotonic() - started, 3), returncode=code)
        return verdict

    save()
    try:
        result["controls"]["before"] = one("nominal_before", None)
        if result["controls"]["before"]["outcome"] != "pass":
            raise RuntimeError("Nominal control could not compile")
        print("MUTATION_CONTROL_PASS before", flush=True)
        save()
        for mutation in mutations:
            record = one(mutation.name, mutation)
            result["mutations"].append(record)
            save()
            print(f"MUTATION_{record['outcome'].upper()} {mutation.name}: {record['diagnostic']}", flush=True)
            if record["outcome"] in ("compile_error", "infrastructure_error"):
                raise RuntimeError(f"Campaign stopped on tool failure: {mutation.name}")
        result["controls"]["after"] = one("nominal_after", None)
        if result["controls"]["after"]["outcome"] != "pass":
            raise RuntimeError("Final nominal control could not compile")
        print("MUTATION_CONTROL_PASS after", flush=True)
        result["source_files_unchanged"] = all(hashlib.sha256((ROOT / n).read_bytes()).hexdigest() == h for n, h in hashes.items())
        if not result["source_files_unchanged"]:
            raise RuntimeError("Canonical source files changed during campaign")
        result["detected"] = sum(m["outcome"] == "detected" for m in result["mutations"])
        result["total"] = len(mutations)
        result["status"] = "pass" if result["detected"] == result["total"] else "fail"
        result["completed_utc"] = datetime.now(timezone.utc).isoformat()
        save()
        pointer.write_text(json.dumps({"record": (output / "results.json").relative_to(ROOT).as_posix(),
                                       "status": result["status"]}, indent=2) + "\n")
        print(f"MUTATION_CAMPAIGN_{result['status'].upper()} {result['detected']}/{result['total']}: {output}", flush=True)
        return result
    except Exception as exc:
        result.update(status="error", diagnostic=str(exc))
        save()
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mutant", action="append", choices=[m.name for m in MUTATIONS])
    parser.add_argument("--list", action="store_true", help="List and validate anchors without invoking a simulator")
    args = parser.parse_args()
    if args.list:
        for mutation in MUTATIONS:
            mutation.apply((ROOT / mutation.source).read_bytes())
            print(f"{mutation.name}: {mutation.requirement}")
        return 0
    from scripts.run_tests import find_questa
    result = run_campaign(find_questa(), args.mutant)
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"MUTATION_CAMPAIGN_ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
