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
        if not m:
            raise ValueError("Malformed git diff header (cannot adapt safely)")
        src, path = m.group(1), m.group(2)
        # Some original Onigiri patches use the peculiar new-file header
        # 'diff --git a/b/<file> b/<file>'. The actual destination is in the
        # b/ path and +++ b/<file>. git apply handles this as file creation.
        # Do not rewrite or discard this section. Only permit the mismatch
        # for exact new-file metadata; existing-file renames must be reviewed.
        if src != path:
            is_source_new = (
                src == "b/" + path
                and re.search(r"(?m)^new file mode 100644$", section) is not None
                and re.search(r"(?m)^--- /dev/null$", section) is not None
                and ("+++ b/" + path + "\\n") in section
            )
            if not is_source_new:
                raise ValueError(
                    f"Unsupported rename or malformed new-file section: "
                    f"{src} -> {path}"
                )
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
    parser.add_argument("--patch", type=Path, help="One disposable patch copy")
    parser.add_argument("--decoded", type=Path, help="One already decoded APK/JAR directory")
    parser.add_argument("--patches", type=Path, help="Disposable patches tree")
    parser.add_argument("--apktool-dir", type=Path, help="Decoded APK/JAR tree")
    args = parser.parse_args()
    try:
        if args.patch and args.decoded and not args.patches and not args.apktool_dir:
            if not args.decoded.is_dir():
                raise ValueError(f"Decoded APK/JAR directory not present: {args.decoded}")
            original = args.patch.read_text()
            updated, skipped = adapt_patch(original, args.decoded)
            if skipped:
                args.patch.write_text(updated)
            for name in skipped:
                print(f"Skipping optional translation absent in Fold6: {name}", flush=True)
            return
        if args.patches and args.apktool_dir and not args.patch and not args.decoded:
            changes = adapt_tree(args.patches, args.apktool_dir)
            for entry in changes:
                print("Adapted:", entry["patch"])
                for name in entry["skipped_optional_locales"]:
                    print("  skipped missing optional translation:", name)
            print(f"Adapted {len(changes)} disposable patches.")
            return
        parser.error("Use --patch and --decoded OR --patches and --apktool-dir")
    except (ValueError, OSError) as e:
        parser.exit(1, f"Patch adaptation failed: {e}\n")


if __name__ == "__main__":
    main()
