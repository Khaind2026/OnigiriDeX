#!/usr/bin/env python3
"""Rebase one Fold5 SecSettings registered-fragment count hunk on Fold6.

Samsung changes the number of SAMSUNG_ENTRY_FRAGMENTS between builds.
The original Onigiri patch replaces a hardcoded integer bound with
array-length. Locate the EXACT same loop in decoded F956N SettingsActivity
and change ONLY its integer const instruction in a DISPOSABLE patch copy.
Never edit the decoded file directly, never skip a smali conflict.
"""
import argparse
import difflib
from pathlib import Path
import re

TARGET = "smali_classes2/com/android/settings/SettingsActivity.smali"
FIELD = ("Lcom/android/settings/core/gateway/SettingsGateway;"
         "->SAMSUNG_ENTRY_FRAGMENTS:[Ljava/lang/String;")
LOAD = re.compile(r"^[ \t]*sget-object[ \t]+(?P<array>v\d+),[ \t]*"
                  + re.escape(FIELD) + r"[ \t]*$")
CONST = re.compile(r"^(?P<indent>[ \t]*)const(?:/4|/16)?[ \t]+"
                   r"(?P<bound>v\d+),[ \t]*(?:0x[0-9a-fA-F]+|\d+)[ \t]*$")
IF_GE = re.compile(r"^[ \t]*if-ge[ \t]+(?P<index>v\d+),[ \t]*"
                   r"(?P<bound>v\d+),[ \t]*:[A-Za-z0-9_$]+[ \t]*$")
AGET = re.compile(r"^[ \t]*aget-object[ \t]+(?P<dest>v\d+),[ \t]*"
                  r"(?P<array>v\d+),[ \t]*(?P<index>v\d+)[ \t]*$")


def next_instruction(lines, pos):
    while pos < len(lines) and (
        not lines[pos].strip() or lines[pos].lstrip().startswith("#")
    ):
        pos += 1
    return pos


def adapt(patch_text: str, decoded: Path):
    sections = re.split(r"(?=^diff --git a/)", patch_text, flags=re.MULTILINE)
    positions = [i for i, part in enumerate(sections)
                 if part.startswith(f"diff --git a/{TARGET} b/{TARGET}\n")]
    if len(positions) != 1:
        raise ValueError("Expected exactly one SettingsActivity source patch")
    i = positions[0]
    old_section = sections[i]
    if ("SAMSUNG_ENTRY_FRAGMENTS" not in old_section or
        "+    array-length v2, v1" not in old_section or
        "-    const/16 v2, 0x8b" not in old_section):
        raise ValueError("Unexpected upstream 0008 patch; refusing rebase")

    target = decoded / TARGET
    if not target.is_file() or target.is_symlink():
        raise ValueError(f"Missing decoded SettingsActivity: {target}")
    source = target.read_text()
    lines = source.splitlines(keepends=True)
    matches = []
    for idx, line in enumerate(lines):
        field = LOAD.fullmatch(line.rstrip("\r\n"))
        if field is None:
            continue
        j = next_instruction(lines, idx + 1)
        if j >= len(lines):
            continue
        bound = CONST.fullmatch(lines[j].rstrip("\r\n"))
        if bound is None:
            continue
        k = next_instruction(lines, j + 1)
        if k >= len(lines):
            continue
        branch = IF_GE.fullmatch(lines[k].rstrip("\r\n"))
        if branch is None or branch.group("bound") != bound.group("bound"):
            continue
        z = next_instruction(lines, k + 1)
        if z >= len(lines):
            continue
        get = AGET.fullmatch(lines[z].rstrip("\r\n"))
        if get is None:
            continue
        if not (get.group("array") == field.group("array") ==
                get.group("dest")):
            continue
        if get.group("index") != branch.group("index"):
            continue
        matches.append((j, field.group("array"), bound.group("bound")))
    if len(matches) != 1:
        raise ValueError(
            f"Expected one exact SAMSUNG_ENTRY_FRAGMENTS count loop, "
            f"found {len(matches)}. Inspect F956N SettingsActivity instead of forcing patch."
        )
    index, array_register, count_register = matches[0]
    previous = lines[index]
    ending = "\r\n" if previous.endswith("\r\n") else (
        "\n" if previous.endswith("\n") else "")
    lines[index] = (
        previous[:len(previous) - len(previous.lstrip())] +
        f"array-length {count_register}, {array_register}" + ending
    )
    updated = "".join(lines)
    diff = list(difflib.unified_diff(
        source.splitlines(keepends=True),
        updated.splitlines(keepends=True),
        fromfile=f"a/{TARGET}", tofile=f"b/{TARGET}", n=3))
    if not diff or not any(x.startswith("@@") for x in diff):
        raise ValueError("No meaningful SettingsActivity patch generated")
    sections[i] = f"diff --git a/{TARGET} b/{TARGET}\n" + "".join(diff)
    return "".join(sections), {
        "array_register": array_register,
        "count_register": count_register,
        "source_line": index + 1,
        "old_instruction": previous.strip(),
        "new_instruction": lines[index].strip()
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--patch", required=True, type=Path)
    parser.add_argument("--decoded", required=True, type=Path)
    args = parser.parse_args()
    try:
        modified, info = adapt(args.patch.read_text(), args.decoded)
        args.patch.write_text(modified)
    except (OSError, ValueError) as exc:
        parser.exit(1, f"SettingsActivity count rebase refused: {exc}\n")
    print(f"Fold6 SettingsActivity allowlist count rebased: {info}", flush=True)
    print("Only temporary patch modified; original decoded smali untouched.", flush=True)


if __name__ == "__main__":
    main()
