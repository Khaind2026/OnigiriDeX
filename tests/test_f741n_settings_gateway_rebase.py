"""Tests for semantic rebase of Flip5 SettingsGateway fragment list on Fold6."""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from rebase_b6q_settings_gateway import GATEWAY, rebase

GATEWAY_PATCH = (
    "From: upstream\n"
    "Subject: [PATCH] add settings\n\n"
    f"diff --git a/{GATEWAY} b/{GATEWAY}\n"
    f"--- a/{GATEWAY}\n"
    f"+++ b/{GATEWAY}\n"
    "@@ -4,4 +4,6 @@\n"
    '     const-string v139, "com.samsung.android.fast.ui.MainActivity"\n'
    " \n"
    '+    const-string v140, "moe.foss.onigiri.OnigiriSettingsFragment"\n'
    '+\n'
    "-    filled-new-array/range {v1 .. v139}, [Ljava/lang/String;\n"
    "+    filled-new-array/range {v1 .. v140}, [Ljava/lang/String;\n"
    " \n"
    "     move-result-object v0\n"
    "diff --git a/res/values/strings.xml b/res/values/strings.xml\n"
    "--- a/res/values/strings.xml\n"
    "+++ b/res/values/strings.xml\n"
    "@@ -1 +1 @@\n"
    "-old\n+new\n"
)


def gateway_source(last=141, registers=None, preused=False):
    data = (
        ".class public Lcom/android/settings/core/gateway/SettingsGateway;\n"
        ".super Ljava/lang/Object;\n"
        ".method static constructor <clinit>()V\n"
        f"    .registers {registers or last+1}\n"
        '    const-string v136, "com.samsung.android.fast.ui.MainActivity"\n'
        f'    const-string v{last}, "com.samsung.android.settings.KnoxFeature"\n'
        + (f"    move-object v{last+1}, v0\n" if preused else "")
        + f"    filled-new-array/range {{v1 .. v{last}}}, [Ljava/lang/String;\n"
        + "    move-result-object v0\n"
        + "    return-void\n"
        + ".end method\n"
    )
    return data


class GatewayRebaseTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.decoded = self.root / "decoded"
        self.target = self.decoded / GATEWAY
        self.target.parent.mkdir(parents=True)

    def test_uses_actual_fold6_vregister_and_generates_git_applicable_diff(self):
        self.target.write_text(gateway_source(last=141))
        adapted, info = rebase(GATEWAY_PATCH, self.decoded)
        self.assertEqual(info["old_last_register"], 141)
        self.assertEqual(info["new_last_register"], 142)
        self.assertIn('const-string v142, "moe.foss.onigiri.OnigiriSettingsFragment"', adapted)
        self.assertIn("filled-new-array/range {v1 .. v142}", adapted)
        self.assertIn("diff --git a/res/values/strings.xml", adapted)
        # Only verify the SettingsGateway diff, since this fixture also
        # includes an intentionally independent strings.xml patch section.
        gateway_patch = adapted.split("diff --git a/res/values/strings.xml")[0]
        diff = self.root / "gateway.patch"
        diff.write_text(gateway_patch)
        completed = subprocess.run(
            ["git", "apply", "--check",
             f"--directory={self.decoded}", "--unsafe-paths", str(diff)],
            capture_output=True, text=True, cwd=self.root
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(self.target.read_text(), gateway_source(last=141))

    def test_two_arrays_select_second_after_samsung_anchor(self):
        source = gateway_source(last=141).replace(
            '    const-string v136, "com.samsung.android.fast.ui.MainActivity"\n',
            '    const-string v12, "unrelated.Array"\n'
            '    filled-new-array/range {v1 .. v12}, [Ljava/lang/String;\n'
            '    move-result-object v0\n'
            '    const-string v136, "com.samsung.android.fast.ui.MainActivity"\n'
        )
        self.target.write_text(source)
        adapted, info = rebase(GATEWAY_PATCH, self.decoded)
        self.assertEqual(info["old_last_register"], 141)
        self.assertIn("+    filled-new-array/range {v1 .. v142}", adapted)
        self.assertNotIn("-    filled-new-array/range {v1 .. v12}", adapted)
        patch_path = self.root / "gateway.patch"
        patch_path.write_text(adapted.split("diff --git a/res/values/strings.xml")[0])
        checked = subprocess.run(
            ["git", "apply", "--check", f"--directory={self.decoded}",
             "--unsafe-paths", str(patch_path)],
            cwd=self.root, capture_output=True, text=True
        )
        self.assertEqual(checked.returncode, 0, checked.stderr)
        self.assertEqual(self.target.read_text(), source)

    def test_duplicate_array_text_before_anchor_is_preserved(self):
        source = gateway_source(last=141).replace(
            '    const-string v136, "com.samsung.android.fast.ui.MainActivity"\n',
            '    filled-new-array/range {v1 .. v141}, [Ljava/lang/String;\n'
            '    move-result-object v0\n'
            '    const-string v136, "com.samsung.android.fast.ui.MainActivity"\n'
        )
        self.target.write_text(source)
        adapted, info = rebase(GATEWAY_PATCH, self.decoded)
        self.assertEqual(info["new_last_register"], 142)
        self.assertEqual(adapted.count("-    filled-new-array/range {v1 .. v141}"), 1)
        self.assertEqual(adapted.count("+    filled-new-array/range {v1 .. v142}"), 1)

    def test_fold6_v140_can_be_initialized_by_sget_object(self):
        # Real F956N lists v1..v140 but register v140 is not assigned
        # by const-string. The original stock array is left untouched,
        # and the port only introduces new, unused v141.
        source = gateway_source(last=140).replace(
            '    const-string v140, "com.samsung.android.settings.KnoxFeature"\n',
            '    sget-object v140, Lcom/samsung/android/settings/Gateway;->LAST:Ljava/lang/String;\n'
        )
        self.target.write_text(source)
        updated, info = rebase(GATEWAY_PATCH, self.decoded)
        self.assertEqual(info["old_last_register"], 140)
        self.assertEqual(info["new_last_register"], 141)
        self.assertIn('+    const-string v141, "moe.foss.onigiri.OnigiriSettingsFragment"', updated)
        self.assertIn("+    filled-new-array/range {v1 .. v141}", updated)
        self.assertNotIn("-    sget-object v140", updated)
        patch_path = self.root / "gateway-sget.patch"
        patch_path.write_text(updated.split("diff --git a/res/values/strings.xml")[0])
        checked = subprocess.run(
            ["git", "apply", "--check", f"--directory={self.decoded}",
             "--unsafe-paths", str(patch_path)],
            cwd=self.root, capture_output=True, text=True,
        )
        self.assertEqual(checked.returncode, 0, checked.stderr)
        self.assertEqual(self.target.read_text(), source)

    def test_last_register_initialized_before_samsung_anchor(self):
        original = gateway_source(last=141)
        original = original.replace(
            '    const-string v136, "com.samsung.android.fast.ui.MainActivity"\n'
            '    const-string v141, "com.samsung.android.settings.KnoxFeature"\n',
            '    const-string v141, "com.samsung.android.settings.KnoxFeature"\n'
            '    const-string v136, "com.samsung.android.fast.ui.MainActivity"\n'
        )
        self.target.write_text(original)
        updated, info = rebase(GATEWAY_PATCH, self.decoded)
        self.assertEqual(info["old_last_register"], 141)
        self.assertIn("+    filled-new-array/range {v1 .. v142}", updated)

    def test_refuses_ambiguous_duplicate_anchor(self):
        source = gateway_source(last=141).replace(
            '    const-string v136, "com.samsung.android.fast.ui.MainActivity"\n',
            '    const-string v130, "com.samsung.android.fast.ui.MainActivity"\n'
            '    const-string v136, "com.samsung.android.fast.ui.MainActivity"\n'
        )
        self.target.write_text(source)
        with self.assertRaisesRegex(ValueError, "one precise Samsung MainActivity"):
            rebase(GATEWAY_PATCH, self.decoded)

    def test_refuses_array_excluding_anchor_register(self):
        source = gateway_source(last=141).replace(
            "filled-new-array/range {v1 .. v141}",
            "filled-new-array/range {v1 .. v80}"
        )
        self.target.write_text(source)
        with self.assertRaisesRegex(ValueError, "outside candidate"):
            rebase(GATEWAY_PATCH, self.decoded)

    def test_bumps_register_allocation_when_required(self):
        self.target.write_text(gateway_source(last=141, registers=142))
        updated, info = rebase(GATEWAY_PATCH, self.decoded)
        self.assertEqual(info["registers_declared_after"], 143)
        self.assertIn("+    .registers 143", updated)

    def test_refuses_to_reuse_register_that_is_active(self):
        self.target.write_text(gateway_source(last=141, preused=True))
        with self.assertRaisesRegex(ValueError, "already used"):
            rebase(GATEWAY_PATCH, self.decoded)

    def test_refuses_missing_target_anchor(self):
        self.target.write_text(gateway_source().replace(
            "com.samsung.android.fast.ui.MainActivity", "unrelated"))
        with self.assertRaisesRegex(ValueError, "Expected one static"):
            rebase(GATEWAY_PATCH, self.decoded)

    def test_refuses_nonstatic_or_ambiguous_target(self):
        self.target.write_text(
            gateway_source().replace(
                ".method static constructor <clinit>()V",
                ".method public instanceMethod()V"
            ))
        with self.assertRaisesRegex(ValueError, "static zero-argument"):
            rebase(GATEWAY_PATCH, self.decoded)

    def test_original_patch_belongs_to_known_layout(self):
        self.target.write_text(gateway_source())
        with self.assertRaisesRegex(ValueError, "Unexpected upstream"):
            rebase(GATEWAY_PATCH.replace("v140},", "v155},"), self.decoded)


if __name__ == "__main__":
    unittest.main()
