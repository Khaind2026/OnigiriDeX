"""Synthetic offline tests for AOSP host VINTF checker integration."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from run_b6q_checkvintf import map_partitions, run_check


class HostVintfTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        (self.root / ".b6q-prepared").write_text("prepared\n")
        (self.root / "port-origin.json").write_text(json.dumps({
            "target": "SM-F741N", "donor": "SM-F956N",
        }))
        paths = ("system/system/etc/vintf", "system_ext/etc/vintf",
                 "product/etc/vintf", "vendor/etc/vintf", "odm/etc")
        for path in paths:
            (self.root / path).mkdir(parents=True)
        (self.root / "vendor/build.prop").write_text(
            "ro.product.first_api_level=34\n"
            "ro.board.first_api_level=34\n"
        )

    def test_maps_correct_mixed_firmware_partitions(self):
        mapped = map_partitions(self.root)
        self.assertEqual(mapped["system"], self.root / "system/system")
        self.assertEqual(mapped["vendor"], self.root / "vendor")
        self.assertEqual(mapped["odm"], self.root / "odm")

    @mock.patch("run_b6q_checkvintf.shutil.which", return_value=None)
    def test_binary_missing_is_unverified(self, _):
        report = run_check(self.root)
        self.assertEqual(report["status"], "NOT_RUN_CHECKVINTF_MISSING")
        self.assertFalse(report["flashable"])

    @mock.patch("run_b6q_checkvintf.subprocess.run")
    def test_host_pass_is_not_boot_or_flash_approval(self, execute):
        execute.return_value = subprocess.CompletedProcess(
            [], 0, "COMPATIBLE\n", ""
        )
        report = run_check(self.root, tool="/mock/checkvintf")
        self.assertEqual(report["status"], "HOST_VINTF_CHECK_PASSED_RUNTIME_UNVERIFIED")
        self.assertFalse(report["flashable"])
        self.assertFalse(report["bootable"])
        command = execute.call_args.args[0]
        self.assertIn("--check-compat", command)
        self.assertIn(f"/system:{self.root / 'system/system'}", command)
        self.assertIn("ro.product.first_api_level=34", command)
        self.assertNotIn("--rootdir", command)

    @mock.patch("run_b6q_checkvintf.subprocess.run")
    def test_host_incompatibility_is_blocker(self, execute):
        execute.return_value = subprocess.CompletedProcess(
            [], 1, "", "HAL version mismatch"
        )
        report = run_check(self.root, tool="/mock/checkvintf")
        self.assertEqual(report["status"], "HOST_VINTF_CHECK_FAILED")
        self.assertIn("HAL version mismatch", report["stderr"])
        self.assertFalse(report["flashable"])

    def test_missing_vendor_build_property_does_not_guess(self):
        (self.root / "vendor/build.prop").unlink()
        report = run_check(self.root, tool="/mock/checkvintf")
        self.assertEqual(report["status"], "NOT_RUN_INCOMPLETE_INPUT")
        self.assertFalse(report["flashable"])

    def test_reject_wrong_source(self):
        (self.root / "port-origin.json").write_text(json.dumps({
            "target": "SM-F741N", "donor": "SM-F946N",
        }))
        with self.assertRaisesRegex(ValueError, "Unexpected"):
            run_check(self.root, tool="/mock/checkvintf")


if __name__ == "__main__":
    unittest.main()
