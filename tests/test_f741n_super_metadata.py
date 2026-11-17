"""Self-contained tests for streaming LP metadata parser; no firmware needed."""
import hashlib
import io
from pathlib import Path
import struct
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from inspect_super_f741n_f956n import image_prefix, logical_partitions


def name36(value):
    raw = value.encode("ascii")
    return raw + bytes(36 - len(raw))


def synthetic_super():
    raw = bytearray(16384)
    geometry = bytearray(52)
    struct.pack_into("<II", geometry, 0, 0x616C4467, 52)
    struct.pack_into("<III", geometry, 40, 65536, 2, 4096)
    geometry[8:40] = hashlib.sha256(geometry).digest()
    raw[4096:4096 + 52] = geometry
    raw[8192:8192 + 52] = geometry

    rows = [
        name36("system_a") + struct.pack("<IIII", 0, 0, 1, 0),
        struct.pack("<QIQI", 16, 0, 0, 0),
        name36("group_a") + struct.pack("<IQ", 0, 1024 * 1024),
        struct.pack("<QIIQ", 2048, 4096, 0, 64 * 1024 * 1024)
        + name36("super") + struct.pack("<I", 0),
    ]
    table = b"".join(rows)
    hdr = bytearray(128)
    struct.pack_into("<IHHI", hdr, 0, 0x414C5030, 10, 2, 128)
    struct.pack_into("<I", hdr, 44, len(table))
    hdr[48:80] = hashlib.sha256(table).digest()
    offset = 0
    for index, row in enumerate(rows):
        struct.pack_into("<III", hdr, 80 + 12 * index, offset, 1, len(row))
        offset += len(row)
    hdr[12:44] = hashlib.sha256(hdr).digest()
    raw[12288:12288 + 128] = hdr
    raw[12288 + 128:12288 + 128 + len(table)] = table
    return bytes(raw)


class SuperParserTests(unittest.TestCase):
    def test_lp_metadata_checksums_and_partitions(self):
        data = synthetic_super()
        parsed = logical_partitions(data)
        self.assertTrue(parsed["checksums_valid"])
        self.assertEqual(parsed["header_version"], "10.2")
        self.assertEqual(parsed["geometry"]["metadata_slots"], 2)
        self.assertEqual(parsed["groups"][0]["name"], "group_a")
        self.assertEqual(parsed["partitions"][0]["name"], "system_a")
        self.assertEqual(parsed["partitions"][0]["bytes"], 8192)
        self.assertEqual(parsed["block_devices"][0]["name"], "super")

    def test_raw_prefix(self):
        data = synthetic_super()
        prefix, sparse = image_prefix(io.BytesIO(data), limit=32768)
        self.assertFalse(sparse)
        self.assertEqual(prefix, data)
        self.assertTrue(logical_partitions(prefix)["checksums_valid"])

    def test_android_sparse_prefix(self):
        raw = synthetic_super()
        header = struct.pack("<IHHHHIIII", 0xED26FF3A, 1, 0, 28, 12, 4096, 4, 1, 0)
        chunk = struct.pack("<HHII", 0xCAC1, 0, 4, 12 + len(raw))
        preview, sparse = image_prefix(io.BytesIO(header + chunk + raw), limit=32768)
        self.assertTrue(sparse)
        self.assertEqual(preview, raw)
        self.assertEqual(logical_partitions(preview)["partitions"][0]["name"], "system_a")

    def test_reject_incorrect_major_version_even_with_valid_checksum(self):
        raw = bytearray(synthetic_super())
        pos = 12288
        struct.pack_into("<H", raw, pos + 4, 2)
        header = bytearray(raw[pos:pos + 128])
        header[12:44] = bytes(32)
        raw[pos + 12:pos + 44] = hashlib.sha256(header).digest()
        with self.assertRaisesRegex(ValueError, "major 10"):
            logical_partitions(raw)

    def test_corrupt_metadata_checksum_rejected(self):
        raw = bytearray(synthetic_super())
        raw[12288 + 128 + 5] ^= 1
        with self.assertRaisesRegex(ValueError, "table SHA256"):
            logical_partitions(raw)

    def test_invalid_sparse_chunk_rejected(self):
        header = struct.pack("<IHHHHIIII", 0xED26FF3A, 1, 0, 28, 12, 4096, 4, 1, 0)
        chunk = struct.pack("<HHII", 0xCAC1, 0, 4, 100)
        with self.assertRaisesRegex(ValueError, "Invalid sparse RAW"):
            image_prefix(io.BytesIO(header + chunk), limit=32768)


if __name__ == "__main__":
    unittest.main()
