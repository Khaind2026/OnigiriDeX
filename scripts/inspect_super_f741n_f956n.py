#!/usr/bin/env python3
"""DuyKhaiDeX F741N/F956N: inspect LP metadata without unpacking giant super images.

Streams only the start of super.img.lz4 from the checksum-verified Odin AP.
Supports Android sparse and raw images. Requires 'lz4' on PATH.
Read-only: creates a small JSON report, never changes firmware or flashes.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import struct
import subprocess
import tarfile
import threading

from inspect_f741n_f956n_archives import MODELS, locate_archive

LIMIT = 4 * 1024 * 1024
SPARSE_MAGIC = 0xED26FF3A
GEOMETRY_MAGIC = 0x616C4467
HEADER_MAGIC = 0x414C5030


def read_exact(stream, n):
    buf = bytearray()
    while len(buf) < n:
        part = stream.read(n - len(buf))
        if not part:
            raise ValueError("Compressed stream ended early")
        buf.extend(part)
    return bytes(buf)


def image_prefix(stream, limit=LIMIT):
    """Decode the first logical bytes, not the whole sparse super partition."""
    first = read_exact(stream, 4)
    if int.from_bytes(first, "little") != SPARSE_MAGIC:
        buf = bytearray(first)
        while len(buf) < limit:
            chunk = stream.read(limit - len(buf))
            if not chunk:
                break
            buf.extend(chunk)
        return bytes(buf), False

    hdr = first + read_exact(stream, 24)
    _, major, _, file_hdr, chunk_hdr, block, blocks, chunks, _ = struct.unpack("<IHHHHIIII", hdr)
    if major != 1 or not 28 <= file_hdr <= 4096 or not 12 <= chunk_hdr <= 4096:
        raise ValueError("Unsupported Android sparse format")
    if block not in (512, 1024, 2048, 4096, 8192, 16384) or blocks == 0:
        raise ValueError("Invalid sparse block size")
    read_exact(stream, file_hdr - 28)
    out = bytearray()
    for _ in range(chunks):
        if len(out) >= limit:
            break
        kind, _, nblocks, total = struct.unpack("<HHII", read_exact(stream, chunk_hdr)[:12])
        expanded = nblocks * block
        count = min(expanded, limit - len(out))
        if kind == 0xCAC1:  # raw
            if total != chunk_hdr + expanded:
                raise ValueError("Invalid sparse RAW chunk")
            out.extend(read_exact(stream, count))
        elif kind == 0xCAC2:  # fill
            if total != chunk_hdr + 4:
                raise ValueError("Invalid sparse FILL chunk")
            fill = read_exact(stream, 4)
            out.extend((fill * ((count + 3) // 4))[:count])
        elif kind == 0xCAC3:  # don't care
            if total != chunk_hdr:
                raise ValueError("Invalid sparse empty chunk")
            out.extend(bytes(count))
        elif kind == 0xCAC4:  # CRC chunk
            if total != chunk_hdr + 4 or nblocks:
                raise ValueError("Invalid sparse CRC chunk")
            read_exact(stream, 4)
        else:
            raise ValueError(f"Unknown sparse chunk: {kind:04x}")
    return bytes(out), True


def cstring(buf):
    return buf.split(b"\x00", 1)[0].decode("utf-8", errors="replace")


def logical_partitions(prefix):
    geom = None
    for off in (4096, 8192):
        if len(prefix) < off + 52 or struct.unpack_from("<I", prefix, off)[0] != GEOMETRY_MAGIC:
            continue
        size = struct.unpack_from("<I", prefix, off + 4)[0]
        if not 52 <= size <= 4096 or off + size > len(prefix):
            continue
        record = bytearray(prefix[off:off + size])
        saved = bytes(record[8:40])
        record[8:40] = bytes(32)
        if hashlib.sha256(record).digest() != saved:
            continue
        maxsize, slots, blocksize = struct.unpack_from("<III", prefix, off + 40)
        if not 4096 <= maxsize <= LIMIT or not 1 <= slots <= 8:
            raise ValueError("Invalid LP geometry")
        geom = {"metadata_max_size": maxsize, "metadata_slots": slots,
                "logical_block_size": blocksize}
        break
    if geom is None:
        raise ValueError("LP geometry not found / SHA256 invalid")

    off = 12288  # 4096 reserved + 4096 primary and 4096 backup geometry.
    if len(prefix) < off + 128:
        raise ValueError("Missing LP metadata header")
    magic, major, minor, header_size = struct.unpack_from("<IHHI", prefix, off)
    if magic != HEADER_MAGIC or major not in (1, 2) or not 128 <= header_size <= 4096:
        raise ValueError("Unexpected LP primary metadata header (slot 0)")
    hdr = bytearray(prefix[off:off + header_size])
    if len(hdr) != header_size:
        raise ValueError("Short LP header")
    saved = bytes(hdr[12:44])
    hdr[12:44] = bytes(32)
    if hashlib.sha256(hdr).digest() != saved:
        raise ValueError("LP header SHA256 invalid")
    table_size = struct.unpack_from("<I", prefix, off + 44)[0]
    if header_size + table_size > geom["metadata_max_size"]:
        raise ValueError("LP tables exceed metadata slot size")
    tables = prefix[off + header_size:off + header_size + table_size]
    if len(tables) != table_size or hashlib.sha256(tables).digest() != prefix[off + 48:off + 80]:
        raise ValueError("LP table SHA256 invalid")

    def entries(index, minimum):
        start, count, stride = struct.unpack_from("<III", prefix, off + 80 + index * 12)
        if stride < minimum or count > 100000 or start + count * stride > len(tables):
            raise ValueError(f"Invalid table descriptor {index}")
        return [tables[start + i * stride:start + (i + 1) * stride] for i in range(count)]

    partitions = entries(0, 52)
    extents = entries(1, 24)
    groups = []
    for rec in entries(2, 48):
        flags, capacity = struct.unpack_from("<IQ", rec, 36)
        groups.append({"name": cstring(rec[:36]), "maximum_bytes": capacity,
                       "flags": flags})
    devices = []
    for rec in entries(3, 64):
        sector, align, offset, size = struct.unpack_from("<QIIQ", rec, 0)
        devices.append({"name": cstring(rec[24:60]), "size_bytes": size,
                        "first_logical_sector": sector})
    parts = []
    for rec in partitions:
        attrs, first, count, group = struct.unpack_from("<IIII", rec, 36)
        if group >= len(groups) or first + count > len(extents):
            raise ValueError("Bad LP partition extent/group reference")
        sectors = sum(struct.unpack_from("<Q", extents[i], 0)[0]
                      for i in range(first, first + count))
        parts.append({"name": cstring(rec[:36]), "group": groups[group]["name"],
                      "bytes": sectors * 512, "extents": count, "attributes": attrs})
    return {"geometry": geom, "header_version": f"{major}.{minor}",
            "groups": groups, "partitions": parts, "block_devices": devices,
            "checksums_valid": True}


def prefix_from_ap(ap):
    if not shutil.which("lz4"):
        raise ValueError("Missing 'lz4' executable. Install: sudo apt install lz4")
    with tarfile.open(ap, mode="r:") as archive:
        members = [m for m in archive if m.isfile() and Path(m.name).name == "super.img.lz4"]
        if len(members) != 1:
            raise ValueError("Expected exactly one super.img.lz4 in " + ap.name)
        source = archive.extractfile(members[0])
        if source is None:
            raise ValueError("Cannot access compressed super image")
        with source:
            process = subprocess.Popen(["lz4", "-dc", "-"], stdin=subprocess.PIPE,
                                       stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
            stop = threading.Event()

            def feed():
                try:
                    while not stop.is_set():
                        block = source.read(512 * 1024)
                        if not block:
                            break
                        process.stdin.write(block)
                except (BrokenPipeError, OSError, ValueError):
                    pass  # Expected when the prefix is read and lz4 is killed.
                finally:
                    try:
                        process.stdin.close()
                    except OSError:
                        pass

            worker = threading.Thread(target=feed, daemon=True)
            worker.start()
            try:
                return image_prefix(process.stdout)
            finally:
                stop.set()
                if process.poll() is None:
                    process.kill()
                process.wait()
                process.stdout.close()
                worker.join(timeout=2)


def inspect(root, selected):
    devices = []
    for model in selected:
        folder = root / (model + "_SKC")
        ap = locate_archive(folder, model, "AP")
        prefix, sparse = prefix_from_ap(ap)
        metadata = logical_partitions(prefix)
        devices.append({"model": model, "role": MODELS[model]["role"],
                        "source": ap.name, "sparse": sparse, **metadata})
    return {"status": "super_metadata_only_no_full_extraction", "devices": devices,
            "warning": "Never flash donor Fold6 low-level partitions to Flip6."}


def main():
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--odin-root", type=Path, default=root / "out/odin")
    parser.add_argument("--model", choices=("both", *MODELS), default="both")
    parser.add_argument("--output", type=Path,
                        default=root / "out/reports/f741n-f956n-super-metadata.json")
    args = parser.parse_args()
    try:
        selected = list(MODELS) if args.model == "both" else [args.model]
        result = inspect(args.odin_root, selected)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    except (OSError, ValueError, tarfile.TarError, struct.error) as exc:
        parser.exit(1, f"Error: {exc}\n")
    for device in result["devices"]:
        print(f"{device['model']}: LP {device['header_version']}, "
              f"{len(device['partitions'])} partitions; sparse={device['sparse']}")
        for group in device["groups"]:
            print(f"  group {group['name']} max={group['maximum_bytes']}")
        for part in device["partitions"]:
            print(f"  {part['name']} {part['bytes']} bytes [{part['group']}]")
    print(f"Report: {args.output}")
    print("No full image extracted, built or flashed.")


if __name__ == "__main__":
    main()
