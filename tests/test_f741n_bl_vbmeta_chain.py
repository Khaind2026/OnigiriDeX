"""Read-only F741N BL vbmeta chain inspection tests (synthetic firmware only)."""
import io
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from inspect_b6q_bl_vbmeta_chain import descriptors, extract_stock_bl_vbmeta, make_report


def fake_avb():
    raw = bytearray(4096)
    raw[:4] = b"AVB0"
    raw[4:8] = (1).to_bytes(4, "big")
    return bytes(raw)


def tar_with_member(path, members):
    with tarfile.open(path, "w") as package:
        for name, data in members:
            member = tarfile.TarInfo(name)
            member.size = len(data)
            package.addfile(member, io.BytesIO(data))


class ChainTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.folder = self.root / "odin" / "SM-F741N_SKC"
        self.folder.mkdir(parents=True)
        self.archive = self.folder / "BL_F741NKSS2BYGB_demo.tar.md5"
        tar_with_member(self.archive, [("vbmeta.img", fake_avb())])
        self.staged = self.root / "staged"
        self.staged.mkdir()
        (self.staged / "vbmeta_system.img").write_bytes(fake_avb())

    def test_descriptor_parser_distinguishes_chain_from_hashtree(self):
        output = (
            "Descriptors:\n"
            "    Chain Partition descriptor:\n"
            "      Partition Name:          vbmeta_system\n"
            "    Hashtree descriptor:\n"
            "      Partition Name:          system\n"
            "    Hash descriptor:\n"
            "      Partition Name:          product\n"
        )
        self.assertEqual(descriptors(output), [
            {"type": "chain partition", "partition": "vbmeta_system"},
            {"type": "hashtree", "partition": "system"},
            {"type": "hash", "partition": "product"},
        ])

    def test_extract_only_vbmeta_into_ephemeral_folder(self):
        with tempfile.TemporaryDirectory() as target:
            output = extract_stock_bl_vbmeta(self.archive, Path(target))
            self.assertEqual(output.read_bytes(), fake_avb())
        self.assertEqual(list(self.folder.iterdir()), [self.archive])

    def test_duplicate_or_nested_rejected(self):
        tar_with_member(self.archive, [("vbmeta.img", fake_avb()), ("vbmeta.img.lz4", fake_avb())])
        with tempfile.TemporaryDirectory() as target:
            with self.assertRaisesRegex(ValueError, "Exactly one"):
                extract_stock_bl_vbmeta(self.archive, Path(target))
        tar_with_member(self.archive, [("../vbmeta.img", fake_avb())])
        with tempfile.TemporaryDirectory() as target:
            with self.assertRaisesRegex(ValueError, "Unsafe nested"):
                extract_stock_bl_vbmeta(self.archive, Path(target))

    @mock.patch("inspect_b6q_bl_vbmeta_chain.info_image")
    def test_still_blocks_flash_after_reading_chain(self, info):
        info.side_effect = [
            "    Chain Partition descriptor:\n      Partition Name: vbmeta_system\n",
            "    Hashtree descriptor:\n      Partition Name: system\n",
        ]
        report = make_report(self.root / "odin", self.staged, avbtool="avbtool")
        self.assertTrue(report["vbmeta_system_chain_declared_in_bl"])
        self.assertEqual(report["direct_system_hash_or_hashtree_overlap"], ["system"])
        self.assertFalse(report["flashable"])
        self.assertEqual(report["status"], "BLOCKED_FOR_FLASH_UNVERIFIED_HYBRID_BOOT")
        self.assertFalse(report["stock_bl_vbmeta"]["header"]["signature_verified"])


if __name__ == "__main__":
    unittest.main()
