"""Tests for safe Fold5->Fold6 resource-locale patch adaptation."""
import sys
from pathlib import Path
import tempfile
import unittest
import subprocess
import shutil

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from adapt_b6q_settings_patches import adapt_patch, adapt_tree

HEADER = "From: Onigiri\nSubject: [PATCH] Test source patch\n\n"


def modify(path, before, after):
    return (
        f"diff --git a/{path} b/{path}\n"
        f"--- a/{path}\n+++ b/{path}\n"
        "@@ -1 +1 @@\n"
        f"-{before}\n+{after}\n"
    )


class SettingsAdapterTests(unittest.TestCase):
    def test_only_missing_optional_locale_sections_are_filtered(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "res/values").mkdir(parents=True)
            (root / "res/values/strings.xml").write_text("<string>before</string>")
            (root / "smali").mkdir()
            (root / "smali/Important.smali").write_text("before")
            patch = HEADER
            patch += modify("res/values/strings.xml", "before", "after")
            patch += modify("res/values-en-rCA/strings.xml", "No SIM", "Branded")
            patch += modify("smali/Important.smali", "before", "after")
            updated, skipped = adapt_patch(patch, root)
            self.assertEqual(skipped, ["res/values-en-rCA/strings.xml"])
            self.assertIn("diff --git a/smali/Important.smali", updated)
            self.assertIn("diff --git a/res/values/strings.xml", updated)
            self.assertNotIn("res/values-en-rCA/strings.xml", updated)
            self.assertEqual((root / "smali/Important.smali").read_text(), "before")

    def test_existing_locale_is_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "res/values-en-rCA").mkdir(parents=True)
            (root / "res/values-en-rCA/strings.xml").write_text("No SIM")
            patch = HEADER + modify("res/values-en-rCA/strings.xml", "No SIM", "Branded")
            adapted, skipped = adapt_patch(patch, root)
            self.assertEqual(adapted, patch)
            self.assertFalse(skipped)

    def test_non_locale_missing_file_is_never_filtered(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            patch = HEADER + modify("smali/com/android/CarrierText.smali", "old", "new")
            self.assertEqual(adapt_patch(patch, root), (patch, []))


    def test_onigiri_new_file_header_with_extra_b_prefix_is_preserved(self):
        original = (
            "From: Onigiri\n"
            "diff --git a/b/res/drawable/onigiri_zone_grid.xml b/res/drawable/onigiri_zone_grid.xml\n"
            "new file mode 100644\n"
            "index 0000000..abc1234\n"
            "--- /dev/null\n"
            "+++ b/res/drawable/onigiri_zone_grid.xml\n"
            "@@ -0,0 +1 @@\n"
            "+<vector />\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            adapted, skipped = adapt_patch(original, Path(tmp))
        self.assertEqual(adapted, original)
        self.assertEqual(skipped, [])

    def test_original_0016_zone_layout_patch_is_accepted_unchanged(self):
        repo = Path(__file__).resolve().parents[1]
        original = (repo / "onigiri/mods/settings/smali/system/priv-app/"
                    "SecSettings/SecSettings.apk/0016-Add-DeX-zone-layouts.patch").read_text()
        with tempfile.TemporaryDirectory() as tmp:
            adapted, skipped = adapt_patch(original, Path(tmp))
        self.assertEqual(adapted, original)
        self.assertEqual(skipped, [])
        self.assertIn("onigiri_zone_columns.xml", adapted)
        self.assertIn("DexZonesPreferenceController.smali", adapted)

    def test_rename_is_still_refused_without_silent_patch_drop(self):
        patch = (
            "diff --git a/res/xml/old.xml b/res/xml/new.xml\n"
            "similarity index 100%\n"
            "rename from res/xml/old.xml\n"
            "rename to res/xml/new.xml\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, "Unsupported rename"):
                adapt_patch(patch, Path(tmp))

    def test_inconsistent_new_file_destination_is_rejected(self):
        patch = (
            "diff --git a/b/res/layout/a.xml b/res/layout/a.xml\n"
            "new file mode 100644\n"
            "--- /dev/null\n"
            "+++ b/res/layout/other.xml\n"
            "@@ -0,0 +1 @@\n+x\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, "Unsupported rename"):
                adapt_patch(patch, Path(tmp))

    @unittest.skipUnless(shutil.which("git"), "git required")
    def test_forward_and_reverse_git_checks_are_read_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            decoded = root / "decoded"
            (decoded / "res/values").mkdir(parents=True)
            original = decoded / "res/values/strings.xml"
            original.write_text("old\n")
            patch = root / "patch.diff"
            patch.write_text(HEADER + modify("res/values/strings.xml", "old", "new"))
            command = ["git", "apply", "--directory=" + str(decoded),
                       "--unsafe-paths", str(patch)]
            forward = subprocess.run(command[:2] + ["--check"] + command[2:],
                                     cwd=root, capture_output=True)
            self.assertEqual(forward.returncode, 0, forward.stderr.decode())
            self.assertEqual(original.read_text(), "old\n")
            applied = subprocess.run(command, cwd=root, capture_output=True)
            self.assertEqual(applied.returncode, 0, applied.stderr.decode())
            self.assertEqual(original.read_text(), "new\n")
            reversed_check = subprocess.run(
                command[:2] + ["--reverse", "--check"] + command[2:],
                cwd=root, capture_output=True)
            self.assertEqual(reversed_check.returncode, 0, reversed_check.stderr.decode())
            self.assertEqual(original.read_text(), "new\n")

    def test_new_translation_file_patch_is_never_filtered(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            patch = HEADER + (
                "diff --git a/res/values-en-rCA/strings.xml b/res/values-en-rCA/strings.xml\n"
                "new file mode 100644\n"
                "--- /dev/null\n+++ b/res/values-en-rCA/strings.xml\n"
                "@@ -0,0 +1 @@\n+new\n"
            )
            self.assertEqual(adapt_patch(patch, root), (patch, []))

    def test_cannot_discard_every_patch_section(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            patch = HEADER + modify("res/values-en-rCA/strings.xml", "a", "b")
            with self.assertRaisesRegex(ValueError, "No meaningful"):
                adapt_patch(patch, root)

    def test_adapt_tree_only_edits_disposable_copy(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            patches = base / "copies"
            target = patches / "system_ext/priv-app/SystemUI/SystemUI.apk"
            target.mkdir(parents=True)
            decoded = base / "decoded/system_ext/priv-app/SystemUI/SystemUI.apk"
            decoded.mkdir(parents=True)
            patch = HEADER + modify("res/values-en-rCA/strings.xml", "a", "b")
            patch += modify("smali/Important.smali", "a", "b")
            (target / "0001-test.patch").write_text(patch)
            changed = adapt_tree(patches, base / "decoded")
            self.assertEqual(len(changed), 1)
            self.assertNotIn("values-en-rCA", (target / "0001-test.patch").read_text())
            self.assertIn("smali/Important.smali", (target / "0001-test.patch").read_text())


if __name__ == "__main__":
    unittest.main()
