"""Tests for opt-in, sanitized DuyKhaiDeX F741N PR status bridge."""
import io
import pathlib
import subprocess
import sys
import unittest
from contextlib import redirect_stdout
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))
from b6q_fast_status import safe_status, scrub_errors, markdown_report, publish_public, main


def statuses():
    return {
        "policy_mapping": "SELINUX_FILES_PRESENT_COMBINED_POLICY_NOT_VERIFIED",
        "mapping_exists": True,
        "secilc": "HOST_SELINUX_COMPILE_FAILED",
        "neverallow": "FAILED_HOST_ONLY",
        "strict_phase": "FAILED",
        "strict_failure_category": "NEVERALLOW_VIOLATION_DETECTED",
        "checkvintf": "NOT_RUN_CHECKVINTF_MISSING",
        "hal_contracts": "POSSIBLE_F741N_F956N_HAL_CONTRACT_MISMATCH",
        "hal_required": 5,
        "hal_matched": 4,
        "hal_candidates": 1,
        "hal_incomplete_cause_count": 2,
        "hal_unknown_reasons": {"VERSION_NOT_EXPLICIT": 2, "REGEX_INSTANCE_NEEDS_LIBVINTF": 1},
        "neverallow_locations_status": "NEVERALLOW_RULE_LOCATIONS_IDENTIFIED_PARTIALLY",
        "neverallow_location_count": 3,
        "avb_graph": "BLOCKED_STOCK_BL_ROOT_HASHTREE_COVERS_REBUILT_SYSTEM",
        "avb_root_overlap": 3,
        "secilc_errors": "/home/myname/secret_project/hello.cil: invalid CIL type\n",
        "checkvintf_errors": "",
    }


class FastStatusTests(unittest.TestCase):
    def test_statuses_are_allowlisted(self):
        self.assertEqual(safe_status("NOT_RUN_CHECKVINTF_MISSING"),
                         "NOT_RUN_CHECKVINTF_MISSING")
        self.assertEqual(safe_status("foo/bar"), "UNKNOWN")
        self.assertEqual(safe_status("abc; curl secret"), "UNKNOWN")

    def test_error_scrubbing_replaces_host_paths_and_email(self):
        raw = "/home/myname/projects/abc.cil: error send to user@example.org\n"
        cleaned = scrub_errors(raw)
        self.assertIn("invalid" not in cleaned and "error", cleaned)
        self.assertNotIn("myname", cleaned)
        self.assertNotIn("user@example.org", cleaned)
        self.assertIn("<local-path>", cleaned)

    def test_default_report_never_contains_raw_error(self):
        report = markdown_report(statuses())
        self.assertIn("HOST_SELINUX_COMPILE_FAILED", report)
        self.assertIn("BLOCKED_UNVERIFIED", report)
        self.assertIn("Strict failure category", report)
        self.assertIn("NEVERALLOW_VIOLATION_DETECTED", report)
        self.assertIn("POSSIBLE_F741N_F956N_HAL_CONTRACT_MISMATCH", report)
        self.assertIn("4/5", report)
        self.assertIn("HAL mismatch candidates", report)
        self.assertIn("VERSION_NOT_EXPLICIT", report)
        self.assertIn("NEVERALLOW_RULE_LOCATIONS_IDENTIFIED_PARTIALLY", report)
        self.assertIn("AVB signed modified partitions count", report)
        self.assertIn("BLOCKED_STOCK_BL_ROOT_HASHTREE_COVERS_REBUILT_SYSTEM", report)
        self.assertNotIn("myname", report)
        self.assertNotIn("secret_project", report)
        self.assertNotIn("invalid CIL type", report)

    def test_opt_in_error_excerpt_is_redacted(self):
        report = markdown_report(statuses(), include_errors=True)
        self.assertIn("invalid CIL type", report)
        self.assertNotIn("myname", report)
        self.assertNotIn("secret_project", report)
        self.assertIn("<local-path>", report)

    @mock.patch("b6q_fast_status.collect", return_value=statuses())
    @mock.patch("b6q_fast_status.publish_public")
    def test_default_only_prints_no_network(self, uploader, _):
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            self.assertEqual(main([]), 0)
        uploader.assert_not_called()
        self.assertIn("NOT UPLOADED", stdout.getvalue())

    @mock.patch("b6q_fast_status.collect", return_value=statuses())
    @mock.patch("b6q_fast_status.publish_public", return_value="https://example.com/pr-comment")
    def test_explicit_consent_required_for_network_publish(self, uploader, _):
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            self.assertEqual(main(["--publish-public"]), 0)
        uploader.assert_called_once()
        self.assertNotIn("secret_project", uploader.call_args.args[0])

    @mock.patch("b6q_fast_status.shutil.which", return_value="/mock/gh")
    @mock.patch("b6q_fast_status.subprocess.run")
    def test_gh_uses_stdin_not_command_line_secrets(self, execute, _):
        execute.side_effect = [
            subprocess.CompletedProcess([], 0, "", ""),
            subprocess.CompletedProcess([], 0, "https://example.com/comment", ""),
        ]
        returned = publish_public("Public report")
        self.assertIn("comment", returned)
        call = execute.call_args_list[1]
        self.assertIn("--body-file", call.args[0])
        self.assertEqual(call.kwargs["input"], "Public report")
        self.assertNotIn("Public report", call.args[0])


if __name__ == "__main__":
    unittest.main()
