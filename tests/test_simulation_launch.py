"""A faster launch must preserve the checked work and negative diagnoses."""
import unittest

from scripts.run_xsim_standalone import signature


NOMINAL = '''UVM_INFO env [TMA_SCENARIOS] bank_family=20/20 offsets=1111
UVM_INFO env [TMA_UVM_PASS] descriptors=46 read_checks=2937 write_checks=2937 memory_checks=25797
UVM_INFO env [TMA_CPP_METRICS] calls=44673 api_ns=11000000
UVM_WARNING : 0
UVM_ERROR : 0
UVM_FATAL : 0
$finish called at time : 4654430 ns : File "vendor.sv" Line 1
'''


class SimulationLaunchTests(unittest.TestCase):
    def test_timing_noise_does_not_change_workload_identity(self):
        self.assertEqual(signature(NOMINAL), signature(NOMINAL.replace('api_ns=11000000', 'api_ns=9000000')))

    def test_reduced_work_or_different_cycles_cannot_count_as_matched_speedup(self):
        for before, after in [('memory_checks=25797', 'memory_checks=4096'),
                              ('read_checks=2937', 'read_checks=2904'),
                              ('offsets=1111', 'offsets=0111'),
                              ('4654430 ns', '4654410 ns'),
                              ('UVM_ERROR : 0', 'UVM_ERROR : 1')]:
            with self.subTest(change=after):
                self.assertNotEqual(signature(NOMINAL), signature(NOMINAL.replace(before, after)))

    def test_corruption_control_must_keep_both_independent_diagnoses(self):
        cpp = 'UVM_ERROR cpp.sv(2) @ 20: env [TMA_CPP_READ_DATA] corruption\n'
        sv = 'UVM_ERROR sv.svh(3) @ 20: env [TMA_READ_DATA] corruption\n'
        self.assertNotEqual(signature(cpp + sv), signature(cpp))
        self.assertNotEqual(signature(cpp + sv), signature(sv))

    def test_executed_covergroup_report_cannot_disappear(self):
        self.assertNotEqual(signature(NOMINAL), signature(NOMINAL +
                            'UVM_INFO coverage [TMA_COVERGROUP] functional_coverage=100.0\n'))


if __name__ == '__main__':
    unittest.main()
