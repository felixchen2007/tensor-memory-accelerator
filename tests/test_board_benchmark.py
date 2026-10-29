import unittest
from model.board_benchmark import compare_runs


def records():
    runs = []
    for engine, cycles in (("serialized", 16000), ("pipelined", 13000)) * 2:
        runs.append({"source_sha256": {"rtl/core.sv": "same"}, "configuration": {"engine": engine},
                     "sof_sha256": engine, "resources": {"LEs": 2000}, "programming_succeeded": True,
                     "nominal_core_hz": 50_000_000, "status": {"format_version": 3, "engine": engine,
                     "status": "pass", "refresh_aligned": True, "operation": "transpose32",
                     "checked_words": 1024, "source_checked_words": 1024, "scratch_checked_words": 1024,
                     "completed_elements": 1024, "elapsed_cycles": cycles}})
    return runs


class BoardBenchmarkTests(unittest.TestCase):
    def test_three_profiles_compared_with_repeated_burst_image(self):
        runs = records()
        for _ in range(2):
            run = records()[1]
            run["configuration"]["read_burst_words"] = 4
            run["status"].update(format_version=4, read_burst_words=4, elapsed_cycles=6000)
            run["sof_sha256"] = "burst-image"
            runs.append(run)
        result = compare_runs(runs)
        self.assertAlmostEqual(result["burst_speedup_vs_serialized"], 16/6)
        self.assertAlmostEqual(result["burst_speedup_vs_pipelined"], 13/6)
        runs[-1]["status"]["read_burst_words"] = 1
        with self.assertRaises(ValueError): compare_runs(runs)

    def test_payload_latency_and_ratio(self):
        result = compare_runs(records())
        self.assertAlmostEqual(result["cycle_speedup"], 16 / 13)
        self.assertEqual(result["engines"]["serialized"]["tile_us_at_nominal_clock"], 320)
        self.assertEqual(result["engines"]["serialized"]["tile_payload_MB_s_at_nominal_clock"], 6.4)

    def test_wrong_image_or_legacy_identity_rejected(self):
        for key, value in (("engine", "pipelined"), ("format_version", 2), ("operation", "copy32")):
            runs = records(); runs[0]["status"][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError): compare_runs(runs)

    def test_mismatched_sources_or_repeat_images_rejected(self):
        for key, value in (("source_sha256", {"rtl/core.sv": "different"}), ("sof_sha256", "new-image")):
            runs = records(); runs[-1][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError): compare_runs(runs)

    def test_failure_unaligned_incomplete_or_zero_counter_rejected(self):
        for key, value in (("status", "fail"), ("refresh_aligned", False), ("checked_words", 0),
                           ("elapsed_cycles", 0), ("completed_elements", 1000)):
            runs = records(); runs[0]["status"][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError): compare_runs(runs)

    def test_missing_repetition_or_unstable_counters_rejected(self):
        with self.assertRaises(ValueError): compare_runs(records()[:2])
        runs = records(); runs[-1]["status"]["elapsed_cycles"] += 1
        with self.assertRaises(ValueError): compare_runs(runs)

    def test_programming_failure_or_changed_clock_rejected(self):
        for key, value in (("programming_succeeded", False), ("nominal_core_hz", 25_000_000)):
            runs = records(); runs[0][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError): compare_runs(runs)
