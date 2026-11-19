"""Synthetic tests of device-specific F741N source building and staging."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from build_b6q_ksu_kernel import assert_source_is_matching, stage_compiled, build_source
from package_b6q_ksu_kernel import REQUIRED_CONFIG


class F741NKernelSourceTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.source = self.root / "Samsung-F741N-source"
        (self.source / "kernel_platform").mkdir(parents=True)
        self.script = self.source / "build_kernel_GKI.sh"
        self.script.write_text(
            "#!/bin/bash\n"
            "BUILD_TARGET=b6q_kor_openx\n"
            "export BUILD_NUMBER=F741NKSS2BYGB\n"
            "CHIPSET_NAME=pineapple\n"
        )
        self.build = self.source / "out/msm-pineapple-pineapple-gki"
        (self.build / "dist").mkdir(parents=True)
        (self.build / "gki_kernel/common").mkdir(parents=True)
        data = bytearray(8192)
        data[0x38:0x3c] = b"ARMd"
        (self.build / "dist/Image").write_bytes(data)
        (self.build / "dist/kernel.release").write_text(
            "6.1.99-android14-11-12345678-abF741NKSS2BYGB\n"
        )
        (self.build / "gki_kernel/common/.config").write_text(
            "\n".join(REQUIRED_CONFIG) + "\n"
        )

    def test_matching_source_does_not_need_root_to_inspect(self):
        info = assert_source_is_matching(self.source)
        self.assertEqual(info["target"], "b6q_kor_openx")
        self.assertEqual(info["build"], "F741NKSS2BYGB")

    def test_stages_actual_compiled_image_with_manifest(self):
        output = self.root / "out-artifacts"
        info = stage_compiled(self.source, output)
        self.assertEqual(info["model"], "SM-F741N")
        self.assertTrue((output / "Image").is_file())
        self.assertTrue((output / ".config").is_file())
        self.assertTrue((output / "f741n-build-origin.json").is_file())
        self.assertFalse(info["module_abi_verified"])
        self.assertFalse(info["boot_tested"])
        with self.assertRaises(FileExistsError):
            stage_compiled(self.source, output)

    def test_refuses_the_flip5_source_model(self):
        self.script.write_text(
            "BUILD_TARGET=b5q_kor_openx\n"
            "BUILD_NUMBER=F741NKSS2BYGB\n"
            "CHIPSET_NAME=pineapple\n"
        )
        with self.assertRaisesRegex(ValueError, "b6q"):
            assert_source_is_matching(self.source)

    def test_refuses_f741b_ui8_source_even_if_same_soc(self):
        self.script.write_text(
            "BUILD_TARGET=b6q_eur_openx\n"
            "BUILD_NUMBER=F741BXXU2CYI6\n"
            "CHIPSET_NAME=pineapple\n"
        )
        with self.assertRaisesRegex(ValueError, "does not match"):
            assert_source_is_matching(self.source)

    def test_refuses_unrooted_kconfig(self):
        (self.build / "gki_kernel/common/.config").write_text("CONFIG_ARM64=y\n")
        with self.assertRaisesRegex(ValueError, "not built with KernelSU"):
            stage_compiled(self.source, self.root / "missing-root")

    def test_fails_on_missing_kernel_image(self):
        (self.build / "dist/Image").unlink()
        with self.assertRaisesRegex(ValueError, "exactly one"):
            stage_compiled(self.source, self.root / "no-kernel")

    @mock.patch("build_b6q_ksu_kernel.subprocess.run")
    def test_executes_only_explicit_matching_b6q_build(self, execute):
        execute.return_value = subprocess.CompletedProcess([], 0, "rev\n", "")
        result = build_source(self.source, run_build=True)
        self.assertEqual(result["target"], "b6q_kor_openx")
        self.assertIn(["bash", "./build_kernel_GKI.sh"],
                      [x.args[0] for x in execute.call_args_list])
        self.assertTrue(any(x.kwargs.get("cwd") == self.source
                            for x in execute.call_args_list))

    def test_refuses_symlinked_build_script(self):
        self.script.unlink()
        self.script.symlink_to(self.root / "unknown-remote")
        with self.assertRaisesRegex(ValueError, "Expected Samsung source"):
            assert_source_is_matching(self.source)


if __name__ == "__main__":
    unittest.main()
