"""Offline tests for DuyKhaiDeX b6q image extraction guards and sparse decoding."""
import io
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from extract_b6q_images import decode_image_to_raw, preflight


def sparse_fixture():
    raw = b"A" * 4096
    header = struct.pack("<IHHHHIIII", 0xED26FF3A, 1, 0, 28, 12, 4096, 3, 3, 0)
    parts = [
        struct.pack("<HHII", 0xCAC1, 0, 1, 12 + 4096) + raw,
        struct.pack("<HHII", 0xCAC2, 0, 1, 16) + b"\x11\x22\x33\x44",
        struct.pack("<HHII", 0xCAC3, 0, 1, 12),
    ]
    return header + b"".join(parts)


class B6qExtractionTests(unittest.TestCase):
    def test_streaming_sparse_expansion(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "super.raw.img"
            with output.open("wb") as stream:
                size, sparse = decode_image_to_raw(io.BytesIO(sparse_fixture()), stream, 12288)
            self.assertTrue(sparse)
            self.assertEqual(size, 12288)
            result = output.read_bytes()
            self.assertEqual(result[:4096], b"A" * 4096)
            self.assertEqual(result[4096:8192], b"\x11\x22\x33\x44" * 1024)
            self.assertEqual(result[8192:], bytes(4096))

    def test_raw_image_stream(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "raw.img"
            with output.open("wb") as stream:
                size, sparse = decode_image_to_raw(io.BytesIO(b"Z" * 4096), stream, 4096)
            self.assertFalse(sparse)
            self.assertEqual(size, 4096)
            self.assertEqual(output.read_bytes(), b"Z" * 4096)

    def test_malformed_chunk_rejected(self):
        payload = sparse_fixture().replace(
            struct.pack("<HHII", 0xCAC2, 0, 1, 16),
            struct.pack("<HHII", 0xCAC2, 0, 1, 18)
        )
        with tempfile.TemporaryDirectory() as tmp:
            with (Path(tmp) / "raw.img").open("wb") as out:
                with self.assertRaisesRegex(ValueError, "Invalid FILL"):
                    decode_image_to_raw(io.BytesIO(payload), out, 12288)

    @mock.patch("extract_b6q_images.shutil.which", return_value="/fake/tool")
    def test_preflight_works_with_not_yet_created_nested_parent(self, _which):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            odin = root / "out/odin/SM-F741N_SKC"
            odin.mkdir(parents=True)
            (odin / "AP_F741NKSS2BYGB_fake.tar.md5").touch()
            models = []
            parts = {
                "system": "SM-F956N", "product": "SM-F956N",
                "system_ext": "SM-F956N", "vendor": "SM-F741N",
                "odm": "SM-F741N", "system_dlkm": "SM-F741N",
                "vendor_dlkm": "SM-F741N",
            }
            for model in ("SM-F741N", "SM-F956N"):
                models.append({
                    "model": model, "checksums_valid": True, "header_version": "10.0",
                    "role": "hardware_target" if model == "SM-F741N" else "system_donor",
                    "groups": [{"name": "qti_dynamic_partitions", "maximum_bytes": 16 * 1024**3}],
                    "block_devices": [{"name": "super", "size_bytes": 14 * 1024**3}],
                    "partitions": [
                        {"name": name, "group": "qti_dynamic_partitions", "bytes": 1024**2}
                        for name in parts
                    ],
                })
            metadata = root / "metadata.json"
            metadata.write_text(json.dumps({"devices": models}))
            plan = root / "plan.json"
            plan.write_text(json.dumps({
                "status": "ANALYSIS_ONLY_NOT_FLASHABLE",
                "system_partition_sources": parts,
            }))
            destination = root / "out/b6q/extracted/SM-F741N"
            info = preflight(root, metadata, plan, "SM-F741N", destination)
            self.assertEqual(len(info["parts"]), 4)
            self.assertFalse(destination.exists())
            destination.mkdir(parents=True)
            with self.assertRaisesRegex(FileExistsError, "Refusing to overwrite"):
                preflight(root, metadata, plan, "SM-F741N", destination)


if __name__ == "__main__":
    unittest.main()
