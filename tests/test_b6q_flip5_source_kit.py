"""Offline tests for reusing the real Flip5 ROM/DeX/KernelSU source on Flip6."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from stage_b6q_flip5_source_kit import (
    SOURCE_TREES, SOURCE_FILES, BINARY_REFERENCES, source_summary, stage,
)


class Flip5SourceKitTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name) / "repo"
        self.root.mkdir()
        for destination, source in SOURCE_TREES.items():
            folder = self.root / source
            folder.mkdir(parents=True)
            (folder / "module.prop").write_text("name=Original Flip5 module\n")
            if destination == "dex/smali":
                patch = folder / "services.jar.patch"
                patch.write_text("Fold5 DeX logic translated to matching class revision\n")
        for to, source in SOURCE_FILES.items():
            f = self.root / source
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text("# Verified source from b5q\n")
        for rel in BINARY_REFERENCES:
            f = self.root / rel
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_bytes(b"pinned local source asset")

    def test_reports_actual_b5q_source_and_f741n_target(self):
        report = source_summary(self.root)
        self.assertEqual(report["working_source"], "SM-F731N")
        self.assertEqual(report["working_dex_donor"], "SM-F946B")
        self.assertEqual(report["actual_framework_donor"], "SM-F956N")
        self.assertFalse(report["root_kernel_compiled"])
        self.assertFalse(report["flashable"])
        self.assertGreater(report["source_files"], 7)

    def test_stages_reusable_patches_and_root_logic_no_boot_images(self):
        output = self.root.parent / "kit"
        report = stage(self.root, output)
        self.assertTrue((output / "dex/smali/services.jar.patch").is_file())
        self.assertTrue((output / "root/essential/module.prop").is_file())
        self.assertTrue((output / "root/legacy-rootmods/module.prop").is_file())
        self.assertTrue((output / "kernel/b5q-package_kernel.sh").is_file())
        self.assertEqual(len(report["pinned_binary_references"]), 2)
        self.assertFalse(report["odin_ap_created"])
        self.assertFalse(any(p.suffix == ".img" for p in output.rglob("*")))
        data = json.loads((output / "port-kit.json").read_text())
        self.assertEqual(len(data["files"]), report["source_files"])

    def test_refuses_to_overwrite_source_kit(self):
        output = self.root.parent / "kit"
        stage(self.root, output)
        with self.assertRaises(FileExistsError):
            stage(self.root, output)

    def test_missing_required_kernel_root_source_fails_closed(self):
        (self.root / "scripts/package_kernel.sh").unlink()
        with self.assertRaisesRegex(ValueError, "Missing/invalid Flip5 source"):
            source_summary(self.root)

    def test_symlinks_cannot_be_copied_from_source(self):
        src = self.root / "target/b5q/patches/dex/native/reference.sh"
        src.symlink_to(self.root / "scripts/build_kernel.sh")
        with self.assertRaisesRegex(ValueError, "Symlink"):
            stage(self.root, self.root.parent / "kit")

    def test_missing_kernel_manager_reference_fails_closed(self):
        (self.root / BINARY_REFERENCES[0]).unlink()
        with self.assertRaisesRegex(ValueError, "Missing pinned"):
            stage(self.root, self.root.parent / "kit")


if __name__ == "__main__":
    unittest.main()
