"""Checks selective DeX asset staging without using Samsung firmware."""
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from stage_b6q_dex_assets import (
    ASSETS, ensure_inventory, extract, inspect_type
)


def zip_bytes():
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w") as archive:
        archive.writestr("AndroidManifest.xml", b"unit-test")
    return data.getvalue()


def test_audit():
    return {
        "status": "ANALYSIS_ONLY_NO_ROM",
        "devices": [
            {"model": "SM-F956N", "partitions": [{
                "partition": "system",
                "build_prop": {"properties": {"ro.build.version.sdk": "35"}},
                "directory_probe": {
                    "/system/priv-app": {"matching_names": [
                        "KnoxDesktopLauncher", "DesktopModeUiService", "DesktopSystemUI"
                    ]},
                    "/system/etc/permissions": {"matching_names": [
                        "privapp-permissions-com.sec.android.app.desktoplauncher.xml",
                        "privapp-permissions-com.sec.android.desktopmode.uiservice.xml",
                        "privapp-permissions-com.sec.android.dexsystemui.xml"
                    ]},
                    "/system/framework": {"matching_names": []}
                }
            }]},
            {"model": "SM-F741N", "partitions": [{
                "partition": "vendor",
                "build_prop": {"properties": {"ro.product.vendor.device": "b6q"}}
            }]}
        ]
    }


class DexStageTests(unittest.TestCase):
    def test_manifest_of_required_and_optional_assets(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "assets"

            def fake_copy(_binary, _image, source_path, output):
                if source_path.endswith(".jar"):
                    raise ValueError("optional jar not found")
                payload = (zip_bytes() if source_path.endswith(".apk")
                           else b"<permissions></permissions>")
                output.write_bytes(payload)
                return {"bytes": len(payload),
                        "sha256": hashlib.sha256(payload).hexdigest()}

            with mock.patch("stage_b6q_dex_assets.copy_from_erofs", fake_copy):
                result = extract("dump.erofs", Path("/stock.img"), dest)
            self.assertEqual(result["status"], "FOLD6_SOURCE_DEX_ASSETS_ONLY_NOT_PATCHED")
            self.assertEqual(
                sum(x["status"] == "COPIED" for x in result["files"]), 6
            )
            self.assertEqual(
                sum(x["status"] == "NOT_EXTRACTED" for x in result["files"]), 2
            )
            self.assertEqual(len(ASSETS), 8)
            self.assertEqual(len(list(dest.glob("*.apk"))), 3)
            self.assertEqual(len(list(dest.glob("*.xml"))), 3)
            self.assertTrue((dest / "manifest.json").exists())
            with self.assertRaisesRegex(FileExistsError, "Refusing to replace"):
                extract("dump.erofs", Path("/stock.img"), dest)

    def test_missing_required_archive_aborts_without_publishing(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "assets"

            def fake_copy(_binary, _image, _path, _out):
                raise ValueError("missing")
            with mock.patch("stage_b6q_dex_assets.copy_from_erofs", fake_copy):
                with self.assertRaisesRegex(ValueError, "Required source asset failed"):
                    extract("dump.erofs", Path("/stock.img"), dest)
            self.assertFalse(dest.exists())

    def test_file_type_checks(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            apk = folder / "valid.apk"
            apk.write_bytes(zip_bytes())
            inspect_type(apk, "apk")
            xml = folder / "perm.xml"
            xml.write_bytes(b"<permissions></permissions>")
            inspect_type(xml, "xml")
            apk.write_bytes(b"not a zip")
            with self.assertRaisesRegex(ValueError, "ZIP-based"):
                inspect_type(apk, "apk")

    @mock.patch("stage_b6q_dex_assets.verify_stage")
    @mock.patch("stage_b6q_dex_assets.report_from_data",
                return_value={"capacity_estimate_pass": True})
    def test_source_references_come_from_checked_audit(self, _capacity, _stage):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "out/reports").mkdir(parents=True)
            (root / "target/b6q").mkdir(parents=True)
            (root / "out/reports/f741n-f956n-framework-audit.json").write_text(
                json.dumps(test_audit())
            )
            (root / "out/reports/f741n-f956n-super-metadata.json").write_text("{}")
            (root / "target/b6q/port-plan.json").write_text("{}")
            image = ensure_inventory(root)
            self.assertEqual(image.name, "system.img")
            self.assertEqual(image.parent.name, "SM-F956N")
            report = test_audit()
            report["devices"][1]["partitions"][0]["build_prop"]["properties"][
                "ro.product.vendor.device"
            ] = "q6q"
            (root / "out/reports/f741n-f956n-framework-audit.json").write_text(
                json.dumps(report)
            )
            with self.assertRaisesRegex(ValueError, "not confirmed b6q"):
                ensure_inventory(root)


if __name__ == "__main__":
    unittest.main()
