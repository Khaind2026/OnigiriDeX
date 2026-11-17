"""Tests for read-only F741N BL archive / AVB discovery."""
from pathlib import Path
import io
import json
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from inspect_b6q_bl_avb import make_report, scan_vbmeta, stock_bl_inventory


def make_bl(path, names):
    with tarfile.open(path, "w") as stream:
        for name in names:
            data = b"TEST_HEADER_ONLY"
            t = tarfile.TarInfo(name)
            t.size = len(data)
            stream.addfile(t, io.BytesIO(data))


class BlAvbTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.odin = self.root / "odin"
        imported = self.odin / "SM-F741N_SKC"
        imported.mkdir(parents=True)
        self.bl = imported / "BL_F741NKSS2BYGB_test.tar.md5"
        make_bl(self.bl, ["sboot.bin.lz4", "vbmeta.img.lz4", "xbl.img.lz4"])
        self.staged = self.root / "boot"
        self.staged.mkdir()
        (self.staged / "vbmeta_system.img").write_bytes(b"AVB0" + bytes(1024))
        self.old = self.root / "previous.json"
        self.old.write_text(json.dumps({
            "status": "BLOCKED_FOR_FLASH_UNVERIFIED_HYBRID_BOOT",
            "model": "SM-F741N", "flashable": False
        }))

    def test_identifies_vbmeta_in_correct_stock_bl_archive(self):
        result = stock_bl_inventory(self.odin)
        self.assertTrue(result["top_level_vbmeta_found"])
        self.assertEqual(result["entries"], 3)
        self.assertTrue(result["archive"].startswith("BL_F741NKSS2BYGB"))

    def test_absent_vbmeta_stays_unresolved(self):
        make_bl(self.bl, ["sboot.bin.lz4", "cm.bin.lz4"])
        result = stock_bl_inventory(self.odin)
        self.assertFalse(result["top_level_vbmeta_found"])

    def test_does_not_extract_BL_images(self):
        report = make_report(self.odin, self.staged, self.old)
        self.assertFalse(report["flashable"])
        self.assertEqual(report["status"], "BLOCKED_FOR_FLASH_UNVERIFIED_HYBRID_BOOT")
        self.assertEqual(len(list((self.odin / "SM-F741N_SKC").iterdir())), 1)
        self.assertTrue((self.staged / "vbmeta_system.img").exists())

    def test_avbtool_unavailable_is_not_misreported_as_verified(self):
        with mock.patch("inspect_b6q_bl_avb.shutil.which", return_value=None):
            info = scan_vbmeta(self.staged / "vbmeta_system.img")
        self.assertFalse(info["descriptors_parsed"])
        self.assertFalse(info["signature_verified"])

    @mock.patch("inspect_b6q_bl_avb.subprocess.run")
    def test_avbtool_extracts_partition_descriptors_without_signing(self, run):
        run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0,
            stdout=(
                "Minimum libavb version: 1.0\n"
                "Descriptors:\n"
                "    Hashtree descriptor:\n"
                "      Partition Name: system\n"
                "    Hashtree descriptor:\n"
                "      Partition Name: system_ext\n"
                "    Hashtree descriptor:\n"
                "      Partition Name: product\n"
            ), stderr=""
        )
        info = scan_vbmeta(self.staged / "vbmeta_system.img", "/fake/avbtool")
        self.assertTrue(info["descriptors_parsed"])
        self.assertEqual(info["modified_system_partition_overlap"],
                         ["product", "system", "system_ext"])
        self.assertFalse(info["signature_verified"])
        self.assertEqual(run.call_args.args[0][:2], ["/fake/avbtool", "info_image"])

    def test_wrong_previous_report_rejected(self):
        self.old.write_text(json.dumps({
            "model": "SM-F956N",
            "status": "BLOCKED_FOR_FLASH_UNVERIFIED_HYBRID_BOOT",
            "flashable": False
        }))
        with self.assertRaisesRegex(ValueError, "not the expected blocked F741N"):
            make_report(self.odin, self.staged, self.old)

    def test_nested_bl_filename_rejected(self):
        make_bl(self.bl, ["../../vbmeta.img.lz4"])
        with self.assertRaisesRegex(ValueError, "nested or unsafe"):
            stock_bl_inventory(self.odin)


if __name__ == "__main__":
    unittest.main()
