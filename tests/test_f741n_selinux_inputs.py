"""Synthetic tests for read-only F741N/F956N SELinux input compatibility."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from audit_b6q_selinux_inputs import inspect, PARTITIONS


class SeLinuxReadinessTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        (self.root / ".b6q-prepared").write_text("ready\n")
        (self.root / "port-origin.json").write_text(json.dumps({
            "target": "SM-F741N", "donor": "SM-F956N",
        }))
        files = (
            "system/system/etc/selinux/plat_sepolicy.cil",
            "system/system/etc/selinux/plat_file_contexts",
            "vendor/etc/selinux/vendor_sepolicy.cil",
            "vendor/etc/selinux/vendor_file_contexts",
            "vendor/etc/selinux/plat_sepolicy_vers.txt",
            "system/system/etc/selinux/mapping/202404.cil",
        )
        for name in files:
            p = self.root / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("202404\n" if name.endswith("vers.txt") else "test\n")
        for part in PARTITIONS:
            f = self.root / "configs" / ("file_context-" + part)
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text("dummy\n")

    def test_matching_vendor_policy_mapping_not_a_boot_pass(self):
        result = inspect(self.root)
        self.assertEqual(result["status"],
                         "SELINUX_FILES_PRESENT_COMBINED_POLICY_NOT_VERIFIED")
        self.assertEqual(result["stock_f741n_vendor_policy_version"], "202404")
        self.assertTrue(result["donor_system_compat_mapping_found"])
        self.assertFalse(result["flashable"])
        self.assertFalse(result["bootable"])

    def test_missing_compatibility_mapping_blocks(self):
        (self.root / "system/system/etc/selinux/mapping/202404.cil").unlink()
        result = inspect(self.root)
        self.assertEqual(result["status"],
                         "BLOCKED_F741N_VENDOR_TO_F956N_SYSTEM_MAPPING_MISSING")
        self.assertFalse(result["flashable"])

    def test_incomplete_vendor_policy_not_success(self):
        (self.root / "vendor/etc/selinux/vendor_sepolicy.cil").unlink()
        result = inspect(self.root)
        self.assertEqual(result["status"],
                         "INCOMPLETE_SELINUX_POLICY_COMPONENTS")
        self.assertFalse(result["flashable"])

    def test_vendor_policy_version_is_required(self):
        (self.root / "vendor/etc/selinux/plat_sepolicy_vers.txt").unlink()
        result = inspect(self.root)
        self.assertEqual(result["status"], "UNKNOWN_SELINUX_POLICY_VERSION_OR_LAYOUT")
        self.assertFalse(result["flashable"])

    def test_incorrect_donor_rejected(self):
        (self.root / "port-origin.json").write_text(json.dumps({
            "target": "SM-F741N", "donor": "SM-F946N",
        }))
        with self.assertRaisesRegex(ValueError, "Unexpected"):
            inspect(self.root)


if __name__ == "__main__":
    unittest.main()
