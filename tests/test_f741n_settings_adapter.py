"""Tests for safe Fold5->Fold6 resource-locale patch adaptation."""
import sys
from pathlib import Path
import tempfile
import unittest

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
