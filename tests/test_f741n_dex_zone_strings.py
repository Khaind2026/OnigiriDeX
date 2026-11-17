"""Unit tests for res/values/strings.xml rebase of DeX zone patch 0016."""
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from rebase_b6q_dex_zone_strings import rebase, EXPECTED_KEYS, STRINGS

PATCH_PATH = (
    Path(__file__).resolve().parents[1] /
    "onigiri/mods/settings/smali/system/priv-app/SecSettings/"
    "SecSettings.apk/0016-Add-DeX-zone-layouts.patch"
)


def fake_fold6_strings():
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<resources>\n'
        '    <string name="original_samsung_setting">Keep original Samsung</string>\n'
        '    <string name="onigiri_external_reconnect">Reconnect the external display</string>\n'
        '    <string name="extra_fold6_string">Fold6-specific option</string>\n'
        '    <string name="onigiri_autoboot_title">Power on when power connected</string>\n'
        '    <string name="onigiri_settings_category_title">Onigiri settings</string>\n'
        '</resources>\n'
    )


class DeXZoneStringRebaseTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.decoded = self.root / "decoded"
        self.path = self.decoded / STRINGS
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(fake_fold6_strings(), encoding="utf-8")
        self.patch = PATCH_PATH.read_text(encoding="utf-8")

    def test_original_0016_diff_rebased_from_actual_fold6_resource(self):
        before = self.path.read_bytes()
        updated, report = rebase(self.patch, self.decoded)
        self.assertEqual(tuple(report["inserted"]), EXPECTED_KEYS)
        self.assertIn("extra_fold6_string", updated)
        self.assertEqual(before, self.path.read_bytes())
        self.assertEqual(updated.count("diff --git a/res/values/strings.xml"), 1)
        # Every new DeX drawable/controller remains exactly the same patch
        # section as upstream. Only res/values/strings.xml is substituted.
        old_start = self.patch.index("diff --git a/res/values/strings.xml")
        new_start = updated.index("diff --git a/res/values/strings.xml")
        self.assertEqual(self.patch[:old_start], updated[:new_start])
        follow = "diff --git a/res/xml/onigiri_settings.xml"
        self.assertEqual(self.patch[self.patch.index(follow):],
                         updated[updated.index(follow):])

    @unittest.skipUnless(shutil.which("git"), "git required")
    def test_actual_generated_hunk_passes_git_apply_and_does_not_write(self):
        before = self.path.read_bytes()
        patched, _ = rebase(self.patch, self.decoded)
        begin = patched.index("diff --git a/res/values/strings.xml")
        end = patched.index("\ndiff --git ", begin + 15)
        standalone = self.root / "zone_strings.patch"
        standalone.write_text(patched[begin:end].rstrip("\n") + "\n")
        run = subprocess.run(
            ["git", "apply", "--check", "--unsafe-paths",
             f"--directory={self.decoded}", str(standalone)],
            cwd=self.root, capture_output=True, text=True
        )
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertEqual(before, self.path.read_bytes())
        apply = subprocess.run(
            ["git", "apply", "--unsafe-paths",
             f"--directory={self.decoded}", str(standalone)],
            cwd=self.root, capture_output=True, text=True
        )
        self.assertEqual(apply.returncode, 0, apply.stderr)
        result = self.path.read_text()
        self.assertLess(result.index('name="onigiri_dex_zones_title"'),
                        result.index('name="onigiri_autoboot_title"'))
        self.assertIn("Fold6-specific option", result)

    def test_duplicate_one_zone_key_is_fail_closed(self):
        self.path.write_text(
            fake_fold6_strings().replace(
                "</resources>",
                '    <string name="onigiri_dex_zones_off">Off</string>\n</resources>'
            )
        )
        with self.assertRaisesRegex(ValueError, "already exist"):
            rebase(self.patch, self.decoded)

    def test_missing_or_duplicate_anchor_rejected(self):
        self.path.write_text(fake_fold6_strings().replace(
            '    <string name="onigiri_autoboot_title">Power on when power connected</string>\n',
            ""
        ))
        with self.assertRaisesRegex(ValueError, "Cannot uniquely locate"):
            rebase(self.patch, self.decoded)

    def test_source_patch_must_be_additive_only(self):
        unsafe = self.patch.replace(
            '+    <string name="onigiri_dex_zones_title">Zones</string>',
            '-    <string name="onigiri_dex_zones_title">Zones</string>'
        )
        with self.assertRaisesRegex(ValueError, "replaces existing values"):
            rebase(unsafe, self.decoded)

    def test_missing_new_asset_section_does_not_change_source(self):
        broken = self.patch.replace(
            '+    <string name="onigiri_dex_zones_grid">Grid</string>',
            '+    <string name="onigiri_fake_setting">Grid</string>'
        )
        before = self.path.read_bytes()
        with self.assertRaisesRegex(ValueError, "Unexpected new zone string keys"):
            rebase(broken, self.decoded)
        self.assertEqual(before, self.path.read_bytes())


if __name__ == "__main__":
    unittest.main()
