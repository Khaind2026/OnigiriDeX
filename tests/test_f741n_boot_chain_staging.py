"""Tests for selective F741N stock boot-chain staging and safe refusal."""
from pathlib import Path
import io
import json
import sys
import tarfile
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from stage_b6q_boot_chain import ASSETS, BUILD, TARGET, inventory, stage

MAGICS = {name: magic or b"UNKNOWN" for name, (magic, _) in ASSETS.items()}


def make_archive(path, missing=(), extra=(), duplicate=False):
    with tarfile.open(path, "w") as archive:
        for name in ASSETS:
            if name in missing:
                continue
            member = tarfile.TarInfo(name + ".lz4")
            payload = b"\x04\x22\x4d\x18" + b"0" * 16
            member.size = len(payload)
            archive.addfile(member, io.BytesIO(payload))
        for name in extra:
            member = tarfile.TarInfo(name)
            payload = b"0" * 32
            member.size = len(payload)
            archive.addfile(member, io.BytesIO(payload))
        if duplicate:
            member = tarfile.TarInfo("boot.img.lz4")
            data = b"\x04\x22\x4d\x18" + b"0" * 16
            member.size = len(data)
            archive.addfile(member, io.BytesIO(data))


class F741NBootStageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.archive = self.base / f"AP_{BUILD}_test.tar.md5"
        make_archive(self.archive)

    def test_expected_model_and_boot_files(self):
        self.assertEqual(TARGET, "SM-F741N")
        items = inventory(self.archive)
        self.assertIn("boot.img", items)
        self.assertIn("vendor_boot.img", items)
        self.assertIn("vbmeta_system.img", items)
        self.assertNotIn("super.img", items)

    def test_no_missing_required_boot_file_allowed(self):
        make_archive(self.archive, missing=("init_boot.img",))
        with self.assertRaisesRegex(ValueError, "Missing F741N boot chain"):
            inventory(self.archive)

    def test_no_avb_metadata_is_blocked(self):
        make_archive(self.archive, missing=("vbmeta.img", "vbmeta_system.img"))
        with self.assertRaisesRegex(ValueError, "no known AVB metadata"):
            inventory(self.archive)

    def test_duplicate_entries_blocked(self):
        make_archive(self.archive, duplicate=True)
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            inventory(self.archive)

    def test_path_traversal_member_is_ignored_and_never_extracted(self):
        make_archive(self.archive, extra=("../../outside.img", "super.img.lz4"))
        items = inventory(self.archive)
        self.assertEqual(set(items), set(ASSETS))

    @mock.patch("stage_b6q_boot_chain.inspect_avb", return_value={"checked": False})
    @mock.patch("stage_b6q_boot_chain.decode_member")
    def test_stage_only_checked_stock_target_and_never_overwrite(self, decode, _avb):
        def fake_decode(_pkg, member, output, _tool):
            name = member.name.removesuffix(".lz4")
            payload = MAGICS[name] + b"\x00" * 1024
            output.write_bytes(payload)
            return len(payload)
        decode.side_effect = fake_decode
        dest = self.base / "target-only" / "stock"
        report = stage(self.archive, dest)
        self.assertEqual(report["model"], TARGET)
        self.assertEqual(report["firmware_build"], BUILD)
        self.assertTrue((dest / "boot.img").is_file())
        self.assertFalse((dest / "super.img").exists())
        self.assertFalse((dest / "BL_F956N").exists())
        self.assertTrue((dest / "manifest.json").exists())
        self.assertEqual(
            json.loads((dest / "manifest.json").read_text())["status"],
            "F741N_STOCK_BOOT_IMAGES_NOT_FLASHABLE"
        )
        self.assertEqual(len(list(dest.glob("*.img"))), len(ASSETS))
        with self.assertRaisesRegex(FileExistsError, "Refusing to overwrite"):
            stage(self.archive, dest)

    @mock.patch("stage_b6q_boot_chain.decode_member")
    def test_invalid_target_image_magic_refuses_to_publish(self, decode):
        def fake_decode(_pkg, _member, output, _tool):
            output.write_bytes(b"BADMAGIC" + b"\x00" * 1024)
            return output.stat().st_size
        decode.side_effect = fake_decode
        dest = self.base / "bad"
        with self.assertRaisesRegex(ValueError, "Unexpected F741N boot.img"):
            stage(self.archive, dest)
        self.assertFalse(dest.exists())


if __name__ == "__main__":
    unittest.main()
