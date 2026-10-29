import unittest

from model.bank_layout import BankLayout


class BankLayoutTests(unittest.TestCase):
    def test_linear_mapping(self):
        layout = BankLayout()
        self.assertEqual([layout.decode(word) for word in range(5)],
                         [(0, 0), (1, 0), (2, 0), (3, 0), (0, 1)])

    def test_exhaustive_bijection_and_round_trip(self):
        for layout in [BankLayout(), *(BankLayout(swizzle=True, shift=s) for s in range(2, 11))]:
            with self.subTest(layout=layout):
                locations = {layout.decode(word) for word in range(layout.words)}
                self.assertEqual(len(locations), layout.words)
                for word in range(layout.words):
                    self.assertEqual(layout.encode(*layout.decode(word)), word)

    def test_tuned_columns(self):
        for width in (8, 16, 32):
            words = [row * width for row in range(4)]
            self.assertEqual(BankLayout().service_cycles(words), 4)
            layout = BankLayout(swizzle=True, shift=width.bit_length() - 1)
            self.assertEqual(layout.service_cycles(words), 1)

    def test_one_mapping_is_not_best_for_every_stride(self):
        layout = BankLayout(swizzle=True, shift=5)
        self.assertEqual(layout.service_cycles([0, 8, 16, 24]), 4)
        self.assertEqual(layout.service_cycles([0, 16, 32, 48]), 2)
        self.assertEqual(layout.service_cycles([0, 32, 64, 96]), 1)

    def test_diagonal_can_regress(self):
        words = [0, 33, 66, 99]
        self.assertEqual(BankLayout().service_cycles(words), 1)
        self.assertEqual(BankLayout(swizzle=True, shift=5).service_cycles(words), 4)

    def test_aligned_rows_keep_four_banks(self):
        for shift in (3, 4, 5):
            layout = BankLayout(swizzle=True, shift=shift)
            for start in range(0, layout.words, 4):
                self.assertEqual(layout.service_cycles(list(range(start, start + 4))), 1)

    def test_buffer_and_capacity_boundaries_round_trip(self):
        layout = BankLayout(swizzle=True)
        for word in (0, 2046, 2047, 2048, 2049, 4094, 4095):
            self.assertEqual(layout.encode(*layout.decode(word)), word)

    def test_invalid_configurations_and_addresses(self):
        for kwargs in ({"row_width": 0}, {"swizzle": True, "shift": 1},
                       {"swizzle": True, "shift": 11}):
            with self.assertRaises(ValueError):
                BankLayout(**kwargs)
        layout = BankLayout()
        for word in (-1, 4096):
            with self.assertRaises(ValueError):
                layout.decode(word)
        for bank, row in ((4, 0), (-1, 0), (0, 1024)):
            with self.assertRaises(ValueError):
                layout.encode(bank, row)


if __name__ == "__main__":
    unittest.main()
