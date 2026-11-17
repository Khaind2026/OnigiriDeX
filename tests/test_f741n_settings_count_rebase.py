"""Test exact Fold6 SettingsActivity count-loop rebase without firmware."""
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from rebase_b6q_settings_count import adapt, TARGET, FIELD


def stock_source(bound="0x8c", count_opcode="const/16", array="v1",
                 count="v2", index="v0"):
    return (
        ".class public Lcom/android/settings/SettingsActivity;\n"
        ".super Ljava/lang/Object;\n"
        ".method public onCreate()V\n"
        "    .locals 5\n"
        f"    sget-object {array}, {FIELD}\n"
        "\n"
        f"    {count_opcode} {count}, {bound}\n"
        "\n"
        f"    if-ge {index}, {count}, :cond_3\n"
        "\n"
        f"    aget-object {array}, {array}, {index}\n"
        "    return-void\n"
        ".end method\n"
    )


PATCH = (
    "Subject: [PATCH] Read the registered Samsung fragment allowlist length\n\n"
    f"diff --git a/{TARGET} b/{TARGET}\n"
    f"--- a/{TARGET}\n"
    f"+++ b/{TARGET}\n"
    "@@ -4,7 +4,7 @@\n"
    f"     sget-object v1, {FIELD}\n"
    " \n"
    "-    const/16 v2, 0x8b\n"
    "+    array-length v2, v1\n"
    " \n"
    "     if-ge v0, v2, :cond_3\n"
    " \n"
    "     aget-object v1, v1, v0\n"
)


class SettingsCountRebaseTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.decoded = self.root / "decoded"
        self.target = self.decoded / TARGET
        self.target.parent.mkdir(parents=True)

    def test_fold6_different_hardcoded_count(self):
        before = stock_source(bound="0x8c")
        self.target.write_text(before)
        modified, info = adapt(PATCH, self.decoded)
        self.assertIn("-    const/16 v2, 0x8c", modified)
        self.assertIn("+    array-length v2, v1", modified)
        self.assertEqual(info["source_line"], 6)
        self.assertEqual(self.target.read_text(), before)

    def test_unrelated_sections_stay_intact(self):
        self.target.write_text(stock_source())
        extra = ("diff --git a/res/values/strings.xml b/res/values/strings.xml\n"
                 "--- a/res/values/strings.xml\n"
                 "+++ b/res/values/strings.xml\n"
                 "@@ -1 +1 @@\n-old\n+new\n")
        changed, _ = adapt(PATCH + extra, self.decoded)
        self.assertTrue(changed.endswith(extra))

    def test_register_variation_is_preserved(self):
        self.target.write_text(stock_source(bound="0x8e", array="v3",
                                            count="v4", index="v7"))
        changed, info = adapt(PATCH, self.decoded)
        self.assertIn("+    array-length v4, v3", changed)
        self.assertEqual(info["count_register"], "v4")

    def test_wrong_branch_register_is_rejected(self):
        self.target.write_text(stock_source().replace(
            "if-ge v0, v2", "if-ge v0, v4"))
        with self.assertRaisesRegex(ValueError, "found 0"):
            adapt(PATCH, self.decoded)

    def test_multiple_matching_loops_refused(self):
        source = stock_source()
        self.target.write_text(source + source)
        with self.assertRaisesRegex(ValueError, "found 2"):
            adapt(PATCH, self.decoded)

    def test_no_hardcoded_count_is_not_modified(self):
        self.target.write_text(stock_source().replace(
            "const/16 v2, 0x8c", "array-length v2, v1"))
        with self.assertRaisesRegex(ValueError, "found 0"):
            adapt(PATCH, self.decoded)

    def test_unexpected_upstream_patch_refused(self):
        self.target.write_text(stock_source())
        with self.assertRaisesRegex(ValueError, "Unexpected upstream"):
            adapt(PATCH.replace("0x8b", "0x4c"), self.decoded)

    @unittest.skipUnless(shutil.which("git"), "git not installed")
    def test_generated_patch_passes_real_git_apply_dry_run(self):
        original = stock_source()
        self.target.write_text(original)
        rebased, _ = adapt(PATCH, self.decoded)
        patch = self.root / "tmp.patch"
        patch.write_text(rebased)
        result = subprocess.run(
            ["git", "apply", "--check",
             f"--directory={self.decoded}", "--unsafe-paths", str(patch)],
            cwd=self.root, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.target.read_text(), original)


if __name__ == "__main__":
    unittest.main()
