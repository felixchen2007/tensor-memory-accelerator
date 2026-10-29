import unittest
from dataclasses import replace

from model.address_model import Descriptor
from model.copy_model import ErrorCode, copy_tensor


class CopyModelTests(unittest.TestCase):
    def setUp(self):
        self.source = list(range(64))
        self.destination = [0xCAFE] * 64
        self.desc = Descriptor(0, 16, 2, 3, 6, 2, 6, 2)

    def test_copy_and_untouched_memory(self):
        result = copy_tensor(self.desc, self.source, self.destination)
        self.assertEqual(result.error_code, ErrorCode.OK)
        self.assertEqual(result.completed_elements, 6)
        self.assertEqual(result.destination[8:14], list(range(6)))
        self.assertEqual(result.destination[:8] + result.destination[14:],
                         [0xCAFE] * 58)
        self.assertEqual(self.destination, [0xCAFE] * 64)

    def test_transpose_data(self):
        result = copy_tensor(replace(self.desc, dst_row_stride=2, dst_col_stride=4),
                             self.source, self.destination)
        self.assertEqual(result.destination[8:14], [0, 3, 1, 4, 2, 5])

    def test_empty_alignment_and_initial_bounds(self):
        for desc, code in [
            (replace(self.desc, rows=0, src_base=1), ErrorCode.EMPTY),
            (replace(self.desc, src_base=1), ErrorCode.ALIGNMENT),
            (replace(self.desc, dst_col_stride=3), ErrorCode.ALIGNMENT),
            (replace(self.desc, src_base=128), ErrorCode.BOUNDS),
            (replace(self.desc, src_row_stride=128), ErrorCode.BOUNDS),
        ]:
            result = copy_tensor(desc, self.source, self.destination)
            self.assertEqual(result.error_code, code)
            self.assertEqual(result.reads, [])
            self.assertEqual(result.writes, [])

    def test_late_bounds_keep_partial_copy(self):
        desc = Descriptor(126, 0, 1, 2, 0, 2, 0, 2)
        result = copy_tensor(desc, self.source, self.destination)
        self.assertEqual(result.error_code, ErrorCode.BOUNDS)
        self.assertEqual(result.completed_elements, 1)
        self.assertEqual(result.destination[:2], [63, 0xCAFE])

    def test_read_fault_does_not_issue_corresponding_write(self):
        result = copy_tensor(self.desc, self.source, self.destination, read_fault=2)
        self.assertEqual(result.error_code, ErrorCode.READ)
        self.assertEqual(len(result.reads), 3)
        self.assertEqual(len(result.writes), 2)
        self.assertEqual(result.completed_elements, 2)

    def test_write_fault_is_not_counted_as_completed(self):
        result = copy_tensor(self.desc, self.source, self.destination, write_fault=2)
        self.assertEqual(result.error_code, ErrorCode.WRITE)
        self.assertEqual(len(result.writes), 3)
        self.assertEqual(result.completed_elements, 2)
        self.assertEqual(result.destination[10], 0xCAFE)

    def test_zero_strides_have_ordered_last_write_wins_semantics(self):
        result = copy_tensor(replace(self.desc, dst_row_stride=0, dst_col_stride=0),
                             self.source, self.destination)
        self.assertEqual(result.destination[8], 5)
        self.assertEqual(result.completed_elements, 6)
        self.assertEqual(len(result.writes), 6)


if __name__ == "__main__":
    unittest.main()
