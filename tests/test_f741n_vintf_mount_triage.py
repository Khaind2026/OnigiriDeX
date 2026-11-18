"""Synthetic tests for read-only b6q VINTF/fstab triage."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from audit_b6q_vintf_mounts import analyze


class TriageTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        (self.root / ".b6q-prepared").write_text("ready\n")
        (self.root / "port-origin.json").write_text(json.dumps({
            "target": "SM-F741N", "donor": "SM-F956N",
        }))
        paths = {
            "system/system/etc/vintf/compatibility_matrix.xml":
                '<compatibility-matrix version="1.0" type="framework" level="8">'
                '<hal><name>android.hardware.graphics.composer</name></hal>'
                '<hal optional="true"><name>android.hardware.optional</name></hal>'
                '<hal><name>android.hardware.missing.hal</name></hal>'
                '</compatibility-matrix>',
            "vendor/etc/vintf/manifest.xml":
                '<manifest version="1.0" type="device" target-level="8">'
                '<hal><name>android.hardware.graphics.composer</name></hal>'
                '</manifest>',
            "vendor/etc/fstab.test":
                '/dev/block/by-name/system /system erofs ro wait,logical,first_stage_mount,avb\n',
            "system/system/build.prop": "ro.build.version.sdk=35\n",
            "vendor/build.prop": "ro.product.vendor.device=b6q\n",
        }
        for path, content in paths.items():
            file = self.root / path
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_text(content)

    def test_presents_only_candidates_and_never_grants_flash(self):
        report = analyze(self.root)
        self.assertFalse(report["flashable"])
        self.assertEqual(report["candidate_missing_hal_names_unverified"],
                         ["android.hardware.missing.hal"])
        self.assertEqual(report["device_manifest_hal_names"],
                         ["android.hardware.graphics.composer"])
        self.assertEqual(len(report["fstab_probes"]), 1)
        self.assertTrue(report["fstab_probes"][0]["matching_rules"][0]["mentions_avb"])
        self.assertEqual(report["properties"]["system"]["properties"]["ro.build.version.sdk"], "35")

    def test_rejects_incorrect_donor(self):
        (self.root / "port-origin.json").write_text(json.dumps({
            "target": "SM-F741N", "donor": "SM-F946N",
        }))
        with self.assertRaisesRegex(ValueError, "Unexpected target/donor"):
            analyze(self.root)

    def test_handles_unavailable_vintf_files(self):
        (self.root / "system/system/etc/vintf/compatibility_matrix.xml").unlink()
        report = analyze(self.root)
        self.assertEqual(report["framework_matrix_files"], [])
        self.assertFalse(report["flashable"])


if __name__ == "__main__":
    unittest.main()
