#!/usr/bin/env python3
"""Safely stage selected stock partition images for DuyKhaiDeX b6q research.

Default = preflight only (disk, tools, source names, verified metadata).
Use --extract --model SM-F956N or --model SM-F741N to explicitly unpack the
selected stock images on the local Debian host. Never flashes any device.
Preserves original Odin archives and refuses to overwrite extracted outputs.
Uses bounded-memory streaming lz4 -> sparse-to-RAW, then lpunpack -p each image.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import tarfile
import tempfile
import threading

from inspect_f741n_f956n_archives import locate_archive, MODELS
from plan_f741n_f956n_port import normalize, report_from_data

GIB = 1024 ** 3
BUFFER = 1024 ** 2
SPARSE_MAGIC = 0xED26FF3A
PARTITION_SOURCES = {"SM-F741N": "hardware_target", "SM-F956N": "system_donor"}


def read_exact(stream, size):
    out = bytearray()
    while len(out) < size:
        block = stream.read(min(BUFFER, size - len(out)))
        if not block:
            raise ValueError("Truncated Samsung sparse/raw super image")
        out.extend(block)
    return bytes(out)


def copy_bounded(source, dest, size):
    while size:
        block = read_exact(source, min(size, BUFFER))
        dest.write(block)
        size -= len(block)


def decode_image_to_raw(source, dest, limit):
    """Convert a raw or sparse Android image to a RAW image without buffering it."""
    first = read_exact(source, 4)
    if int.from_bytes(first, "little") != SPARSE_MAGIC:
        dest.write(first)
        remaining = limit - 4
        if remaining < 0:
            raise ValueError("Raw image exceeds configured logical-size limit")
        while True:
            block = source.read(BUFFER)
            if not block:
                break
            if len(block) > remaining:
                raise ValueError("Raw image exceeds configured logical-size limit")
            dest.write(block)
            remaining -= len(block)
        return dest.tell(), False

    header = first + read_exact(source, 24)
    _, major, _minor, header_size, chunk_header_size, block_size, blocks, chunks, _crc = struct.unpack(
        "<IHHHHIIII", header
    )
    if major != 1 or not 28 <= header_size <= 4096 or not 12 <= chunk_header_size <= 4096:
        raise ValueError("Unsupported Android sparse header")
    if block_size not in (512, 1024, 2048, 4096, 8192, 16384) or blocks == 0:
        raise ValueError("Invalid sparse geometry")
    logical_size = block_size * blocks
    if logical_size > limit:
        raise ValueError(f"Super image size {logical_size} exceeds expected {limit}")
    read_exact(source, header_size - 28)
    accounted_blocks = 0
    for _ in range(chunks):
        kind, _reserved, nblocks, total_size = struct.unpack(
            "<HHII", read_exact(source, chunk_header_size)[:12]
        )
        expanded = nblocks * block_size
        accounted_blocks += nblocks
        if accounted_blocks > blocks:
            raise ValueError("Sparse chunks exceed logical image size")
        if kind == 0xCAC1:  # RAW
            if total_size != chunk_header_size + expanded:
                raise ValueError("Invalid RAW chunk size")
            copy_bounded(source, dest, expanded)
        elif kind == 0xCAC2:  # FILL
            if total_size != chunk_header_size + 4:
                raise ValueError("Invalid FILL chunk size")
            pattern = read_exact(source, 4)
            if pattern == bytes(4):
                dest.seek(expanded, os.SEEK_CUR)
            else:
                fill_block = pattern * (BUFFER // 4)
                while expanded:
                    count = min(expanded, len(fill_block))
                    dest.write(fill_block[:count])
                    expanded -= count
        elif kind == 0xCAC3:  # DONT_CARE
            if total_size != chunk_header_size:
                raise ValueError("Invalid DONT_CARE chunk")
            dest.seek(expanded, os.SEEK_CUR)
        elif kind == 0xCAC4:  # CRC
            if total_size != chunk_header_size + 4 or nblocks:
                raise ValueError("Invalid CRC chunk")
            read_exact(source, 4)
        else:
            raise ValueError(f"Unknown sparse chunk type 0x{kind:04x}")
    if accounted_blocks != blocks:
        raise ValueError("Sparse blocks do not match declared logical image size")
    dest.truncate(logical_size)
    return logical_size, True


def extract_super_to_raw(ap, raw_file, expected_bytes):
    """Read just one named TAR member and stream through system lz4."""
    with tarfile.open(ap, "r:") as archive:
        members = [m for m in archive if m.isfile() and Path(m.name).name == "super.img.lz4"]
        if len(members) != 1:
            raise ValueError(f"Exactly one super.img.lz4 required in {ap.name}")
        member = archive.extractfile(members[0])
        if member is None:
            raise ValueError("Unable to read super member")
        with member, open(raw_file, "xb") as dest:
            proc = subprocess.Popen(
                ["lz4", "-d", "-c", "-"],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL
            )
            errors = []

            def feed():
                try:
                    while True:
                        block = member.read(BUFFER)
                        if not block:
                            break
                        proc.stdin.write(block)
                except (OSError, BrokenPipeError, ValueError) as exc:
                    errors.append(str(exc))
                finally:
                    try:
                        proc.stdin.close()
                    except OSError:
                        pass

            worker = threading.Thread(target=feed, daemon=True)
            worker.start()
            try:
                size, sparse = decode_image_to_raw(proc.stdout, dest, expected_bytes)
                # A full stream read (rather than a prefix) checks LZ4 integrity.
                if proc.stdout.read(1):
                    raise ValueError("Unexpected data after sparse super image")
                exit_status = proc.wait()
                worker.join()
                if exit_status or errors:
                    raise ValueError(f"lz4 failed: exit={exit_status}, feeder={errors}")
                if size != expected_bytes:
                    raise ValueError(f"Super logical size mismatch: {size} != {expected_bytes}")
            finally:
                if proc.poll() is None:
                    proc.kill()
                proc.wait()
                proc.stdout.close()
                worker.join(timeout=2)
            return sparse


def select_parts(metadata, capacity, model):
    devices = {d["model"]: d for d in metadata["devices"]}
    device = devices.get(model)
    if device is None or device.get("checksums_valid") is not True:
        raise ValueError(f"Missing checked metadata for {model}")
    partitions = {
        normalize(p["name"]): p for p in device["partitions"]
    }
    selected = [
        (p["partition"], partitions[p["partition"]]["name"],
         p["current_image_bytes"]) for p in capacity["hybrid_partitions"]
        if p["source"] == model
    ]
    if not selected:
        raise ValueError(f"No images selected for {model}")
    if any(size <= 0 for _, _, size in selected):
        raise ValueError("Cannot extract zero-size partitions")
    devices_info = device.get("block_devices", [])
    if len(devices_info) != 1:
        raise ValueError("Expected one stock super block device; inspect actual layout")
    raw_size = devices_info[0]["size_bytes"]
    if not isinstance(raw_size, int) or not (1 * GIB < raw_size < 64 * GIB):
        raise ValueError("Unexpected physical super size")
    return selected, raw_size


def preflight(root, metadata_file, plan_file, model, destination):
    metadata = json.loads(metadata_file.read_text())
    plan = json.loads(plan_file.read_text())
    capacity = report_from_data(metadata, plan)
    if not capacity["capacity_estimate_pass"]:
        raise ValueError("Hybrid size estimate failed; refusing image extraction")
    parts, raw_size = select_parts(metadata, capacity, model)
    ap = locate_archive(root / "out/odin" / f"{model}_SKC", model, "AP")
    binaries = ["lz4", "lpunpack"]
    missing = [item for item in binaries if not shutil.which(item)]
    if missing:
        raise ValueError(f"Missing tools in PATH: {', '.join(missing)}; check out/tools/bin")
    if destination.exists() or destination.is_symlink():
        raise FileExistsError(f"Refusing to overwrite existing output: {destination}")
    parent = destination.parent
    if not parent.is_dir():
        parent = parent.parent
    disk = shutil.disk_usage(parent)
    selected_bytes = sum(size for _, _, size in parts)
    # Reserve one raw super image, all selected partition outputs and 4 GiB.
    # Dense allocation may differ; check real free bytes before operations.
    needed = raw_size + selected_bytes + 4 * GIB
    return {"model": model, "ap": ap, "parts": parts, "raw_size": raw_size,
            "selected_bytes": selected_bytes, "needed": needed, "free": disk.free,
            "destination": destination}


def extract_model(pre):
    if pre["free"] < pre["needed"]:
        raise ValueError(
            f"Not enough free space; requires at least {pre['needed']/GIB:.1f} GiB, "
            f"has {pre['free']/GIB:.1f} GiB"
        )
    dest = pre["destination"]
    dest.parent.mkdir(parents=True, exist_ok=True)
    # Stage on the same filesystem, then atomically publish all selected images.
    with tempfile.TemporaryDirectory(dir=dest.parent, prefix=f".{pre['model']}-stage-") as work:
        stage = Path(work)
        raw = stage / "super.raw.img"
        images = stage / "partitions"
        images.mkdir()
        print(f"Extracting stock super for {pre['model']} (no phone access)...", flush=True)
        extract_super_to_raw(pre["ap"], raw, pre["raw_size"])
        for label, physical, expected in pre["parts"]:
            print(f"Unpacking {pre['model']} {physical}...", flush=True)
            subprocess.run(["lpunpack", "-p", physical, str(raw), str(images)],
                           check=True)
            output = images / (physical + ".img")
            if not output.is_file() or output.is_symlink():
                raise ValueError(f"Missing lpunpack output: {output}")
            if output.stat().st_size != expected:
                raise ValueError(
                    f"{physical}: extracted bytes {output.stat().st_size} != {expected}"
                )
            if physical != label:
                output.rename(images / (label + ".img"))
        # No raw super image is stored in the published directory.
        manifest = {"status": "STOCK_IMAGES_ONLY_NOT_BUILDABLE",
                    "model": pre["model"], "source_ap": pre["ap"].name,
                    "partitions": [
                        {"partition": label, "source_partition": physical,
                         "bytes": size} for label, physical, size in pre["parts"]
                    ]}
        (images / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
        images.rename(dest)
    print(f"Stock images staged in {dest}. No ROM built and nothing flashed.", flush=True)


def main():
    project = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", choices=tuple(MODELS), required=True)
    parser.add_argument("--extract", action="store_true", help="Explicitly unpack large image files")
    parser.add_argument("--metadata", type=Path,
                        default=project / "out/reports/f741n-f956n-super-metadata.json")
    parser.add_argument("--plan", type=Path, default=project / "target/b6q/port-plan.json")
    parser.add_argument("--destination", type=Path, default=None)
    args = parser.parse_args()
    output = args.destination or project / "out/b6q/extracted" / args.model
    try:
        result = preflight(project, args.metadata, args.plan, args.model, output)
        print(f"{args.model}: selected {[p[0] for p in result['parts']]}")
        print(f"Super raw size: {result['raw_size']/GIB:.1f} GiB")
        print(f"Selected image total: {result['selected_bytes']/GIB:.1f} GiB")
        print(f"Required temporary+output space (with margin): {result['needed']/GIB:.1f} GiB")
        print(f"Free space on destination filesystem: {result['free']/GIB:.1f} GiB")
        if not args.extract:
            print("PREFLIGHT ONLY: no image files created. --extract is required to proceed.")
            return 0 if result["free"] >= result["needed"] else 2
        extract_model(result)
    except (OSError, ValueError, subprocess.CalledProcessError, tarfile.TarError) as exc:
        parser.exit(1, f"Extraction error: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
