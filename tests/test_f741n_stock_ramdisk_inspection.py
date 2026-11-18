"""Offline synthetic tests for safe F741N init/vendor ramdisk content inspection."""
import gzip
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from inspect_b6q_stock_ramdisks import (
    analyze_entries, decompress_ramdisk, inspect_stock_ramdisks,
    parse_cpio, ramdisk_payload, MAX_COMPRESSED,
)


def cpio_newc(entries):
    data = bytearray()
    for name, payload in [*entries, ("TRAILER!!!", b"")]:
        fields = [1, 0o100644, 0, 0, 1, 0, len(payload), 0, 0, 0, 0,
                  len(name.encode()) + 1, 0]
        data.extend(b"070701" + b"".join(f"{value:08x}".encode()
                                         for value in fields))
        data.extend(name.encode() + b"\x00")
        data.extend(bytes((-len(data)) % 4))
        data.extend(payload)
        data.extend(bytes((-len(data)) % 4))
    return bytes(data)


def boot_v4(gzram):
    data = bytearray(4096 + ((len(gzram) + 4095) // 4096) * 4096)
    data[:8] = b"ANDROID!"
    struct.pack_into("<I", data, 12, len(gzram))
    struct.pack_into("<I", data, 20, 1584)
    struct.pack_into("<I", data, 40, 4)
    data[4096:4096 + len(gzram)] = gzram
    return bytes(data)


def vendor_v4(gzram):
    # 4096 header, padded ramdisk, empty DTB, table at next 4096 boundary
    padded = ((len(gzram) + 4095) // 4096) * 4096
    table_start = 4096 + padded
    data = bytearray(table_start + 4096)
    data[:8] = b"VNDRBOOT"
    struct.pack_into("<I", data, 8, 4)
    struct.pack_into("<I", data, 12, 4096)
    struct.pack_into("<I", data, 24, len(gzram))
    struct.pack_into("<I", data, 2096, 2128)
    struct.pack_into("<I", data, 2100, 0)
    struct.pack_into("<I", data, 2112, 108)
    struct.pack_into("<I", data, 2116, 1)
    struct.pack_into("<I", data, 2120, 108)
    struct.pack_into("<I", data, 2124, 0)
    data[4096:4096 + len(gzram)] = gzram
    struct.pack_into("<III", data, table_start, len(gzram), 0, 1)
    data[table_start + 12:table_start + 20] = b"platform"
    return bytes(data)


class StockRamdiskTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        fstab = (b"system /system erofs ro wait,logical,first_stage_mount,avb\n"
                 b"product /product erofs ro wait,logical,first_stage_mount,avb\n")
        payload = cpio_newc([
            ("first_stage_ramdisk/fstab.qcom", fstab),
            ("init.rc", b"on early-init\n"),
        ])
        self.compressed = gzip.compress(payload)
        (self.root / "init_boot.img").write_bytes(boot_v4(self.compressed))
        (self.root / "vendor_boot.img").write_bytes(vendor_v4(self.compressed))

    def test_parses_valid_cpio_and_fstab_flags(self):
        entries = parse_cpio(cpio_newc([("fstab.qcom",
            b"system /system erofs ro wait,logical,first_stage_mount,avb\n")]))
        result = analyze_entries(entries)
        self.assertEqual(result["entries"], 1)
        self.assertEqual(result["first_stage_fstab_dynamic_entries"][0]["mountpoint"],
                         "/system")
        self.assertTrue(result["first_stage_fstab_dynamic_entries"][0]["avb"])

    def test_safe_gzip_decompression(self):
        encoding, data = decompress_ramdisk(self.compressed)
        self.assertEqual(encoding, "GZIP")
        self.assertEqual(len(parse_cpio(data)), 2)

    @mock.patch("inspect_b6q_stock_ramdisks.verify_stock_images")
    def test_both_boot_ramdisks_scanned_but_never_flashable(self, verify):
        verify.return_value = [{"image": "boot.img"}, {"image": "init_boot.img"}]
        report = inspect_stock_ramdisks(self.root)
        self.assertEqual(len(report["ramdisks"]), 2)
        self.assertTrue(all(x["status"] == "CPIO_INSPECTED" for x in report["ramdisks"]))
        self.assertFalse(report["flashable"])
        self.assertFalse(report["bootable"])
        self.assertEqual(report["ramdisks"][1]["source"], "vendor_boot.img/fragment_0")

    def test_reject_cpio_missing_terminator(self):
        raw = bytearray(cpio_newc([("x", b"hi")]))
        raw[111] = ord("Q")
        with self.assertRaisesRegex(ValueError, "terminator"):
            parse_cpio(bytes(raw))

    def test_unknown_compression_is_not_a_false_success(self):
        encoding, data = decompress_ramdisk(b"\x00\x01UNKNOWN")
        self.assertEqual(encoding, "UNKNOWN_COMPRESSION")
        self.assertIsNone(data)

    def test_out_of_bounds_staged_ramdisk_refused(self):
        with self.assertRaisesRegex(ValueError, "bounds"):
            ramdisk_payload(self.root / "init_boot.img", 0, MAX_COMPRESSED + 1)


if __name__ == "__main__":
    unittest.main()
