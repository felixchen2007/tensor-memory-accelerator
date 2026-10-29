"""Prevent false mutation detections from tool errors or unrelated failures."""
from dataclasses import replace
from pathlib import Path
import unittest

from scripts.mutation_catalog import MUTATIONS
from scripts.run_mutation_tests import classify, nominal_result

ROOT = Path(__file__).resolve().parents[1]


class MutationCampaignTests(unittest.TestCase):
    def test_catalog_is_unique_and_every_patch_changes_exactly_one_anchor(self):
        self.assertEqual(len({m.name for m in MUTATIONS}), len(MUTATIONS))
        for mutation in MUTATIONS:
            with self.subTest(mutation=mutation.name):
                original = (ROOT / mutation.source).read_bytes()
                patched = mutation.apply(original)
                self.assertNotEqual(original, patched)
                self.assertEqual(patched.replace(mutation.after.encode(), mutation.before.encode(), 1), original)
                identity = mutation.identity(original)
                self.assertNotEqual(identity['source_sha256'], identity['mutated_sha256'])

    def test_missing_duplicate_and_ineffective_anchors_fail_closed(self):
        mutation = MUTATIONS[0]
        for source in (b'', mutation.before.encode() * 2):
            with self.assertRaises(ValueError):
                mutation.apply(source)
        with self.assertRaises(ValueError):
            replace(mutation, after=mutation.before).apply(mutation.before.encode())

    def test_only_designated_first_uvm_diagnosis_counts(self):
        mutation = MUTATIONS[0]
        caught = '# UVM_ERROR checker.svh(89) @ 200: env [TMA_WRITE_DATA] DMA data mismatch\n'
        self.assertEqual(classify(caught, mutation, 0)['outcome'], 'detected')
        unrelated = caught.replace('TMA_WRITE_DATA', 'TMA_TIMEOUT')
        self.assertEqual(classify(unrelated + caught, mutation, 0)['outcome'], 'unexpected_failure')

    def test_tool_errors_and_absent_diagnosis_are_not_detections(self):
        caught = '# UVM_ERROR checker.svh(89) @ 200: env [TMA_WRITE_DATA] DMA data mismatch\n'
        for error in ('# ** Error: elaboration failed\n', '# ** Fatal: load failure\n',
                      'Failure to checkout svverification license feature\n'):
            self.assertEqual(classify(error + caught, MUTATIONS[0], 1)['outcome'], 'infrastructure_error')
        self.assertEqual(classify('external timeout', MUTATIONS[0], 1)['outcome'], 'unexpected_failure')
        self.assertEqual(classify(caught, MUTATIONS[0], 211)['outcome'], 'infrastructure_error')
        self.assertEqual(classify('[TMA_UVM_PASS]', MUTATIONS[0], 0)['outcome'], 'survived')

    def test_refresh_requires_specific_pin_model_failure(self):
        mutation = next(m for m in MUTATIONS if m.model_diagnostic)
        log = '# ** Fatal: SDRAM_MODEL refresh deadline missed gap=781\n'
        self.assertEqual(classify(log, mutation, 1)['outcome'], 'detected')
        self.assertEqual(classify(log.replace('refresh deadline missed', 'bus contention'), mutation, 1)['outcome'], 'unexpected_failure')

    def test_control_requires_clean_severities_and_completed_probes(self):
        log = ('# [TMA_MUTATION_PROBES_DONE] probes complete\n'
               '# [TMA_UVM_PASS] descriptors=34 pipelined=1 burst_words=4 swizzle=0\n'
               '# UVM_WARNING : 0\n# UVM_ERROR : 0\n# UVM_FATAL : 0\n')
        self.assertEqual(nominal_result(log, 0)['descriptors'], 34)
        for bad, code in ((log, 1), (log.replace('TMA_MUTATION_PROBES_DONE', 'MISSING'), 0),
                          (log.replace('UVM_WARNING : 0', 'UVM_WARNING : 1'), 0),
                          (log.replace('descriptors=34', 'descriptors=33'), 0)):
            with self.assertRaises(RuntimeError):
                nominal_result(bad, code)


if __name__ == '__main__':
    unittest.main()
