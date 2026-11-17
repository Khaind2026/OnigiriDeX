"""Tests for read-only F741N AVB and branded-super compatibility report."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from analyze_b6q_avb import decode_vbmeta_header, inspect_super, produce, verify_stock_images
from stage_b6q_boot_chain import ASSETS, BUILD, TARGET


def vbmeta_fixture():
    data = bytearray(4160)
    data[:4] = b"AVB0"
    data[4:8] = (1).to_bytes(4, "big")
    data[8:12] = (2).to_bytes(4, "big")
    data[12:20] = (0).to_bytes(8, "big")
    data[20:28] = (3904).to_bytes(8, "big")
    data[28:32] = (0).to_bytes(4, "big")
    data[96:104] = (0).to_bytes(8, "big")
    data[104:112] = (0).to_bytes(8, "big")
    data[112:120] = (3).to_bytes(8, "big")
    data[120:124] = (0).to_bytes(4, "big")
    data[124:128] = (1).to_bytes(4, "big")
    data[128:138] = b"avbtool 1."
    return bytes(data)


class BootReadinessTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.stock = self.root / "stock"
        self.stock.mkdir()
        manifest = {
            "status": "F741N_STOCK_BOOT_IMAGES_NOT_FLASHABLE",
            "model": TARGET, "firmware_build": BUILD,
            "files": []
        }
        for name, (magic, required) in ASSETS.items():
            if name == "vbmeta.img":
                manifest["files"].append(
                    {"name": name, "present": False, "required": False})
                continue
            payload = (vbmeta_fixture() if name == "vbmeta_system.img"
                       else (magic or b"VM-STOCK") + bytes(1024))
            file = self.stock / name
            file.write_bytes(payload)
            manifest["files"].append({
                "name": name, "present": True, "required": required,
                "bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest(),
            })
        (self.stock / "manifest.json").write_text(json.dumps(manifest))
        self.super = self.root / "DuyKhaiDeX_F741N_BRANDED_SUPER_PREVIEW_NOT_FOR_FLASH.img"
        self.super.write_bytes(b"SPARSE_SUPER_TEST_ONLY")
        self.digest = hashlib.sha256(self.super.read_bytes()).hexdigest()
        Path(str(self.super) + ".sha256").write_text(f"{self.digest}  {self.super}\n")

    def test_readiness_never_grants_flash_approval(self):
        result = produce(self.stock, self.super)
        self.assertFalse(result["flashable"])
        self.assertEqual(result["status"], "BLOCKED_FOR_FLASH_UNVERIFIED_HYBRID_BOOT")
        self.assertEqual(len(result["stock_boot_images_verified"]), 7)
        self.assertEqual(result["vbmeta_system"]["header"]["rollback_index"], 3)
        self.assertFalse(result["vbmeta_system"]["header"]["signature_verified"])
        self.assertFalse(result["branded_super"]["sha256_recomputed"])
        self.assertTrue(any("Top-level" in b for b in result["blockers"]))

    def test_sha256_super_optional_full_verification(self):
        result = inspect_super(self.super, verify_large=True)
        self.assertTrue(result["sha256_recomputed"])
        self.super.write_bytes(b"changed")
        with self.assertRaisesRegex(ValueError, "checksum mismatch"):
            inspect_super(self.super, verify_large=True)

    def test_stock_corruption_is_detected(self):
        with (self.stock / "init_boot.img").open("ab") as fd:
            fd.write(b"modified")
        with self.assertRaisesRegex(ValueError, "Image size changed"):
            verify_stock_images(self.stock)

    def test_avb_descriptor_bounds_checked(self):
        header = bytearray(vbmeta_fixture())
        header[104:112] = (9000).to_bytes(8, "big")
        (self.stock / "vbmeta_system.img").write_bytes(header)
        with self.assertRaisesRegex(ValueError, "descriptors extend"):
            decode_vbmeta_header(self.stock / "vbmeta_system.img")

    def test_reject_other_model(self):
        manifest = self.stock / "manifest.json"
        content = json.loads(manifest.read_text())
        content["model"] = "SM-F956N"
        manifest.write_text(json.dumps(content))
        with self.assertRaisesRegex(ValueError, "Wrong stock device"):
            verify_stock_images(self.stock)

    def test_reject_missing_avb_image(self):
        (self.stock / "vbmeta_system.img").unlink()
        with self.assertRaisesRegex(ValueError, "Missing or linked"):
            verify_stock_images(self.stock)

    def test_reject_untrusted_super_checksum_filename(self):
        Path(str(self.super) + ".sha256").write_text(f"{self.digest}  /tmp/other.img\n")
        with self.assertRaisesRegex(ValueError, "manifest name mismatch"):
            inspect_super(self.super)


if __name__ == "__main__":
    unittest.main()
