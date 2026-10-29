"""Decode a saved probe transcript; hardware reads require explicit --hardware."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from model.board_status import decode_samples, decode_read_trace


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--transcript", type=Path, help="Decode a saved readout without touching hardware")
    mode.add_argument("--hardware", action="store_true", help="Read an already-programmed board; never reprogram it")
    args = parser.parse_args()
    if args.hardware:
        candidates = []
        if os.environ.get("QUARTUS_BIN"):
            candidates.append(Path(os.environ["QUARTUS_BIN"]))
        located = shutil.which("quartus_stp")
        if located:
            candidates.append(Path(located).parent)
        for root in (Path("C:/altera_lite"), Path("C:/intelFPGA_lite")):
            if root.is_dir():
                candidates.extend(sorted(root.glob("*/quartus/bin64"), reverse=True))
        suffix = ".exe" if os.name == "nt" else ""
        executable = next((p / f"quartus_stp{suffix}" for p in candidates if (p / f"quartus_stp{suffix}").is_file()), None)
        if executable is None:
            raise RuntimeError("quartus_stp not found; set QUARTUS_BIN")
        run = subprocess.run([str(executable), "-t", str(ROOT / "quartus/read_board_probe.tcl")],
                             cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        folder = ROOT / "build/hardware"
        folder.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        log = folder / f"{stamp}_probe.log"
        log.write_text(run.stdout, encoding="utf-8")
        if run.returncode:
            raise RuntimeError(f"Probe read failed; transcript: {log}")
        transcript = run.stdout
    else:
        log = args.transcript.resolve()
        transcript = log.read_text(encoding="utf-8")
    snapshots = re.findall(r"^TMA_PROBE_HEX=((?:0[xX])?[0-9a-fA-F]+)\s*$", transcript, re.MULTILINE)
    status = decode_samples(snapshots)
    result = {"scope": "hardware-probe-read" if args.hardware else "offline-probe-decoding",
              "timestamp_utc": datetime.now(timezone.utc).isoformat(), "status": status,
              "raw_snapshots": snapshots, "transcript": str(log),
              "transcript_sha256": hashlib.sha256(log.read_bytes()).hexdigest()}
    traces = re.findall(r"^TMA_READ_TRACE_HEX=((?:0[xX])?[0-9a-fA-F]+)\s*$", transcript, re.MULTILINE)
    if traces:
        decoded = [decode_read_trace(frame) for frame in traces]
        if len(decoded) != 3 or any(item != decoded[0] for item in decoded[1:]):
            raise ValueError("Read trace did not remain stable across three samples")
        result["read_trace"] = decoded[0]
    if args.hardware:
        log.with_suffix(".json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"PROBE_READ_FAILED: {exc}", file=sys.stderr)
        raise SystemExit(1)
