"""Keep C++ checking independent and preserve strict mutation diagnoses."""
import unittest

from scripts.mutation_catalog import MUTATIONS
from scripts.run_dpi_uvm_tests import cpp_mutation
from scripts.run_mutation_tests import classify


class DpiContractTests(unittest.TestCase):
    def test_cpp_functional_diagnoses_are_distinct_from_sv_baseline(self):
        for mutation in MUTATIONS:
            mapped=cpp_mutation(mutation)
            self.assertEqual(mapped.before,mutation.before)
            self.assertEqual(mapped.after,mutation.after)
            for old,new in zip(mutation.checker_ids,mapped.checker_ids):
                if 'STABILITY' not in old:
                    self.assertTrue(new.startswith('TMA_CPP_'))
                else:
                    self.assertEqual(old,new)

    def test_refresh_control_keeps_independent_pin_checker(self):
        mutation=next(m for m in MUTATIONS if m.model_diagnostic)
        mapped=cpp_mutation(mutation)
        self.assertEqual(mapped.checker_ids,())
        self.assertEqual(mapped.model_diagnostic,'SDRAM_MODEL refresh deadline missed')

    def test_sv_scoreboard_cannot_mask_a_missing_cpp_detection(self):
        mutation=cpp_mutation(next(m for m in MUTATIONS if m.name=='fifo_data_bit_flipped'))
        sv='# UVM_ERROR scoreboard.svh(10) @ 200: env [TMA_WRITE_DATA] corrupted data\n'
        cpp=sv.replace('TMA_WRITE_DATA','TMA_CPP_WRITE_DATA')
        self.assertEqual(classify(sv,mutation,0)['outcome'],'unexpected_failure')
        self.assertEqual(classify(cpp,mutation,0)['outcome'],'detected')
        self.assertEqual(classify(sv+cpp,mutation,0)['outcome'],'unexpected_failure')


if __name__=='__main__':unittest.main()
