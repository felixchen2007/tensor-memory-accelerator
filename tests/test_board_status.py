import unittest
from model.board_status import decode_snapshot, decode_samples, decode_read_trace


def packet(**changes):
    # Explicit bit packing is also checked against RTL-produced frames by the
    # simulator runner, so these software fixtures are not the only format test.
    fields = {"flags": 0xF3, "stage": 13, "reason": 0, "checked": 1024,
              "source": 1024, "scratch": 1024, "word": 0, "expected": 0,
              "observed": 0, "completed": 1024, "cycles": 12500, "refresh": 123}
    fields.update(changes)
    bits = (0x544D << 240) | (2 << 232)
    for name, bit in {"flags": 224, "stage": 220, "reason": 216, "checked": 204,
                      "source": 192, "scratch": 180, "word": 148, "expected": 132,
                      "observed": 116, "completed": 84, "cycles": 20, "refresh": 4}.items():
        bits |= fields[name] << bit
    return f"{bits:064x}"


class BoardStatusTests(unittest.TestCase):
    def test_burst_profile_identity(self):
        raw = packet(); raw = raw[:4] + "04" + raw[6:-1] + "f"
        result = decode_snapshot(raw)
        self.assertEqual(result["read_burst_words"], 4)
        self.assertEqual(result["engine"], "pipelined")
        with self.assertRaises(ValueError): decode_snapshot(raw[:-1] + "b")

    def test_benchmark_engine_identity_and_legacy_compatibility(self):
        for engine, nibble in (("serialized", 0xA), ("pipelined", 0xB)):
            raw = packet(); raw = raw[:4] + "03" + raw[6:-1] + f"{nibble:x}"
            result = decode_snapshot(raw)
            self.assertEqual(result["engine"], engine)
            self.assertTrue(result["refresh_aligned"])
        self.assertEqual(decode_snapshot(packet())["engine"], "unspecified")

    def test_unknown_benchmark_workload_rejected(self):
        raw = packet(); raw = raw[:4] + "03" + raw[6:]
        for nibble in (0, 1, 6, 7, 14, 15):
            with self.subTest(nibble=nibble), self.assertRaises(ValueError):
                decode_snapshot(raw[:-1] + f"{nibble:x}")

    def test_read_trace_order_and_capture_index(self):
        value = (0x5254 << 240) | (1 << 232) | (7 << 228) | (12 << 224) | (0x010007F0 << 192)
        for i in range(12):
            value |= (0x1000 + i) << (16 * i)
        result = decode_read_trace(f"{value:064x}")
        self.assertEqual(result["samples"], list(range(0x1000, 0x100C)))
        self.assertEqual(result["consumed_value"], 0x1007)
        self.assertEqual(result["byte_address"], 0x010007F0)

    def test_incomplete_trace_rejected(self):
        value = (0x5254 << 240) | (1 << 232) | (7 << 228) | (8 << 224)
        with self.assertRaises(ValueError):
            decode_read_trace(f"{value:064x}")

    def test_empty_trace_before_first_sdram_read(self):
        value = (0x5254 << 240) | (1 << 232) | (8 << 228)
        self.assertFalse(decode_read_trace(f"{value:064x}")["available"])
    def test_complete_pass(self):
        decoded = decode_snapshot(packet())
        self.assertEqual(decoded["status"], "pass")
        self.assertEqual(decoded["completed_elements"], 1024)

    def test_source_failure_before_copy(self):
        decoded = decode_snapshot(packet(flags=0x35, reason=6, checked=0, source=7,
                                          completed=0, word=7, expected=0x1234, observed=0x1235))
        self.assertEqual(decoded["failure"], "sdram_data_mismatch")
        self.assertEqual(decoded["failure_byte_address"], 0x010007FE)

    def test_local_and_final_failures(self):
        for raw, label in ((packet(flags=0x15, reason=9, checked=0, source=0, scratch=0,
                                  completed=0), "scratchpad_data_mismatch"),
                           (packet(flags=0xF5, reason=4, checked=0), "tensor_data_mismatch")):
            self.assertEqual(decode_snapshot(raw)["failure"], label)

    def test_wrong_size_signature_version_and_reserved_bits(self):
        raw = packet()
        for bad in (raw[:-1], "f" + raw[1:], raw[:4] + "01" + raw[6:], raw[:-1] + "1"):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                decode_snapshot(bad)

    def test_false_pass_rejected(self):
        for change in ({"checked": 1000}, {"completed": 0}, {"flags": 0x73}, {"reason": 4}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                decode_snapshot(packet(**change))

    def test_invalid_terminal_and_valid_running_state(self):
        for change in ({"flags": 0xF7}, {"stage": 10}, {"flags": 0xFB},
                       {"source": 4095}, {"flags": 0x15, "reason": 6}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                decode_snapshot(packet(**change))
        self.assertEqual(decode_snapshot(packet(flags=0x11, stage=5, checked=0,
                                                source=0, scratch=0, completed=0))["status"], "running")

    def test_live_refresh_ignored_but_changed_result_rejected(self):
        result = decode_samples([packet(refresh=i) for i in (65535, 0, 1)])
        self.assertFalse(result["refresh_count_low_atomic"])
        with self.assertRaises(ValueError):
            decode_samples([packet(), packet(), packet(cycles=9999)])

    def test_require_three_samples(self):
        with self.assertRaises(ValueError):
            decode_samples([packet()])
