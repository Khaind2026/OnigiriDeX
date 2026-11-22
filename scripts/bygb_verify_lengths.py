#!/usr/bin/env python3
"""Check raw partition lengths in an active BYGB verification without reading super."""
import argparse
from pathlib import Path
import re
import subprocess
import sys


def compare(info, folder):
    rows = []
    for block in re.split(r"(?m)^\s*Hashtree descriptor:\s*$", info)[1:]:
        fields = dict(re.findall(r"(?m)^\s*(Partition Name|Image Size|Tree Offset|Tree Size):\s*([^\n]+)$", block))
        name = fields["Partition Name"].strip()
        if not re.fullmatch(r"[a-z0-9_]+", name):
            raise ValueError("Invalid partition name")
        data, offset, tree = [int(fields[k].split()[0]) for k in ("Image Size", "Tree Offset", "Tree Size")]
        actual = (folder / (name + ".img")).stat().st_size
        status = "SHORT_DATA" if actual < data else "SHORT_TREE" if tree and actual < offset + tree else "SIZE_OK"
        rows.append((name, actual, data, offset + tree, status))
    if not rows:
        raise ValueError("No hashtree descriptors found")
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("pid", nargs="?", type=int)
    source.add_argument("--image", type=Path)
    args = parser.parse_args()
    if args.image:
        vb = args.image.resolve()
    else:
        cmd = Path(f"/proc/{args.pid}/cmdline").read_bytes().decode().split("\0")
        if "verify_image" not in cmd or "--image" not in cmd:
            raise ValueError("PID no longer identifies the verifier")
        vb = Path(cmd[cmd.index("--image") + 1])
    if not vb.is_absolute() or vb.name != "vbmeta_system.img":
        raise ValueError("Expected an absolute vbmeta_system.img path")
    tool = Path(__file__).resolve().parents[1] / "out/tools/bin/avbtool"
    info = subprocess.check_output([str(tool), "info_image", "--image", str(vb)], text=True)
    rows = compare(info, vb.parent)
    print("partition  actual_bytes  signed_data_bytes  tree_end_bytes  result")
    for row in rows:
        print(*row)
    return int(any(row[-1] != "SIZE_OK" for row in rows))


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, ValueError, KeyError, IndexError, subprocess.SubprocessError) as exc:
        sys.exit(f"Size check unavailable: {exc}")
