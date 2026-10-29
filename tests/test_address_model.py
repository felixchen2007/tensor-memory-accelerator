import unittest
from dataclasses import replace

from model.address_model import Descriptor, addresses


class AddressModelTests(unittest.TestCase):
    def setUp(self):
        self.base = Descriptor(0x1000, 0x2000, 2, 3, 6, 2, 6, 2)

    def test_contiguous_copy(self):
        self.assertEqual(list(addresses(self.base)), [
            (0x1000, 0x2000, False), (0x1002, 0x2002, False),
            (0x1004, 0x2004, False), (0x1006, 0x2006, False),
            (0x1008, 0x2008, False), (0x100A, 0x200A, True)])

    def test_transpose(self):
        tile = replace(self.base, dst_row_stride=2, dst_col_stride=4)
        self.assertEqual([dst for _, dst, _ in addresses(tile)],
                         [0x2000, 0x2004, 0x2008, 0x2002, 0x2006, 0x200A])

    def test_padded_rows(self):
        tile = replace(self.base, src_row_stride=32)
        self.assertEqual([src for src, _, _ in addresses(tile)],
                         [0x1000, 0x1002, 0x1004, 0x1020, 0x1022, 0x1024])

    def test_zero_counts(self):
        for rows, cols in [(0, 0), (0, 3), (2, 0)]:
            tile = replace(self.base, rows=rows, cols=cols)
            self.assertTrue(tile.is_empty)
            self.assertEqual(list(addresses(tile)), [])

    def test_one_element_and_zero_strides(self):
        one = replace(self.base, rows=1, cols=1)
        self.assertEqual(list(addresses(one)), [(0x1000, 0x2000, True)])
        repeated = replace(self.base, src_row_stride=0, src_col_stride=0)
        self.assertEqual([src for src, _, _ in addresses(repeated)], [0x1000] * 6)

    def test_wrap_matches_fixed_width_arithmetic(self):
        tile = Descriptor(254, 255, 2, 2, 5, 2, 3, 1)
        self.assertEqual(list(addresses(tile, addr_width=8)),
                         [(254, 255, False), (0, 0, False),
                          (3, 2, False), (5, 3, True)])

    def test_maximum_count_axis(self):
        for rows, cols in [(65535, 1), (1, 65535)]:
            result = list(addresses(replace(self.base, rows=rows, cols=cols)))
            self.assertEqual(len(result), 65535)
            self.assertEqual(sum(last for _, _, last in result), 1)
            self.assertTrue(result[-1][2])

    def test_invalid_fields_rejected(self):
        for field, value in [("rows", -1), ("cols", 65536), ("src_base", -1),
                             ("dst_base", 1 << 32), ("src_row_stride", -2),
                             ("dst_col_stride", 1.5)]:
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                list(addresses(replace(self.base, **{field: value})))
        for addr_width, count_width in [(0, 16), (32, 0)]:
            with self.assertRaises(ValueError):
                list(addresses(self.base, addr_width, count_width))


if __name__ == "__main__":
    unittest.main()
