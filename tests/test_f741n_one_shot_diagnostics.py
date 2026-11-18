"""Offline tests for the one-shot b6q diagnostic ZIP tool."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from diagnose_b6q_all import scan, package, get_reports, summary_text


class OneShotDiagnosticsTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        (self.root / "scripts").mkdir()
        (self.root / "scripts/audit_b6q_vintf_mounts.py").write_text("# fake\n")
        file = self.root / "out/reports/f741n-f956n-odin-layout.json"
        file.parent.mkdir(parents=True)
        file.write_text(json.dumps({"status": "tar_headers_only_no_partition_extraction"}))
        self.large = self.root / "out/b6q/build/DuyKhaiDeX_F741N_BRANDED_SUPER_PREVIEW_NOT_FOR_FLASH.img"
        self.large.parent.mkdir(parents=True)
        self.large.write_bytes(b"TEST_FIRMWARE_BYTES_NOT_FOR_ZIP")

    def test_collect_missing_sources_without_crashing(self):
        result = scan(self.root)
        self.assertFalse(result["flashable"])
        self.assertEqual(result["bootable"], "NOT_VERIFIED")
        self.assertEqual(result["sections"]["vintf_mount_triage"]["result"], "UNKNOWN")
        self.assertEqual(result["sections"]["boot_chain"]["result"], "UNKNOWN")
        self.assertTrue(result["sections"]["super_preview"]["present"])
        self.assertIn("DO NOT FLASH", summary_text(result))

    def test_bundle_has_only_derived_reports_not_images(self):
        result = scan(self.root)
        dest = self.root / "diag.zip"
        count = package(self.root, dest, result)
        self.assertEqual(count, 1)
        with zipfile.ZipFile(dest) as z:
            contents = set(z.namelist())
            self.assertIn("summary.json", contents)
            self.assertIn("summary.txt", contents)
            self.assertIn("reports/out__reports__f741n-f956n-odin-layout.json", contents)
            self.assertFalse(any(item.endswith(".img") for item in contents))
            self.assertNotIn(b"TEST_FIRMWARE_BYTES_NOT_FOR_ZIP", dest.read_bytes())
            self.assertFalse(json.loads(z.read("summary.json"))["flashable"])

    def test_refuses_overwrite(self):
        dest = self.root / "diag.zip"
        dest.write_text("existing")
        with self.assertRaisesRegex(ValueError, "already exists"):
            package(self.root, dest, scan(self.root))
        self.assertEqual(dest.read_text(), "existing")

    def test_invalid_json_does_not_stop_zip(self):
        malformed = self.root / "out/reports/f741n-f956n-framework-audit.json"
        malformed.write_text("not JSON")
        reports, included = get_reports(self.root)
        key = "out/reports/f741n-f956n-framework-audit.json"
        self.assertEqual(reports[key]["status"], "INVALID")
        self.assertNotIn(key, included)
        dest = self.root / "diag.zip"
        package(self.root, dest, scan(self.root))
        with zipfile.ZipFile(dest) as z:
            summary = json.loads(z.read("summary.json"))
        self.assertEqual(summary["sections"]["existing_reports"][key]["status"], "INVALID")


if __name__ == "__main__":
    unittest.main()
