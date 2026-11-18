"""Read-only classification of mixed F741N/F956N host neverallow failures."""
import sys
from pathlib import Path
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from triage_b6q_neverallow import analyze


class NeverallowTriageTests(unittest.TestCase):
    def test_detects_violation_with_line_hint_and_sanitized_public_counts(self):
        output = (
            "libsepol: neverallow check failed at /home/user/vendor/etc/selinux/"
            "vendor_sepolicy.cil:124 from file\n"
            "(allow vendor_service system_file (file (read)))\n"
            "libsepol.check_assertions: 1 neverallow failures occurred\n"
        )
        r = analyze({"passes": {"strict_neverallow": {
            "status": "FAILED", "stderr_tail": output, "stdout_tail": "",
        }}})
        self.assertEqual(r["status"], "NEVERALLOW_RULE_LOCATIONS_IDENTIFIED_PARTIALLY")
        self.assertGreaterEqual(r["suspected_violation_lines"], 1)
        self.assertEqual(r["local_rule_evidence"][0]["first_line_number_hint"], 124)
        self.assertEqual(r["local_rule_evidence"][0]["origin_partition_hint"], "vendor")
        self.assertIn("file", r["allow_statement_class_counts"])
        self.assertNotIn("/home/", str(r["public_fields"]))
        self.assertFalse(r["flashable"])

    def test_strict_pass_does_not_report_violations(self):
        r = analyze({"passes": {"strict_neverallow": {
            "status": "COMPILED", "stderr_tail": "", "stdout_tail": "",
        }}})
        self.assertEqual(r["status"], "HOST_STRICT_POLICY_COMPILED")
        self.assertEqual(r["suspected_violation_lines"], 0)

    def test_failed_without_diagnostic_is_unknown_not_zero_violations(self):
        r = analyze({"passes": {"strict_neverallow": {
            "status": "FAILED", "stderr_tail": "failed to compile", "stdout_tail": "",
        }}})
        self.assertEqual(r["status"], "STRICT_FAILED_WITHOUT_NEVERALLOW_RULE_LOCATIONS")
        self.assertEqual(r["suspected_violation_lines"], 0)
        self.assertFalse(r["flashable"])

    def test_summary_lines_not_counted_as_a_separate_violating_rule(self):
        r = analyze({"passes": {"strict_neverallow": {
            "status": "FAILED", "stderr_tail":
                "neverallow check failed at /system/etc/selinux/plat_sepolicy.cil:8\n"
                "1 neverallow failures occurred\n", "stdout_tail": "",
        }}})
        self.assertEqual(r["suspected_violation_lines"], 1)

    def test_neverallow_parse_failure_does_not_claim_success(self):
        r = analyze({"passes": {"strict_neverallow": {
            "status": "FAILED", "stderr_tail":
                "libsepol: neverallow failures occurred\n", "stdout_tail": "",
        }}})
        self.assertNotEqual(r["status"], "HOST_STRICT_POLICY_COMPILED")


if __name__ == "__main__":
    unittest.main()
