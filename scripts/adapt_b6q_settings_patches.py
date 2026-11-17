#!/usr/bin/env python3
"""Adapt *only absent optional translation files* in upstream Settings patches.

The stock F956N system APK may omit some language/region resource XMLs
present on Fold5. Remove only those diff sections from a disposable copied
patch directory; preserve AndroidManifest, smali, public IDs, new-file
patches, and every existing locale. This makes no changes to original source.
"""
import argparse
from pathlib import Path
import re

LOCALE = re.compile(r"^res/values-[^/]+/strings\.xml$")


def adapt_patch(text: str, decoded_root: Path):
    sections = re.split(r"(?=^diff --git a/)", text, flags=re.MULTILINE)
    if len(sections) < 2:
        raise ValueError("Expected unified git patch with diff --git sections")
    output = [sections[0]]
    skipped = []
    for section in sections[1:]:
        m = re.match(r"diff --git a/([^\n]+) b/([^\n]+)\n", section)
        if not m or m.group(1) != m.group(2):
            raise ValueError("Unsupported git patch section (cannot adapt safely)")
        path = m.group(2)
        if (LOCALE.fullmatch(path) and not (decoded_root / path).is_file()
                and "new file mode " not in section
                and "--- /dev/null" not in section):
            skipped.append(path)
            continue
        output.append(section)
    if len(output) < 2:
        raise ValueError("No meaningful patch sections remain")
    return "".join(output), skipped


def adapt_tree(patches: Path, apktool_root: Path):
    updated = []
    for patch in sorted(patches.rglob("*.patch")):
        relative = patch.parent.relative_to(patches)
        parts = relative.parts
        partition = parts[0]
        if partition not in ("system", "system_ext", "vendor", "product", "odm"):
            raise ValueError(f"Unexpected patch partition {partition}")
        decoded = apktool_root / relative
        if not decoded.is_dir():
            raise ValueError(f"Decoded target missing for {patch}: {decoded}")
        original = patch.read_text()
        replacement, skipped = adapt_patch(original, decoded)
        if skipped:
            patch.write_text(replacement)
            updated.append({"patch": str(patch.relative_to(patches)),
                            "skipped_optional_locales": skipped})
    return updated


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--patches", type=Path, required=True)
    parser.add_argument("--apktool-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        changes = adapt_tree(args.patches, args.apktool_dir)
    except (ValueError, OSError) as e:
        parser.exit(1, f"Patch adaptation failed: {e}\n")
    for entry in changes:
        print("Adapted:", entry["patch"])
        for path in entry["skipped_optional_locales"]:
            print("  skipped missing optional translation:", path)
    print(f"Adapted {len(changes)} copied patches; original OnigiriDeX files untouched.")


if __name__ == "__main__":
    main()
