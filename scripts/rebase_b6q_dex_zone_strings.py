#!/usr/bin/env python3
"""Rebase the *seven additive zone labels* from Onigiri patch 0016 on F956N.

The Fold5 diff uses old strings.xml line context, while the decoded Fold6
SecSettings resource list has different neighboring lines. Generate only the
res/values/strings.xml hunk against the actual decoded Fold6 file. Preserve
the upstream patch's icon, XML layout and controller smali sections byte for
byte. No changes to decoded APK, original source patch, or system images.
"""
import argparse
import difflib
from pathlib import Path
import re

STRINGS = "res/values/strings.xml"
EXPECTED_KEYS = (
    "onigiri_dex_zones_title",
    "onigiri_dex_zones_off",
    "onigiri_dex_zones_map_left",
    "onigiri_dex_zones_map_right",
    "onigiri_dex_zones_columns",
    "onigiri_dex_zones_grid",
    "onigiri_dex_zones_priority",
)
TAG = re.compile(r'^[ \t]*<string[ \t]+name="([^"]+)"[^>]*>.*</string>[ \t]*$')


def rebase(original_patch: str, decoded_root: Path):
    blocks = re.split(r"(?=^diff --git a/)", original_patch, flags=re.MULTILINE)
    found = [i for i, block in enumerate(blocks)
             if block.startswith(f"diff --git a/{STRINGS} b/{STRINGS}\n")]
    if len(found) != 1:
        raise ValueError("Expected exactly one res/values/strings.xml diff")
    idx = found[0]
    section = blocks[idx]
    if "@@ " not in section or "new file mode" in section:
        raise ValueError("Unexpected 0016 strings diff metadata")
    plus = [line[1:] for line in section.splitlines(keepends=True)
            if line.startswith("+") and not line.startswith("+++ ")]
    minus = [line for line in section.splitlines()
             if line.startswith("-") and not line.startswith("--- ")]
    if minus:
        raise ValueError("0016 string hunk replaces existing values; refusing to rebase")
    actual_keys = []
    for line in plus:
        m = TAG.fullmatch(line.rstrip("\r\n"))
        if m is None:
            raise ValueError("0016 contains non-string resource addition")
        actual_keys.append(m.group(1))
    if tuple(actual_keys) != EXPECTED_KEYS:
        raise ValueError(f"Unexpected new zone string keys: {actual_keys}")

    path = decoded_root / STRINGS
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"Decoded Fold6 strings missing or symlink: {path}")
    source = path.read_text(encoding="utf-8")
    old_lines = source.splitlines(keepends=True)
    names = {}
    for i, line in enumerate(old_lines):
        m = TAG.fullmatch(line.rstrip("\r\n"))
        if m:
            names.setdefault(m.group(1), []).append(i)
    if any(key in names for key in EXPECTED_KEYS):
        raise ValueError("Some new zone labels already exist; inspect partial patch state")

    # 0013 added autoboot; the original 0016 patch inserts immediately
    # before its title, leaving the preexisting Settings category below.
    autoboot = names.get("onigiri_autoboot_title", [])
    category = names.get("onigiri_settings_category_title", [])
    if len(autoboot) != 1 or len(category) != 1 or autoboot[0] >= category[0]:
        raise ValueError("Cannot uniquely locate Fold6 autoboot / Settings anchors")
    if sum(1 for line in old_lines if line.strip() == "</resources>") != 1:
        raise ValueError("No unique closing </resources> in decoded strings")
    newline = "\r\n" if old_lines[autoboot[0]].endswith("\r\n") else "\n"
    new_labels = [line.rstrip("\r\n") + newline for line in plus]
    new_lines = old_lines[:autoboot[0]] + new_labels + old_lines[autoboot[0]:]
    diff = list(difflib.unified_diff(
        old_lines, new_lines,
        fromfile=f"a/{STRINGS}", tofile=f"b/{STRINGS}", n=3))
    if not diff:
        raise ValueError("No new string diff created")
    blocks[idx] = f"diff --git a/{STRINGS} b/{STRINGS}\n" + "".join(diff)
    return "".join(blocks), {
        "inserted": actual_keys,
        "before": "onigiri_autoboot_title",
        "original_line": autoboot[0] + 1,
        "other_patch_sections_preserved": len(blocks) - 2,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--patch", required=True, type=Path,
                        help="Disposable copy of original Onigiri 0016 patch")
    parser.add_argument("--decoded", required=True, type=Path,
                        help="Current decoded F956N SecSettings.apk")
    args = parser.parse_args()
    try:
        updated, summary = rebase(args.patch.read_text(), args.decoded)
        args.patch.write_text(updated)
    except (OSError, UnicodeError, ValueError) as exc:
        parser.exit(1, f"Fold6 DeX zone strings rebase refused: {exc}\n")
    print(f"Fold6 DeX zones strings rebased: {summary}", flush=True)
    print("Only a temporary patch was updated; decoded strings unchanged.", flush=True)


if __name__ == "__main__":
    main()
