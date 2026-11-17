#!/usr/bin/env python3
"""Rebase one Fold5 SecSettings SettingsGateway fragment allowlist hunk on F956N.

The old patch inserts the Settings fragment after v139. Fold6's array size and
the register count can differ. This creates an equivalent, context-correct
unified diff from the actual decoded Fold6 smali, in a DISPOSABLE PATCH COPY.
The original repository patch and the decoded APK are left unchanged.
Requires an anchored static initializer and a matching String[] array. If
v(N+1) is occupied, appends after its move-result-object using a new private
helper with its own registers. Otherwise extends the original contiguous
range. Original resources and other arrays remain unchanged.
"""
import argparse
import difflib
from pathlib import Path
import re

GATEWAY = "smali_classes2/com/android/settings/core/gateway/SettingsGateway.smali"
FRAGMENT = "moe.foss.onigiri.OnigiriSettingsFragment"
TARGET_CONST = f'    const-string v{{new}}, "{FRAGMENT}"'
ARRAY = re.compile(r'^[ \t]*filled-new-array/range \{v1 \.\. v(\d+)\}, \[Ljava/lang/String;', re.MULTILINE)
END = "\n.end method"
STATIC_ANCHOR = "com.samsung.android.fast.ui.MainActivity"

HELPER_NAME = "duykhai$appendOnigiriFragment"
HELPER_SIGNATURE = f"{HELPER_NAME}([Ljava/lang/String;)[Ljava/lang/String;"
HELPER_SMALI = f""".method private static {HELPER_SIGNATURE}
    .locals 3

    array-length v0, p0
    add-int/lit8 v1, v0, 0x1
    invoke-static {{p0, v1}}, Ljava/util/Arrays;->copyOf([Ljava/lang/Object;I)[Ljava/lang/Object;
    move-result-object v2
    check-cast v2, [Ljava/lang/String;
    const-string v1, "{FRAGMENT}"
    aput-object v1, v2, v0
    return-object v2
.end method"""


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
    # Fold6 can build multiple arrays. Only the array following the exact
    # MainActivity string is a possible target for the original b5q patch.
    matches = list(ARRAY.finditer(body))
    anchors = list(re.finditer(
        rf'^[ \t]*const-string(?:/jumbo)?[ \t]+v(\d+),[ \t]*"{re.escape(STATIC_ANCHOR)}"[ \t]*$',
        body, re.MULTILINE
    ))
    if len(anchors) != 1:
        raise ValueError(f"Expected one precise Samsung MainActivity const-string, found {len(anchors)}")
    anchor = anchors[0]
    anchor_reg = int(anchor.group(1))
    following = [m for m in matches if m.start() > anchor.end()]
    if not following:
        raise ValueError("No String[] array after Samsung MainActivity anchor")
    array_match = following[0]
    old_last = int(array_match.group(1))
    if not 1 <= anchor_reg <= old_last:
        raise ValueError(f"Anchor v{anchor_reg} outside candidate v1..v{old_last} array")
    between = body[anchor.end():array_match.start()]
    if "filled-new-array" in between:
        raise ValueError("Unrelated array between MainActivity anchor and candidate")
    # The existing stock F956N array is already part of a working initializer.
    # Its last vN entry may come from sget-object/move-object or const-string;
    # validating only const-string falsely rejected the real v140 register.
    # We add a NEW string register without changing any existing v1..vN entry.
    new_reg = old_last + 1
    if old_last < 2 or new_reg > 254:
        raise ValueError("Unsupported contiguous array register range")
    allocation = re.search(r"^\s*\.(locals|registers)\s+(\d+)\s*$", body, re.MULTILINE)
    if not allocation:
        raise ValueError("Cannot establish smali register allocation")
    declared = int(allocation.group(2))
    occupied = re.search(rf'\bv{new_reg}\b', body) is not None

    if occupied:
        # Fold6 already uses v(N+1); expanding a filled-new-array/range would
        # overwrite a live register. Instead append to the freshly produced
        # String[] using the existing move-result-object register. This does
        # not change the initializer register count or any v1..vN values.
        if HELPER_SIGNATURE in original:
            raise ValueError("SettingsGateway helper name already exists")
        tail = body[array_match.end():]
        result = re.match(
            r'(?:[ \t]*\n|[ \t]*#[^\n]*\n)+'
            r'[ \t]*move-result-object[ \t]+(?P<reg>v\d+)\b',
            tail
        )
        if result is None:
            raise ValueError("Missing immediate array move-result-object; manual rebase required")
        result_register = result.group("reg")
        insert_at = array_match.end() + result.end()
        hook = (
            f"\n    invoke-static {{{result_register}}}, "
            f"Lcom/android/settings/core/gateway/SettingsGateway;->{HELPER_SIGNATURE}"
            f"\n    move-result-object {result_register}"
        )
        replacement_body = body[:insert_at] + hook + body[insert_at:]
        revised = original[:start] + replacement_body + original[end:]
        revised = revised.rstrip("\n") + "\n\n" + HELPER_SMALI + "\n"
        strategy = "post_array_append"
        declared_after = declared
    else:
        # Original b5q-style extension remains usable when the next
        # contiguous register is genuinely unused in the Fold6 initializer.
        old_array = array_match.group(0)
        insertion = f'{TARGET_CONST.format(new=new_reg)}\n\n' + \
                    old_array.replace(f"v{old_last}}}", f"v{new_reg}}}")
        replacement_body = (
            body[:array_match.start()] + insertion + body[array_match.end():]
        )
        declared_after = max(declared, new_reg + 1)
        if declared <= new_reg:
            updated_allocation = re.search(
                r"^\s*\.(locals|registers)\s+(\d+)\s*$",
                replacement_body, re.MULTILINE
            )
            if updated_allocation is None:
                raise ValueError("Cannot update register allocation safely")
            old_line = updated_allocation.group(0)
            new_line = old_line.replace(
                updated_allocation.group(2), str(declared_after), 1
            )
            replacement_body = (
                replacement_body[:updated_allocation.start()] +
                new_line + replacement_body[updated_allocation.end():]
            )
        revised = original[:start] + replacement_body + original[end:]
        strategy = "extend_contiguous_range"

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
        "new_last_register": old_last if occupied else new_reg,
        "registers_declared_before": declared,
        "registers_declared_after": declared_after,
        "strategy": strategy,
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
