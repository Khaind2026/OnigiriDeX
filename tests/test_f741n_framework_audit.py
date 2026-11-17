"""Unit tests for the read-only b6q EROFS framework/vendor inventory."""
from pathlib import Path
import sys
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from audit_b6q_framework import dump_tool, properties, vintf_summary


class B6qAuditTests(unittest.TestCase):
    def test_build_props_selects_only_compatibility_fields(self):
        payload = (b"# tested\nro.build.version.sdk=35\nro.product.vendor.device=b6q\n"
                   b"persist.unrelated.value=private\nro.vndk.version=35\n")
        values = properties(payload)
        self.assertEqual(values["ro.build.version.sdk"], "35")
        self.assertEqual(values["ro.product.vendor.device"], "b6q")
        self.assertEqual(values["ro.vndk.version"], "35")
        self.assertNotIn("persist.unrelated.value", values)

    def test_vintf_extracts_names_without_full_xml_dump(self):
        payload = (b'<manifest version="1.0" type="device" target-level="8">'
                   b"<hal><name>android.hardware.graphics.composer3</name></hal>"
                   b"<hal><name>android.hardware.camera.provider</name></hal>"
                   b"</manifest>")
        summary = vintf_summary(payload)
        self.assertTrue(summary["parsed"])
        self.assertEqual(summary["target_level"], "8")
        self.assertIn("android.hardware.graphics.composer3", summary["hal_names"])
        self.assertEqual(summary["hal_count"], 2)

    def test_invalid_vintf_is_reported_not_faked(self):
        report = vintf_summary(b"<manifest><hal>")
        self.assertFalse(report["parsed"])
        self.assertIn("error", report)

    @mock.patch("audit_b6q_framework.subprocess.run")
    def test_dump_uses_read_only_operation_without_shell(self, run):
        run.return_value.returncode = 0
        run.return_value.stdout = b"ro.build.version.sdk=35\n"
        run.return_value.stderr = b""
        payload, error = dump_tool("/usr/bin/dump.erofs", Path("/img/system.img"),
                                   "--cat", "/system/build.prop")
        self.assertIsNone(error)
        self.assertEqual(payload, b"ro.build.version.sdk=35\n")
        args, kwargs = run.call_args
        self.assertEqual(args[0], ["/usr/bin/dump.erofs", "--cat",
                                   "--path=/system/build.prop", "/img/system.img"])
        self.assertFalse(kwargs["check"])

    @mock.patch("audit_b6q_framework.subprocess.run")
    def test_dump_rejects_large_output(self, run):
        run.return_value.returncode = 0
        run.return_value.stdout = b"X" * (2 * 1024 * 1024 + 1)
        run.return_value.stderr = b""
        payload, error = dump_tool("dump.erofs", Path("/img/system.img"),
                                   "--cat", "/system/build.prop")
        self.assertIsNone(payload)
        self.assertIn("safety limit", error)

    @mock.patch("audit_b6q_framework.subprocess.run")
    def test_missing_paths_report_errors(self, run):
        run.return_value.returncode = 1
        run.return_value.stdout = b""
        run.return_value.stderr = b"not found"
        payload, error = dump_tool("dump.erofs", Path("/img/system.img"),
                                   "--ls", "/system/priv-app")
        self.assertIsNone(payload)
        self.assertEqual(error, "not found")


if __name__ == "__main__":
    unittest.main()
