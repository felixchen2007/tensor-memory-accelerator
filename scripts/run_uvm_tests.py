"""Run native UVM 1.2 against the SDRAM tensor system; never access hardware."""
import argparse
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
UVM_SOURCES = ["tb/uvm/tma_uvm_if.sv", "tb/uvm/tma_uvm_pkg.sv", "tb/uvm/tma_uvm_agent.svh",
    "tb/uvm/tma_uvm_scoreboard.svh", "tb/uvm/tma_uvm_coverage.svh", "tb/uvm/tma_uvm_sequences.svh",
    "tb/uvm/tb_tma_uvm.sv", "scripts/run_uvm_tests.py"]
RTL_SOURCES = [f"rtl/{name}.sv" for name in ("tma_addr_gen", "tma_copy_engine", "tma_copy_engine_pipelined",
    "tma_copy_engine_select", "tma_ram_bank", "tma_scratchpad", "tma_scratchpad_endpoint",
    "tma_sdram_controller", "tma_sdram_copy_system")]
PROFILES = {f"p{p}_b{b}_s{s}": (p,b,s) for p in (0,1) for b in (1,4) for s in (0,1)}


def run_uvm_suite(tool_dir: Path, output: Path, full: bool = False, profiles=None,
                  seed: int = 20261029, random_cases: int = 12, compile_only: bool = False) -> dict:
    output.mkdir(parents=True, exist_ok=True)
    result_path = output / "results.json"
    result_path.unlink(missing_ok=True)
    names = RTL_SOURCES + ["tb/tma_sdram_model.sv"] + UVM_SOURCES
    hashes = {name: hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in names}
    uvm_src = tool_dir.parent / "verilog_src/uvm-1.2/src"
    dpi = tool_dir.parent / "uvm-1.2/win64/uvm_dpi"
    if not (uvm_src/"uvm_pkg.sv").is_file() or not dpi.with_suffix(".dll").is_file():
        raise RuntimeError("Installed UVM 1.2 sources/DPI were not found beside Questa")
    suffix = ".exe" if os.name == "nt" else ""

    def call(tool, args, log_name):
        run = subprocess.run([str(tool_dir/f"{tool}{suffix}"), *args], cwd=output,
            text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, errors="replace")
        (output/log_name).write_text(run.stdout, encoding="utf-8")
        return run

    for library in ("work", "uvm12"):
        if not (output/library).exists():
            r = call("vlib", [library], f"{library}_library.log")
            if r.returncode: raise RuntimeError(r.stdout[-4000:])
    vendor_hash = hashlib.sha256((uvm_src/"uvm_pkg.sv").read_bytes()).hexdigest()
    cache = output / "uvm_library_hash.txt"
    if not cache.exists() or cache.read_text().strip() != vendor_hash:
        r = call("vlog", ["-sv", "-work", "uvm12", "+incdir+"+str(uvm_src), str(uvm_src/"uvm_pkg.sv")], "uvm_compile.log")
        if r.returncode: raise RuntimeError(r.stdout[-6000:])
        cache.write_text(vendor_hash)
    compile_args = ["-sv", "-L", "uvm12", "+incdir+"+str(uvm_src), "+incdir+"+str(ROOT/"tb/uvm")]
    if full: compile_args.append("+define+TMA_UVM_FULL")
    compile_args += [str(ROOT/n) for n in RTL_SOURCES + ["tb/tma_sdram_model.sv",
        "tb/uvm/tma_uvm_if.sv", "tb/uvm/tma_uvm_pkg.sv", "tb/uvm/tb_tma_uvm.sv"]]
    r = call("vlog", compile_args, "project_compile.log")
    if r.returncode: raise RuntimeError(r.stdout[-8000:])
    if compile_only:
        print("UVM_COMPILE_ONLY: no simulation or coverage claim", flush=True)
        return {"status": "compiled-only"}
    (output/"run.do").write_text("onerror {quit -code 1}\nrun -all\nquit -code 0\n", encoding="ascii")
    summaries = {}
    selected = list(profiles) if profiles else list(PROFILES)
    for profile in selected + ["data_fault_control"]:
        negative = profile == "data_fault_control"
        p,b,s = (1,4,0) if negative else PROFILES[profile]
        args = ["-c", "-onfinish", "stop", "-L", "uvm12", "-sv_lib", str(dpi), "-sv_seed", str(seed),
                "-l", f"{profile}_simulation.log", "work.tb_tma_uvm", f"-gPIPELINED={p}",
                f"-gREAD_BURST_WORDS={b}", f"-gSWIZZLE={s}", "+UVM_VERBOSITY=UVM_LOW",
                "+UVM_MAX_QUIT_COUNT=1,YES", f"+TMA_STIMULUS_SEED={seed}",
                f"+TMA_RANDOM_CASES={random_cases}", "-do", "do run.do"]
        if full: args.insert(1, "-coverage")
        if negative: args += ["-gREAD_XOR_MASK=1", "+TMA_SKIP_SOURCE_READ=1"]
        run = call("vsim", args, f"{profile}_console.log")
        transcript = run.stdout
        if "Unable to checkout verification license" in transcript:
            raise RuntimeError(f"Simulator license denies full SV verification; see {output/(profile+'_console.log')}")
        if negative:
            if "[TMA_READ_DATA]" not in transcript or "UVM_ERROR" not in transcript or "[TMA_UVM_PASS]" in transcript:
                raise RuntimeError(f"UVM scoreboard did not catch injected data corruption: {transcript[-6000:]}")
            summaries[profile] = {"expected_scoreboard_error_detected": True, "id": "TMA_READ_DATA"}
            print("UVM_EXPECTED_FAILURE_DETECTED: data_fault_control TMA_READ_DATA", flush=True)
            continue
        match = re.search(r"\[TMA_UVM_PASS\] ([^\r\n]+)", transcript)
        if (run.returncode or not match or "** Fatal:" in transcript or "** Error:" in transcript
                or not re.search(r"UVM_ERROR\s*:\s*0", transcript) or not re.search(r"UVM_FATAL\s*:\s*0", transcript)):
            raise RuntimeError(f"UVM profile {profile} failed: {transcript[-8000:]}")
        values = {k: int(v) for k,v in (field.split("=",1) for field in match.group(1).split())}
        if (values["descriptors"] != 34 + random_cases or values["bank_family_bins"] != 20
                or (values["pipelined"],values["burst_words"],values["swizzle"]) != (p,b,s)):
            raise RuntimeError("UVM coverage/identity does not match the requested profile")
        summaries[profile] = values
        print(f"TMA_UVM_PROFILE_PASS {profile} "+match.group(1), flush=True)
    if any(hashlib.sha256((ROOT/n).read_bytes()).hexdigest()!=h for n,h in hashes.items()):
        raise RuntimeError("Sources changed during UVM verification")
    result = {"status": "pass", "scope": "native UVM simulation; no hardware access", "uvm_version": "1.2",
        "mode": "licensed-constrained-random-and-covergroups" if full else "starter-seeded-procedural-stimulus",
        "sv_constrained_randomization_executed": full, "sv_covergroups_executed": full,
        "timestamp_utc": datetime.now(timezone.utc).isoformat(), "seed": seed, "random_cases": random_cases,
        "profiles": summaries, "sha256": hashes, "uvm_package_sha256": vendor_hash}
    result_path.write_text(json.dumps(result, indent=2)+"\n", encoding="utf-8")
    print("UVM_REGRESSION_PASS: "+str(result_path), flush=True)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--full", action="store_true", help="Requires licensed SV randomize and covergroups")
    parser.add_argument("--profile", action="append", choices=PROFILES)
    parser.add_argument("--seed", type=int, default=20261029)
    parser.add_argument("--random-cases", type=int, default=12)
    parser.add_argument("--compile-only", action="store_true")
    args = parser.parse_args()
    if args.random_cases<0 or args.random_cases>1000: parser.error("random cases must be 0..1000")
    from scripts.run_tests import find_questa
    output = ROOT / "build/uvm" / ("full" if args.full else "starter")
    run_uvm_suite(find_questa(), output, args.full, args.profile, args.seed, args.random_cases, args.compile_only)
    return 0


if __name__ == "__main__":
    try: raise SystemExit(main())
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"UVM_REGRESSION_FAILED: {exc}", file=sys.stderr)
        raise SystemExit(1)
