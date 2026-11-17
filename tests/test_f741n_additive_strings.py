"""Test Fold6 safe string rebasing using real 0018, 0019, 0020 patches."""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock
import subprocess
import shutil

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from rebase_b6q_additive_strings import adapt, STRINGS

PATCH_DIR = (Path(__file__).resolve().parents[1] /
             "onigiri/mods/settings/smali/system/priv-app/SecSettings/SecSettings.apk")
NAMES = [
    "0018-Add-car-standby-toggle.patch",
    "0019-Add-DeX-zone-apps.patch",
    "0020-Make-car-standby-shutdown-time-adjustable.patch",
]


def initial_strings():
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<resources>\n'
        '    <string name="samsung_extra">Stock Fold6 content</string>\n'
        '    <string name="onigiri_dex_zones_grid">Grid</string>\n'
        '    <string name="onigiri_dex_zones_priority">Priority grid</string>\n'
        '    <string name="onigiri_autoboot_title">Power on when power connected</string>\n'
        '    <string name="onigiri_settings_category_title">Onigiri settings</string>\n'
        '</resources>\n'
    )


def only_strings(patch):
    at = patch.index("diff --git a/res/values/strings.xml b/res/values/strings.xml")
    next_section = patch.find("\ndiff --git ", at + 20)
    return patch[at:next_section if next_section != -1 else None].rstrip("\n") + "\n"


class AdditiveStringsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.decoded = self.base / "decoded"
        self.path = self.decoded / STRINGS
        self.path.parent.mkdir(parents=True)
        self.path.write_text(initial_strings())

    def source_patch(self, number):
        return (PATCH_DIR / NAMES[number]).read_text()

    @unittest.skipUnless(shutil.which("git"), "git required")
    def test_all_three_original_settings_patches_apply_in_order(self):
        for i in range(3):
            upstream = self.source_patch(i)
            rebased, info = adapt(upstream, self.decoded)
            self.assertIn("diff --git a/res/values/strings.xml", rebased)
            if i == 0:
                self.assertEqual(info["added_keys"],
                                 ["onigiri_car_standby_title",
                                  "onigiri_car_standby_summary"])
            if i == 1:
                self.assertIn("onigiri_dex_zone_apps", info["added_keys"])
            if i == 2:
                self.assertEqual(info["replaced_keys"],
                                 ["onigiri_car_standby_summary"])
                self.assertEqual(info["added_keys"],
                                 ["onigiri_car_standby_hours_title"])
            patchfile = self.base / f"actual{i}.patch"
            patchfile.write_text(only_strings(rebased))
            before = self.path.read_text()
            check = subprocess.run(
                ["git", "apply", "--check", "--unsafe-paths",
                 f"--directory={self.decoded}", str(patchfile)],
                cwd=self.base, capture_output=True, text=True)
            self.assertEqual(check.returncode, 0, check.stderr)
            self.assertEqual(before, self.path.read_text())
            applied = subprocess.run(
                ["git", "apply", "--unsafe-paths",
                 f"--directory={self.decoded}", str(patchfile)],
                cwd=self.base, capture_output=True, text=True)
            self.assertEqual(applied.returncode, 0, applied.stderr)
        result = self.path.read_text()
        self.assertIn("onigiri_car_standby_hours_title", result)
        self.assertIn("onigiri_dex_zone_apps", result)
        self.assertIn("Shuts down below 10% or after the time below.", result)
        self.assertNotIn("Shuts down after 4 days or below 10%.", result)
        self.assertIn("Stock Fold6 content", result)

    def test_replaces_only_if_exact_previous_string_matches(self):
        self.path.write_text(initial_strings().replace(
            '</resources>',
            '    <string name="onigiri_car_standby_summary">Different!</string>\n</resources>'
        ))
        with self.assertRaisesRegex(ValueError, "old value differs"):
            adapt(self.source_patch(2), self.decoded)

    def test_refuses_partial_additive_patch_state(self):
        self.path.write_text(initial_strings().replace(
            '</resources>',
            '    <string name="onigiri_car_standby_title">Standby when unplugged</string>\n'
            '</resources>'
        ))
        with self.assertRaisesRegex(ValueError, "already present"):
            adapt(self.source_patch(0), self.decoded)

    def test_other_patch_sections_unmodified(self):
        p = self.source_patch(1)
        updated, _ = adapt(p, self.decoded)
        before = p.index("diff --git a/res/values/strings.xml")
        after = updated.index("diff --git a/res/values/strings.xml")
        self.assertEqual(p[:before], updated[:after])
        next_marker = "diff --git a/res/xml/onigiri_settings.xml"
        self.assertEqual(p[p.index(next_marker):], updated[updated.index(next_marker):])

    def test_reject_non_string_deletion(self):
        p = self.source_patch(0)
        p = p.replace(
            '+    <string name="onigiri_car_standby_title">Standby when unplugged</string>',
            '-    <integer name="some_number">4</integer>')
        with self.assertRaisesRegex(ValueError, "Non-string deletion"):
            adapt(p, self.decoded)


if __name__ == "__main__":
    unittest.main()
