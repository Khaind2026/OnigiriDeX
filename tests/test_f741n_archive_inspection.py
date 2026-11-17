"""Offline tests for the read-only Fold6 donor / Flip6 target archive scanner."""
import io
from pathlib import Path
import tarfile
import tempfile
import unittest

from scripts.inspect_f741n_f956n_archives import MODELS, run


def make_tar(destination, names):
    with tarfile.open(destination, mode="w:") as archive:
        for name in names:
            payload = b"test-only"
            member = tarfile.TarInfo(name)
            member.size = len(payload)
            archive.addfile(member, io.BytesIO(payload))
    # Samsung Odin tar.md5 packages add a checksum footer after TAR end blocks;
    # archive parsing must not depend on extracting or interpreting that footer.
    with destination.open("ab") as handle:
        handle.write(b"0" * 32 + b"  " + destination.name.removesuffix(".md5").encode() + b"\n")


class ArchiveHeaderInspectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def add_model(self, model, ap_members):
        folder = self.root / (model + "_SKC")
        folder.mkdir()
        build = MODELS[model]["build"]
        make_tar(folder / f"AP_{build}_TEST.tar.md5", ap_members)
        make_tar(folder / f"BL_{build}_TEST.tar.md5", ["vbmeta.img.lz4", "up_param.bin"])

    def test_target_and_donor_are_separate(self):
        self.add_model("SM-F741N", ["super.img.lz4", "boot.img.lz4", "dtbo.img.lz4"])
        self.add_model("SM-F956N", ["system.img.lz4", "product.img.lz4"])
        report = run(self.root)
        self.assertEqual(report["status"], "tar_headers_only_no_partition_extraction")
        self.assertEqual(report["devices"][0]["model"], "SM-F741N")
        self.assertEqual(report["devices"][0]["ap_image_layout"], "super")
        self.assertIn("boot.img", report["devices"][0]["ap_image_members"])
        self.assertEqual(report["devices"][1]["ap_image_layout"], "separate_partition_images")
        self.assertFalse((self.root / "super.img.lz4").exists())

    def test_unknown_ap_layout_is_reported_not_assumed(self):
        self.add_model("SM-F741N", ["boot.img.lz4"])
        self.add_model("SM-F956N", ["vendor_boot.img.lz4"])
        report = run(self.root)
        self.assertEqual(report["devices"][0]["ap_image_layout"], "unknown")

    def test_missing_donor_refuses(self):
        self.add_model("SM-F741N", ["super.img.lz4"])
        with self.assertRaisesRegex(ValueError, "Missing or invalid"):
            run(self.root)


if __name__ == "__main__":
    unittest.main()
