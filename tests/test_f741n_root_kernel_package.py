"""F741N-only KernelSU/SUSFS boot repack fixture tests (no real firmware)."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from package_b6q_ksu_kernel import (
    source_provenance, package, OUT_NAME, REQUIRED_CONFIG,
)


class F741NRootKernelTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.build = self.root / "compiled-f741n"
        self.build.mkdir()
        payload = bytearray(8192)
        payload[0x38:0x3c] = b"ARMd"
        (self.build / "Image").write_bytes(payload)
        (self.build / ".config").write_text(
            "\n".join(REQUIRED_CONFIG) + "\n"
        )
        (self.build / "kernel.release").write_text(
            "6.1.99-android14-11-12345678-abF741NKSS2BYGB\n"
        )
        (self.build / "f741n-build-origin.json").write_text(json.dumps({
            "model": "SM-F741N", "firmware_build": "F741NKSS2BYGB",
            "device": "b6q", "platform": "sm8650",
            "source_is_samsung_f741n": True,
            "kernel_release": "6.1.99-android14-11-12345678-abF741NKSS2BYGB",
            "root_backend": "KernelSU+SUSFS",
            "source_revision": "test-f741n-specific",
        }))
        self.stock_dir = self.root / "stock"
        self.stock_dir.mkdir()
        self.stock = self.stock_dir / "boot.img"
        self.stock.write_bytes(b"ANDROID!" + bytes(16_376))
        self.out = self.root / "root-boot-output"

    def test_uses_f741n_kernel_build_artifacts(self):
        result = source_provenance(
            self.build, self.build / "Image", self.build / ".config",
            self.build / "kernel.release",
        )
        self.assertEqual(result["kernel_bytes"], 8192)
        self.assertTrue(result["kernel_release"].startswith("6.1.99-"))
        self.assertEqual(len(result["kernel_sha256"]), 64)

    def test_refuses_wrong_kernel_board(self):
        p = self.build / "f741n-build-origin.json"
        data = json.loads(p.read_text())
        data["device"] = "b5q"
        p.write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError, "provenance mismatch: device"):
            source_provenance(self.build, self.build / "Image",
                              self.build / ".config", self.build / "kernel.release")

    def test_refuses_unsigned_or_unknown_donor_source(self):
        p = self.build / "f741n-build-origin.json"
        data = json.loads(p.read_text())
        data["source_is_samsung_f741n"] = False
        p.write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError, "not confirmed"):
            source_provenance(self.build, self.build / "Image",
                              self.build / ".config", self.build / "kernel.release")

    def test_refuses_wrong_kernelsu_susfs_config(self):
        (self.build / ".config").write_text("CONFIG_ARM64=y\nCONFIG_KSU=y\n")
        with self.assertRaisesRegex(ValueError, "CONFIG_KSU_SUSFS=y"):
            source_provenance(self.build, self.build / "Image",
                              self.build / ".config", self.build / "kernel.release")

    def test_refuses_non_arm64_image(self):
        (self.build / "Image").write_bytes(bytes(8192))
        with self.assertRaisesRegex(ValueError, "ARM64"):
            source_provenance(self.build, self.build / "Image",
                              self.build / ".config", self.build / "kernel.release")

    def test_refuses_b5q_kernel_release(self):
        (self.build / "kernel.release").write_text("5.15.153-android13-8\n")
        with self.assertRaisesRegex(ValueError, "Android14 GKI 6.1"):
            source_provenance(self.build, self.build / "Image",
                              self.build / ".config", self.build / "kernel.release")

    @mock.patch("package_b6q_ksu_kernel.shutil.which", return_value="/mock/magiskboot")
    @mock.patch("package_b6q_ksu_kernel.read_boot_header",
                return_value={"header_version": 4})
    @mock.patch("package_b6q_ksu_kernel.verify_stock_boot")
    @mock.patch("package_b6q_ksu_kernel.subprocess.run")
    def test_repack_only_f741n_stock_boot_and_never_flash(
            self, execute, verify_boot, _hdr, _which):
        original = hashlib.sha256(self.stock.read_bytes()).hexdigest()
        verify_boot.return_value = {
            "boot.img": {"path": self.stock, "sha256": original}
        }

        def fake_run(command, **kwargs):
            work = kwargs["cwd"]
            if "unpack" in command:
                (work / "kernel").write_bytes(b"ORIGINAL")
            elif "repack" in command:
                (work / "new-boot.img").write_bytes(
                    b"ANDROID!" + bytes(16_375) + b"X"
                )
            return subprocess.CompletedProcess(command, 0, "", "")

        execute.side_effect = fake_run
        report = package(self.stock_dir, self.build, self.out, "/mock/magiskboot")
        self.assertTrue((self.out / OUT_NAME).is_file())
        self.assertEqual(report["stock_boot_sha256"], original)
        self.assertTrue(report["root_boot_sha256"] != original)
        self.assertFalse(report["flashable"])
        self.assertFalse(report["bootable"])
        self.assertFalse(report["avb_trust_verified"])
        self.assertFalse(report["vendor_boot_replaced"])
        self.assertEqual(execute.call_count, 2)
        repack_args = execute.call_args.kwargs
        self.assertEqual(repack_args["env"]["PATCHVBMETAFLAG"], "false")
        self.assertTrue(self.stock.is_file())
        with self.assertRaises(FileExistsError):
            package(self.stock_dir, self.build, self.out, "/mock/magiskboot")


if __name__ == "__main__":
    unittest.main()
