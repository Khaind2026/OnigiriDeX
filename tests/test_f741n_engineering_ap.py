"""Synthetic Odin AP packaging checks; NO firmware, flash or device access."""
import hashlib
import json
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from build_b6q_engineering_ap import (
    ARCHIVE_NAME, STOCK_BOOT_ORDER, IMAGE_MAGIC, build, verify_input_super,
    verify_stock_boot,
)
from import_fw import verify_odin_package
from stage_b6q_boot_chain import ASSETS


class F741NEngineeringAPTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.repo = Path(temp.name) / "src"
        self.repo.mkdir()
        self.work = self.repo / "out/target/b6q/SM-F741N/work_dir"
        self.work.mkdir(parents=True)
        (self.work / ".b6q-prepared").write_text("ready")
        (self.work / ".b6q-dex-patched").write_text("done")
        (self.work / "port-origin.json").write_text(json.dumps({
            "target": "SM-F741N", "donor": "SM-F956N",
        }))
        self.boot = self.repo / "out/b6q/analysis/f741n-stock-boot-chain"
        self.boot.mkdir(parents=True)
        files = []
        for name in STOCK_BOOT_ORDER:
            magic, required = ASSETS[name]
            if name == "vbmeta_system.img":
                files.append({"name": name, "present": False, "required": required})
                continue
            file = self.boot / name
            data = (magic or b"TEST") + bytes(8192 - len(magic or b"TEST"))
            file.write_bytes(data)
            files.append({
                "name": name, "present": True, "required": required,
                "bytes": file.stat().st_size,
                "sha256": hashlib.sha256(data).hexdigest(),
            })
        (self.boot / "manifest.json").write_text(json.dumps({
            "status": "F741N_STOCK_BOOT_IMAGES_NOT_FLASHABLE",
            "model": "SM-F741N", "firmware_build": "F741NKSS2BYGB",
            "files": files,
        }))
        self.out = self.repo / "out/b6q/build"
        self.out.mkdir(parents=True)
        self.super = self.out / "DuyKhaiDeX_F741N_SUPER_PREVIEW_NOT_FOR_FLASH.img"
        self.super.write_bytes(bytes.fromhex("3aff26ed") + bytes(8192))
        self._checksum_super()

    def _checksum_super(self):
        self.super.with_suffix(".img.sha256").write_text(
            hashlib.sha256(self.super.read_bytes()).hexdigest() + "  " + self.super.name + "\n"
        )

    @staticmethod
    def fake_compress(executable, source, output):
        # Tests packaging only; never invents a genuinely valid LZ4 file.
        with output.open("wb") as file:
            file.write(b"STUB")
            file.write(source.read_bytes())

    def test_validates_actual_stock_boot_and_sparse_super_hashes(self):
        files = verify_stock_boot(self.boot)
        self.assertIn("init_boot.img", files)
        self.assertEqual(len(files), 6)
        self.assertEqual(verify_input_super(self.super)["bytes"], 8196)

    @mock.patch("build_b6q_engineering_ap.shutil.which", return_value="/usr/bin/lz4")
    @mock.patch("build_b6q_engineering_ap.compress_image")
    def test_packages_actual_odin_tar_md5_metadata_with_stock_boot(self, comp, which):
        comp.side_effect = self.fake_compress
        result = build(self.repo, self.out, auto_build=False)
        self.assertEqual(result["status"], "ENGINEERING_ODIN_AP_CREATED_NOT_FLASHABLE")
        self.assertFalse(result["flashable"])
        self.assertFalse(result["kernel_root_built"])
        self.assertFalse(result["dex_boot_verified"])
        output = self.out / ARCHIVE_NAME
        verify_odin_package(output)
        with tarfile.open(output, "r:") as stream:
            names = {m.name for m in stream}
        self.assertEqual(names, {
            "super.img.lz4", "boot.img.lz4", "init_boot.img.lz4",
            "vendor_boot.img.lz4", "dtbo.img.lz4", "recovery.img.lz4",
            "vbmeta.img.lz4",
        })
        self.assertTrue((self.out / (ARCHIVE_NAME + ".sha256")).is_file())
        with self.assertRaises(FileExistsError):
            build(self.repo, self.out, auto_build=False)

    def test_rejects_wrong_donor_source(self):
        (self.work / "port-origin.json").write_text(json.dumps({
            "target": "SM-F741N", "donor": "SM-F946B",
        }))
        with self.assertRaisesRegex(ValueError, "Unexpected"):
            build(self.repo, self.out, auto_build=False)

    def test_rejects_altered_super_without_checksum_update(self):
        with self.super.open("ab") as stream:
            stream.write(b"changed")
        with self.assertRaisesRegex(ValueError, "differs from its checksum"):
            verify_input_super(self.super)

    def test_rejects_fake_kernel_payload_hash(self):
        manifest = self.boot / "manifest.json"
        obj = json.loads(manifest.read_text())
        obj["files"][0]["sha256"] = "0" * 64
        manifest.write_text(json.dumps(obj))
        with self.assertRaisesRegex(ValueError, "hash mismatch"):
            verify_stock_boot(self.boot)

    def test_rejects_wrong_stock_firmware_build(self):
        manifest = self.boot / "manifest.json"
        obj = json.loads(manifest.read_text())
        obj["firmware_build"] = "F741NKSS3FOO"
        manifest.write_text(json.dumps(obj))
        with self.assertRaisesRegex(ValueError, "Wrong F741N"):
            verify_stock_boot(self.boot)

    def test_requires_dex_patched_flag(self):
        (self.work / ".b6q-dex-patched").unlink()
        with self.assertRaisesRegex(ValueError, "DeX F956N patches not completed"):
            build(self.repo, self.out, auto_build=False)


if __name__ == "__main__":
    unittest.main()
