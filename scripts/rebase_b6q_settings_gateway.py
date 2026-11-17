#!/usr/bin/env python3
"""Rebase one Fold5 SecSettings SettingsGateway fragment allowlist hunk on F956N.

The old patch inserts the Settings fragment after v139. Fold6's array size and
the register count can differ. This creates an equivalent, context-correct
unified diff from the actual decoded Fold6 smali, in a DISPOSABLE PATCH COPY.
The original repository patch and the decoded APK are left unchanged.
Requires a single anchored static initializer, exact MainActivity string,
first matching v1..vN array after that anchor, and unused vN+1.
Other string arrays in the method are preserved. Fails closed otherwise.
"""
import argparse
import difflib
from pathlib import Path
import re

GATEWAY = "smali_classes2/com/android/settings/core/gateway/SettingsGateway.smali"
FRAGMENT = "moe.foss.onigiri.OnigiriSettingsFragment"
TARGET_CONST = f'    const-string v{{new}}, "{FRAGMENT}"'
ARRAY = re.compile(r'filled-new-array/range \{v1 \.\. v(\d+)\}, \[Ljava/lang/String;')
END = "\n.end method"
STATIC_ANCHOR = "com.samsung.android.fast.ui.MainActivity"


def rebase(patch_text: str, decoded: Path):
    """Return patched git diff and exact register change summary."""
    sections = re.split(r"(?=^diff --git a/)", patch_text, flags=re.MULTILINE)
    target = [index for index, section in enumerate(sections)
              if section.startswith(f"diff --git a/{GATEWAY} b/{GATEWAY}\n")]
    if len(target) != 1:
        raise ValueError("Expected exactly one SettingsGateway patch section")
    i = target[0]
    old_section = sections[i]
    if (FRAGMENT not in old_section or
            not re.search(r'\+    filled-new-array/range \{v1 \.\. v140\},', old_section)):
        raise ValueError("Unexpected upstream gateway patch; cannot safely adapt")

    filename = decoded / GATEWAY
    if not filename.is_file() or filename.is_symlink():
        raise ValueError(f"Decoded SettingsGateway not found: {filename}")
    original = filename.read_text()
    if FRAGMENT in original:
        raise ValueError("Fragment already appears in SettingsGateway; inspect previous patch state")

    # Pick the exact containing method, not a coincidental array in another
    # method; Samsung changes its initialization list between device builds.
    methods = []
    for header in re.finditer(r"^\.method [^\n]+$", original, re.MULTILINE):
        end = original.find(END, header.end())
        if end < 0:
            raise ValueError("Invalid smali: unterminated .method")
        body = original[header.start():end + len(END)]
        if STATIC_ANCHOR in body and ARRAY.search(body):
            methods.append((header.start(), end + len(END), body))
    if len(methods) != 1:
        raise ValueError(f"Expected one static fragment-list method, found {len(methods)}")
    start, end, body = methods[0]
    method_signature = body.splitlines()[0]
    if not re.search(r'\bstatic\b.*\(\)V$', method_signature):
        raise ValueError("Gateway fragment array must be in a static zero-argument void method")
    # Fold6 may construct multiple unrelated String[] arrays in <clinit>.
    # The original b5q patch targets the list containing the known Samsung
    # MainActivity class, not an arbitrary first v1..vN array.
    matches = list(ARRAY.finditer(body))
    anchors = list(re.finditer(
        rf'^[ \t]*const-string(?:/jumbo)?[ \t]+v(\d+),[ \t]*"{re.escape(STATIC_ANCHOR)}"[ \t]*
    if old_last < 2 or new_reg > 254:
        raise ValueError("Unsupported contiguous array register range")
    before = body[:array_match.start()]
    if not re.search(rf'\bconst-string(?:/jumbo)? v{old_last},\s*"[^"\n]+"', before):
        raise ValueError(f"Last array register v{old_last} was not initialized by const-string")
    # Only one new contiguous register is allowed; never destroy a register
    # already used elsewhere in the original initializer.
    if re.search(rf'\bv{new_reg}\b', body):
        raise ValueError(f"v{new_reg} is already used in F956N initializer; manual rebase needed")

    allocation = re.search(r"^\s*\.(locals|registers)\s+(\d+)\s*$", body, re.MULTILINE)
    if not allocation:
        raise ValueError("Cannot establish smali register allocation")
    declared = int(allocation.group(2))
    # Insert by the *selected match offset*: other arrays may have identical
    # text and must remain byte-for-byte unchanged.
    old_array = array_match.group(0)
    insertion = f'{TARGET_CONST.format(new=new_reg)}\n\n    ' + \
                old_array.replace(f"v{old_last}}}", f"v{new_reg}}}")
    replacement_body = (body[:array_match.start()] + insertion +
                        body[array_match.end():])
    if declared <= new_reg:
        updated_allocation = re.search(
            r"^\s*\.(locals|registers)\s+(\d+)\s*$",
            replacement_body, re.MULTILINE)
        if updated_allocation is None:
            raise ValueError("Cannot update register allocation safely")
        old_line = updated_allocation.group(0)
        new_line = old_line.replace(updated_allocation.group(2),
                                    str(new_reg + 1), 1)
        replacement_body = (replacement_body[:updated_allocation.start()] +
                            new_line + replacement_body[updated_allocation.end():])
    revised = original[:start] + replacement_body + original[end:]

    unified = list(difflib.unified_diff(
        original.splitlines(keepends=True),
        revised.splitlines(keepends=True),
        fromfile=f"a/{GATEWAY}", tofile=f"b/{GATEWAY}",
        n=3,
    ))
    if not unified or not any(x.startswith("@@") for x in unified):
        raise ValueError("No changes generated to gateway smali")
    new_section = f"diff --git a/{GATEWAY} b/{GATEWAY}\n" + "".join(unified)
    sections[i] = new_section
    return "".join(sections), {
        "old_last_register": old_last,
        "new_last_register": new_reg,
        "registers_declared_before": declared,
        "registers_declared_after": max(declared, new_reg + 1),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--patch", type=Path, required=True,
                        help="Disposable copy of upstream 0001-Add-Onigiri-Settings.patch")
    parser.add_argument("--decoded", type=Path, required=True,
                        help="Already decoded F956N SecSettings.apk directory")
    args = parser.parse_args()
    try:
        result, changes = rebase(args.patch.read_text(), args.decoded)
        args.patch.write_text(result)
    except (OSError, ValueError) as exc:
        parser.exit(1, f"SettingsGateway rebase refused: {exc}\n")
    print("SettingsGateway F956N list adapted:", changes, flush=True)
    print("Only disposable patch copy updated; original smali unchanged.", flush=True)


if __name__ == "__main__":
    main()
,
        body, re.MULTILINE
    ))
    if len(anchors) != 1:
        raise ValueError(f"Expected one precise Samsung MainActivity const-string, found {len(anchors)}")
    anchor = anchors[0]
    anchor_reg = int(anchor.group(1))
    following = [m for m in matches if m.start() > anchor.end()]
    if not following:
        raise ValueError("No matching String[] array after Samsung MainActivity anchor")
    # First array after the anchor must contain its register; otherwise the
    # initializer has changed too much to safely rebase without real smali.
    array_match = following[0]
    old_last = int(array_match.group(1))
    if not 1 <= anchor_reg <= old_last:
        raise ValueError(f"Anchor v{anchor_reg} outside candidate v1..v{old_last} array")
    between = body[anchor.end():array_match.start()]
    if "filled-new-array" in between:
        raise ValueError("An unrelated array appears between anchor and candidate")
    if not re.search(
        rf'\bconst-string(?:/jumbo)?[ \t]+v{old_last},[ \t]*"[^"\n]+"',
        between
    ) and old_last != anchor_reg:
        raise ValueError(f"Final v{old_last} value not initialized after Samsung MainActivity anchor")
    new_reg = old_last + 1
    if old_last < 2 or new_reg > 254:
        raise ValueError("Unsupported contiguous array register range")
    before = body[:array_match.start()]
    if not re.search(rf'\bconst-string(?:/jumbo)? v{old_last},\s*"[^"\n]+"', before):
        raise ValueError(f"Last array register v{old_last} was not initialized by const-string")
    # Only one new contiguous register is allowed; never destroy a register
    # already used elsewhere in the original initializer.
    if re.search(rf'\bv{new_reg}\b', body):
        raise ValueError(f"v{new_reg} is already used in F956N initializer; manual rebase needed")

    allocation = re.search(r"^\s*\.(locals|registers)\s+(\d+)\s*$", body, re.MULTILINE)
    if not allocation:
        raise ValueError("Cannot establish smali register allocation")
    declared = int(allocation.group(2))
    replacement_body = body
    if declared <= new_reg:
        from_line = allocation.group(0)
        to_line = from_line.replace(allocation.group(2), str(new_reg + 1), 1)
        replacement_body = replacement_body.replace(from_line, to_line, 1)

    # Insert just before the array constructor. Preserve exact neighboring
    # Fold6 instructions and keep original static list elements in place.
    old_array = array_match.group(0)
    insertion = f'{TARGET_CONST.format(new=new_reg)}\n\n    ' + \
                old_array.replace(f"v{old_last}}}", f"v{new_reg}}}")
    if replacement_body.count(old_array) != 1:
        raise ValueError("Array declaration not unique")
    replacement_body = replacement_body.replace(old_array, insertion, 1)
    revised = original[:start] + replacement_body + original[end:]

    unified = list(difflib.unified_diff(
        original.splitlines(keepends=True),
        revised.splitlines(keepends=True),
        fromfile=f"a/{GATEWAY}", tofile=f"b/{GATEWAY}",
        n=3,
    ))
    if not unified or not any(x.startswith("@@") for x in unified):
        raise ValueError("No changes generated to gateway smali")
    new_section = f"diff --git a/{GATEWAY} b/{GATEWAY}\n" + "".join(unified)
    sections[i] = new_section
    return "".join(sections), {
        "old_last_register": old_last,
        "new_last_register": new_reg,
        "registers_declared_before": declared,
        "registers_declared_after": max(declared, new_reg + 1),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--patch", type=Path, required=True,
                        help="Disposable copy of upstream 0001-Add-Onigiri-Settings.patch")
    parser.add_argument("--decoded", type=Path, required=True,
                        help="Already decoded F956N SecSettings.apk directory")
    args = parser.parse_args()
    try:
        result, changes = rebase(args.patch.read_text(), args.decoded)
        args.patch.write_text(result)
    except (OSError, ValueError) as exc:
        parser.exit(1, f"SettingsGateway rebase refused: {exc}\n")
    print("SettingsGateway F956N list adapted:", changes, flush=True)
    print("Only disposable patch copy updated; original smali unchanged.", flush=True)


if __name__ == "__main__":
    main()
