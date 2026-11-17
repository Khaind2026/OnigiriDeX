#!/usr/bin/env python3
"""Rebase strictly additive Onigiri res/values/strings.xml hunks on Fold6.

Only accepts string additions (no removals, replacements or other XML).
Recreates the single diff using the actual decoded SecSettings strings and
inserts additions immediately before the unique settings-category title.
Preserves every other original patch section unmodified. Fails closed.
"""
import argparse
import difflib
from pathlib import Path
import re
import xml.etree.ElementTree as ET

STRINGS = "res/values/strings.xml"
TAG = re.compile(r'^[ \t]*<string[ \t]+name="([^"]+)"[^>]*>.*</string>[ \t]*$')
CATEGORY = "onigiri_settings_category_title"


def adapt(original_patch: str, decoded_root: Path):
    sections = re.split(r"(?=^diff --git a/)", original_patch, flags=re.MULTILINE)
    hits = [i for i, part in enumerate(sections)
            if part.startswith(f"diff --git a/{STRINGS} b/{STRINGS}\n")]
    if len(hits) != 1:
        raise ValueError("Expected one res/values/strings.xml section")
    index = hits[0]
    section = sections[index]
    if "@@ " not in section or "new file mode" in section:
        raise ValueError("Unexpected strings patch format")
    additions = [s[1:] for s in section.splitlines(keepends=True)
                 if s.startswith("+") and not s.startswith("+++ ")]
    deletions = [s for s in section.splitlines()
                 if s.startswith("-") and not s.startswith("--- ")]
    if deletions or not additions:
        raise ValueError("Non-additive strings patch; manual rebase required")
    keys = []
    for item in additions:
        found = TAG.fullmatch(item.rstrip("\r\n"))
        if found is None:
            raise ValueError("Non-string addition in strings.xml section")
        keys.append(found.group(1))
    if len(set(keys)) != len(keys):
        raise ValueError("Duplicate resource keys in patch")

    path = decoded_root / STRINGS
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"Decoded strings missing: {path}")
    source = path.read_text(encoding="utf-8")
    original_lines = source.splitlines(keepends=True)
    # Strict XML parsing catches malformed or duplicate-resource issues
    # before patch generation, without altering the source.
    try:
        xml_root = ET.fromstring(source)
    except ET.ParseError as exc:
        raise ValueError(f"Invalid decoded strings.xml: {exc}") from exc
    if xml_root.tag != "resources":
        raise ValueError("Expected resources root")
    names = {}
    for j, line in enumerate(original_lines):
        match = TAG.fullmatch(line.rstrip("\r\n"))
        if match:
            names.setdefault(match.group(1), []).append(j)
    if any(k in names for k in keys):
        raise ValueError("Some resource keys already present; partial patch possible")
    positions = names.get(CATEGORY, [])
    if len(positions) != 1:
        raise ValueError("Cannot uniquely locate settings category anchor")
    if len(names.get("onigiri_autoboot_title", [])) != 1:
        raise ValueError("Missing existing Onigiri settings anchor")
    if sum(line.strip() == "</resources>" for line in original_lines) != 1:
        raise ValueError("Expected exactly one closing resources tag")
    at = positions[0]
    newline = "\r\n" if original_lines[at].endswith("\r\n") else "\n"
    added_lines = [line.rstrip("\r\n") + newline for line in additions]
    new_lines = original_lines[:at] + added_lines + original_lines[at:]
    updated_resource = "".join(new_lines)
    try:
        ET.fromstring(updated_resource)
    except ET.ParseError as exc:
        raise ValueError(f"Rebased strings invalid XML: {exc}") from exc
    diff = list(difflib.unified_diff(
        original_lines, new_lines,
        fromfile=f"a/{STRINGS}", tofile=f"b/{STRINGS}", n=3))
    if not diff:
        raise ValueError("Nothing to rebase")
    sections[index] = f"diff --git a/{STRINGS} b/{STRINGS}\n" + "".join(diff)
    return "".join(sections), {"added_keys": keys, "insert_before": CATEGORY,
                               "other_sections_preserved": len(sections) - 2}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--patch", type=Path, required=True)
    parser.add_argument("--decoded", type=Path, required=True)
    args = parser.parse_args()
    try:
        result, info = adapt(args.patch.read_text(), args.decoded)
        args.patch.write_text(result)
    except (OSError, UnicodeError, ValueError) as exc:
        parser.exit(1, f"Fold6 additive strings rebase refused: {exc}\n")
    print(f"Fold6 additive Settings strings rebased: {info}", flush=True)
    print("Only temporary patch changed; decoded XML and stock firmware unchanged.")


if __name__ == "__main__":
    main()
