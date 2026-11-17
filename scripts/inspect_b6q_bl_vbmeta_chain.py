#!/usr/bin/env python3
"""Read-only inventory of stock F741N BL vbmeta and its AVB descriptors.

Extracts ONLY the small top-level vbmeta image into a temporary directory.
It does not modify firmware, verify Samsung's trust root, create Odin AP or flash.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile

from inspect_f741n_f956n_archives import locate_archive
from analyze_b6q_avb import decode_vbmeta_header

MODEL = "SM-F741N"
MAX_COMPRESSED = 16 * 1024 * 1024
MAX_IMAGE = 32 * 1024 * 1024
MODIFIED_PARTITIONS = {"system", "product", "system_ext"}
DESCRIPTOR = re.compile(r"(?im)^[ \t]*(Chain Partition|Hash|Hashtree) descriptor:[ \t]*$")
PARTITION = re.compile(r"(?im)^[ \t]*Partition Name:[ \t]*([a-z0-9_]+)[ \t]*$")


def descriptors(text):
    chunks = DESCRIPTOR.split(text)
    parsed = []
    for index in range(1, len(chunks), 2):
        match = PARTITION.search(chunks[index + 1])
        parsed.append({"type": chunks[index].lower(), "partition": match.group(1) if match else None})
    return parsed


def extract_stock_bl_vbmeta(archive: Path, temp: Path, lz4="lz4"):
    """Keep an ephemeral copy only, with strict member and output size bounds."""
    with tarfile.open(archive, "r:") as package:
        possible = [m for m in package if m.isfile()
                    and Path(m.name).name.lower() in ("vbmeta.img", "vbmeta.img.lz4")]
        if len(possible) != 1:
            raise ValueError("Exactly one top-level vbmeta image is required in stock BL")
        member = possible[0]
        if member.name != Path(member.name).name or member.name.startswith("."):
            raise ValueError("Unsafe nested BL vbmeta member")
        if not (256 <= member.size <= MAX_COMPRESSED):
            raise ValueError("Unexpected compressed BL vbmeta size")
        source = package.extractfile(member)
        if source is None:
            raise ValueError("Unable to read BL vbmeta member")
        output = temp / "vbmeta.img"
        if member.name.lower().endswith(".lz4"):
            compressed = temp / "vbmeta.img.lz4"
            with compressed.open("xb") as target:
                shutil.copyfileobj(source, target)
            with output.open("xb") as target:
                process = subprocess.Popen([lz4, "-d", "-c", str(compressed)],
                                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                try:
                    count = 0
                    while True:
                        piece = process.stdout.read(65536)
                        if not piece:
                            break
                        count += len(piece)
                        if count > MAX_IMAGE:
                            raise ValueError("Decompressed BL vbmeta exceeds safety limit")
                        target.write(piece)
                    error = process.stderr.read(1200)
                    if process.wait(timeout=45) != 0:
                        raise ValueError("BL vbmeta LZ4 decompression failed: "
                                         + error.decode("utf-8", "replace"))
                except BaseException:
                    process.kill()
                    process.wait()
                    raise
        else:
            with output.open("xb") as target:
                shutil.copyfileobj(source, target)
        if not (256 <= output.stat().st_size <= MAX_IMAGE):
            raise ValueError("Invalid decoded BL vbmeta size")
        with output.open("rb") as stream:
            if stream.read(4) != b"AVB0":
                raise ValueError("BL vbmeta does not have AVB0 magic")
        return output


def info_image(path: Path, avbtool: str):
    completed = subprocess.run([avbtool, "info_image", "--image", str(path)],
                               capture_output=True, text=True, timeout=45)
    if completed.returncode != 0:
        raise ValueError("avbtool could not parse " + path.name + ": "
                         + (completed.stderr or completed.stdout)[:1000])
    return completed.stdout


def make_report(odin_root: Path, staged: Path, *, lz4="lz4", avbtool=None):
    stock = odin_root / "SM-F741N_SKC"
    if stock.is_symlink() or not stock.is_dir():
        raise ValueError("Verified stock F741N Odin directory not found")
    vbmeta_system = staged / "vbmeta_system.img"
    if vbmeta_system.is_symlink() or not vbmeta_system.is_file():
        raise ValueError("Original staged F741N vbmeta_system.img not found")
    tool = avbtool or shutil.which("avbtool")
    if not tool:
        raise ValueError("avbtool is required for BL vbmeta descriptor inspection")
    archive = locate_archive(stock, MODEL, "BL")
    with tempfile.TemporaryDirectory(prefix="f741n-bl-vbmeta-") as tmp:
        top = extract_stock_bl_vbmeta(archive, Path(tmp), lz4)
        header = decode_vbmeta_header(top)
        top_desc = descriptors(info_image(top, tool))
        system_desc = descriptors(info_image(vbmeta_system, tool))
        top_sha = hashlib.sha256(top.read_bytes()).hexdigest()
        top_size = top.stat().st_size
    chain_targets = sorted({d["partition"] for d in top_desc
                            if d["type"] == "chain partition" and d["partition"]})
    impacted = sorted({d["partition"] for d in top_desc + system_desc
                       if d["type"] in ("hash", "hashtree") and d["partition"] in MODIFIED_PARTITIONS})
    return {
        "model": MODEL,
        "phase": "READ_ONLY_STOCK_BL_VBMETA_CHAIN_INSPECTION",
        "source_bl_archive": archive.name,
        "stock_bl_vbmeta": {
            "bytes": top_size, "sha256": top_sha, "header": header,
            "descriptors": top_desc, "chain_targets": chain_targets
        },
        "stock_ap_vbmeta_system": {"descriptors": system_desc},
        "direct_system_hash_or_hashtree_overlap": impacted,
        "vbmeta_system_chain_declared_in_bl": "vbmeta_system" in chain_targets,
        "status": "BLOCKED_FOR_FLASH_UNVERIFIED_HYBRID_BOOT",
        "flashable": False,
        "next_gates": [
            "Confirm the authentic stock chain of trust and rollback policy; parsing is not signature verification",
            "Determine how signed vbmeta_system descriptors can cover modified system/product/system_ext",
            "Audit F956N framework against F741N vendor VINTF, SELinux and first-stage mount requirements",
            "Use recoverable hardware tests only after independent boot compatibility review"
        ],
        "notes": [
            "Only stock F741N BL vbmeta was read in a temporary directory; no firmware changed",
            "No Odin AP built and no flash permission granted",
            "Never use F956N BL/boot/vbmeta on F741N"
        ]
    }


def main(argv=None):
    repo = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--odin-root", type=Path, default=repo / "out/odin")
    parser.add_argument("--stock", type=Path, default=repo / "out/b6q/analysis/f741n-stock-boot-chain")
    parser.add_argument("--output", type=Path, default=repo / "out/b6q/analysis/f741n-bl-vbmeta-chain.json")
    args = parser.parse_args(argv)
    try:
        if args.output.exists() or args.output.is_symlink():
            raise ValueError("Refusing to overwrite existing report: " + str(args.output))
        report = make_report(args.odin_root, args.stock)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    except (OSError, ValueError, subprocess.TimeoutExpired, tarfile.TarError) as error:
        parser.exit(1, "F741N BL vbmeta chain inspection failed: " + str(error) + "\n")
    print("Stock F741N BL vbmeta: AVB0 parsed; signatures NOT verified")
    print("Top-level chain targets:", ", ".join(report["stock_bl_vbmeta"]["chain_targets"]) or "none identified")
    print("Modified partition descriptor overlap:", ", ".join(report["direct_system_hash_or_hashtree_overlap"]) or "none identified")
    print("STATUS:", report["status"])
    print("Report:", args.output)
    print("NO AP CREATED. DO NOT FLASH.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
