"""Build completion alone must not be mistaken for successful fitted timing."""
import unittest
from scripts.build_board import validate_timing, validate_pins


SUMMARY = "\n".join(f"Type : corner{i} Setup 'core'\nSlack : 1.0\nTNS : 0.0" for i in range(18))
COVERED = "Design is fully constrained for setup requirements\nDesign is fully constrained for hold requirements"


class BoardReportTests(unittest.TestCase):
    def test_configuration_pins_are_separate_from_user_ports(self):
        report = "\n".join(f"PORT{i} : P{i} : output : 3.3-V LVTTL : : 3 : Y" for i in range(50))
        report += "\n~ALTERA_TDO~ : M5 : output : 2.5 V : : 1B : N"
        report += "\naltera_reserved_tdi : L4 : input : 2.5 V : : 1B : N"
        self.assertEqual(len(validate_pins(report)), 50)
        with self.assertRaises(RuntimeError):
            validate_pins(report.replace("altera_reserved_tdi : L4", "altera_reserved_tdi : L5"))

    def test_unassigned_or_aliased_user_pin_rejected(self):
        report = "\n".join(f"PORT{i} : P{i} : output : 3.3-V LVTTL : : 3 : Y" for i in range(50))
        for bad in (report.replace("P49", "P0"), report.replace(": Y", ": N", 1)):
            with self.subTest(report=bad), self.assertRaises(RuntimeError):
                validate_pins(bad)

    def test_clean_report(self):
        timing, warnings = validate_timing(SUMMARY, COVERED)
        self.assertEqual(len(timing), 18)
        self.assertEqual(warnings, [])

    def test_negative_slack_rejected(self):
        with self.assertRaises(RuntimeError):
            validate_timing(SUMMARY.replace("Slack : 1.0", "Slack : -0.001", 1), COVERED)

    def test_missing_corner_report_rejected(self):
        with self.assertRaises(RuntimeError):
            validate_timing("Type : onlyone\nSlack : 1.0", COVERED)

    def test_unconstrained_paths_rejected(self):
        with self.assertRaises(RuntimeError):
            validate_timing(SUMMARY, COVERED.splitlines()[0])

    def test_only_known_empty_vendor_filter_pair_reviewed(self):
        warning = ("Warning (332174): Ignored filter at qsta_default_script.tcl(1297): "
                   "*phasedone_state* could not be matched\n"
                   "Warning (332049): Ignored set_false_path at qsta_default_script.tcl(1297): "
                   "Argument <to> is not an object ID")
        self.assertEqual(len(validate_timing(SUMMARY, COVERED+"\n"+warning)[1]), 2)
        with self.assertRaises(RuntimeError):
            validate_timing(SUMMARY, COVERED+"\n"+warning.splitlines()[1])

    def test_user_constraint_and_clock_warnings_rejected(self):
        for warning in (
            "Warning (332174): Ignored filter at de10_lite.sdc(2): *phasedone_state* could not be matched",
            "Warning (332174): Ignored filter at qsta_default_script.tcl(1297): *data_capture* could not be matched",
            "Warning (332088): No paths exist between clock target DRAM_CLK and its clock source",
            "Critical Warning (332148): Timing requirements not met",
        ):
            with self.subTest(warning=warning), self.assertRaises(RuntimeError):
                validate_timing(SUMMARY, COVERED+"\n"+warning)


if __name__ == "__main__":
    unittest.main()
