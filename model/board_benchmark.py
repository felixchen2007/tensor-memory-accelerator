"""Validate paired board evidence and compute tile latency, not sustained bandwidth."""


def compare_runs(runs: list[dict]) -> dict:
    has_burst = any(r["configuration"].get("read_burst_words", 1) == 4 for r in runs)
    if len(runs) != (6 if has_burst else 4):
        raise ValueError("Require two fresh configurations of each engine")
    sources = runs[0]["source_sha256"]
    if not sources or any(r["source_sha256"] != sources for r in runs):
        raise ValueError("Benchmark images do not share the same sources and constraints")
    groups = {engine: [] for engine in ("serialized", "pipelined")}
    if has_burst:
        groups["pipelined_burst4"] = []
    for run in runs:
        status, engine = run["status"], run["configuration"]["engine"]
        burst_words = run["configuration"].get("read_burst_words", 1)
        group_name = engine + ("_burst4" if burst_words == 4 else "")
        if (group_name not in groups or status.get("engine") != engine
                or status.get("format_version") != (4 if burst_words == 4 else 3)
                or status.get("read_burst_words", 1) != burst_words):
            raise ValueError("Programmed engine identity disagrees with the hardware packet")
        if (not run.get("programming_succeeded") or status.get("status") != "pass"
                or not status.get("refresh_aligned") or status.get("operation") != "transpose32"
                or run.get("nominal_core_hz") != 50_000_000):
            raise ValueError("Benchmark requires passing, refresh-aligned 50 MHz transpose runs")
        if any(status.get(k) != 1024 for k in ("checked_words", "source_checked_words",
                                               "scratch_checked_words", "completed_elements")):
            raise ValueError("Benchmark lacks complete data verification")
        if status.get("elapsed_cycles", 0) <= 0:
            raise ValueError("Invalid onboard cycle counter")
        groups[group_name].append(run)
    result = {}
    for engine, group in groups.items():
        if len(group) != 2 or len({r["sof_sha256"] for r in group}) != 1:
            raise ValueError("Each engine must repeat the same image twice")
        cycles = {r["status"]["elapsed_cycles"] for r in group}
        if len(cycles) != 1:
            raise ValueError("Repeated onboard counters differ; investigate before comparing")
        count = cycles.pop()
        result[engine] = {"cycles": count, "tile_us_at_nominal_clock": count / 50,
                          "tile_payload_MB_s_at_nominal_clock": 2048 * 50 / count,
                          "sof_sha256": group[0]["sof_sha256"],
                          "resources": group[0]["resources"], "repetitions": 2}
    ratio = result["serialized"]["cycles"] / result["pipelined"]["cycles"]
    summary = {"status": "pass", "scope": "paired onboard tile counters; not sustained bandwidth",
            "operation": "32x32 sixteen-bit SDRAM-to-scratchpad transpose", "payload_bytes": 2048,
            "nominal_core_hz": 50_000_000, "refresh_phase": "two core edges after refresh launch",
            "engines": result, "cycle_speedup": ratio, "latency_reduction_percent": (1 - 1 / ratio) * 100}
    if has_burst:
        summary["burst_speedup_vs_serialized"] = result["serialized"]["cycles"] / result["pipelined_burst4"]["cycles"]
        summary["burst_speedup_vs_pipelined"] = result["pipelined"]["cycles"] / result["pipelined_burst4"]["cycles"]
    return summary
