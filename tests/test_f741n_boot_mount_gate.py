"""Synthetic tests for F741N read-only boot-format, mount, and AVB precheck."""
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from audit_b6q_boot_mount_gate import (
    read_boot_header, read_vendor_boot_header, read_target_fstab, analyze, REQUIRED,
)


def synthetic_boot(version=4):
    data = bytearray(8192)
    data[:8] = b"ANDROID!"
    struct.pack_into("<II", data, 8, 0, 128)
    struct.pack_into("<I", data, 20, 1584 if version == 4 else 1580)
    struct.pack_into("<I", data, 40, version)
    return bytes(data)


def synthetic_vendor_boot():
    data = bytearray(16384)
    data[:8] = b"VNDRBOOT"
    struct.pack_into("<I", data, 8, 4)
    struct.pack_into("<I", data, 12, 4096)
    struct.pack_into("<I", data, 24, 100)
    struct.pack_into("<I", data, 2096, 2128)
    struct.pack_into("<I", data, 2100, 128)
    struct.pack_into("<I", data, 2112, 108)
    struct.pack_into("<I", data, 2116, 1)
    struct.pack_into("<I", data, 2120, 108)
    struct.pack_into("<I", data, 2124, 0)
    offset = 12288
    struct.pack_into("<III", data, offset, 100, 0, 1)
    data[offset + 12:offset + 20] = b"platform"
    return bytes(data)


class BootMountTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.stock = self.root / "stock"
        self.stock.mkdir()
        (self.stock / "boot.img").write_bytes(synthetic_boot())
        (self.stock / "init_boot.img").write_bytes(synthetic_boot())
        (self.stock / "vendor_boot.img").write_bytes(synthetic_vendor_boot())
        self.work = self.root / "work"
        (self.work / "vendor/etc").mkdir(parents=True)
        (self.work / "port-origin.json").write_text(json.dumps({
            "target": "SM-F741N", "donor": "SM-F956N",
        }))
        body = []
        for part in REQUIRED:
            body.append(
                f"{part} /{part} erofs ro wait,logical,first_stage_mount,avb\n"
            )
        self.fstab = self.work / "vendor/etc/fstab.qcom"
        self.fstab.write_text("".join(body))
        self.chain = self.root / "chain.json"
        self.chain.write_text(json.dumps({
            "model": "SM-F741N",
            "stock_bl_vbmeta": {"descriptors": [
                {"type": "hashtree", "partition": "system"},
                {"type": "hashtree", "partition": "product"},
                {"type": "hashtree", "partition": "system_ext"},
            ]},
        }))

    def test_android_v4_boot_header(self):
        self.assertEqual(read_boot_header(self.stock / "boot.img")["header_version"], 4)

    def test_vendor_boot_v4_fragment_table(self):
        header = read_vendor_boot_header(self.stock / "vendor_boot.img")
        self.assertEqual(header["vendor_ramdisk_fragments"][0]["name"], "platform")
        self.assertEqual(header["vendor_ramdisk_fragments"][0]["ramdisk_bytes"], 100)
        self.assertFalse(header["ramdisk_contents_inspected"])

    def test_fstab_has_seven_first_stage_mount_variants(self):
        f = read_target_fstab(self.work)
        self.assertTrue(f["all_seven_first_stage_logical_avb_variants_found"])
        self.assertEqual(set(f["partitions"]), set(REQUIRED))

    def test_missing_avb_is_not_a_mount_pass(self):
        self.fstab.write_text(self.fstab.read_text().replace(
            "system_ext /system_ext erofs ro wait,logical,first_stage_mount,avb",
            "system_ext /system_ext erofs ro wait,logical,first_stage_mount"))
        f = read_target_fstab(self.work)
        self.assertFalse(f["all_seven_first_stage_logical_avb_variants_found"])
        self.assertFalse(f["partitions"]["system_ext"]["first_stage_logical_avb_variant_found"])

    @mock.patch("audit_b6q_boot_mount_gate.verify_stock_images")
    def test_analysis_still_blocks_flash(self, verify):
        verify.return_value = [{"image": "boot.img"}, {"image": "init_boot.img"}]
        report = analyze(self.stock, self.work, self.chain)
        self.assertEqual(report["avb"]["changed_partition_overlap"],
                         ["product", "system", "system_ext"])
        self.assertFalse(report["flashable"])
        self.assertFalse(report["bootable"])
        self.assertEqual(report["stock_boot_image_hash_manifest_checked"], 2)

    @mock.patch("audit_b6q_boot_mount_gate.verify_stock_images")
    def test_missing_bl_report_is_unknown_not_pass(self, verify):
        verify.return_value = []
        self.chain.unlink()
        report = analyze(self.stock, self.work, self.chain)
        self.assertEqual(report["avb"]["state"], "UNKNOWN_NO_STOCK_BL_DESCRIPTOR_REPORT")
        self.assertFalse(report["flashable"])

    def test_reject_corrupt_fragment_bounds(self):
        data = bytearray(synthetic_vendor_boot())
        struct.pack_into("<I", data, 12288 + 4, 150)
        (self.stock / "vendor_boot.img").write_bytes(data)
        with self.assertRaisesRegex(ValueError, "Invalid F741N vendor ramdisk"):
            read_vendor_boot_header(self.stock / "vendor_boot.img")

    def test_reject_wrong_model(self):
        (self.work / "port-origin.json").write_text(json.dumps({
            "target": "SM-F731N", "donor": "SM-F956N",
        }))
        with self.assertRaisesRegex(ValueError, "Unexpected hybrid"):
            analyze(self.stock, self.work, self.chain)


if __name__ == "__main__":
    unittest.main()
