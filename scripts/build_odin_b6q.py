#!/usr/bin/env python3
"""Build a DuyKhaiDeX SM-F741N AP candidate from a verified stock AP and b6q super.

The stock F741N AP remains the container/boot-chain source. Only super.img.lz4 is
replaced. This does not resolve AVB or establish that the image is safe to flash.
"""
import argparse
import hashlib
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SUPER_NAMES = {"super.img", "super.img.lz4"}


def digest(path, algorithm):
    h = hashlib.new(algorithm)
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def verify_stock_ap(path):
    sys.path.insert(0, str(ROOT / "scripts"))
    from import_fw import verify_odin_package
    verify_odin_package(path)
    with tarfile.open(path, "r:") as archive:
        members = archive.getmembers()
        if not members or any(not x.isfile() for x in members):
            raise ValueError("Stock AP must contain regular image files only")
        names = [Path(x.name).name for x in members]
        if len(names) != len(set(names)):
            raise ValueError("Stock AP contains duplicate basenames")
        if not any(x in SUPER_NAMES for x in names):
            raise ValueError("Stock F741N AP has no super.img(.lz4)")
        required = {"boot.img.lz4", "init_boot.img.lz4", "vendor_boot.img.lz4",
                    "dtbo.img.lz4", "vbmeta.img.lz4", "recovery.img.lz4"}
        missing = required.difference(names)
        if missing:
            raise ValueError("F741N AP is missing expected target boot-chain members: " + ", ".join(sorted(missing)))
        return names


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("stock_ap", type=Path, help="verified SM-F741N AP_*.tar.md5")
    p.add_argument("super_img", type=Path, help="rebuilt F741N-geometry sparse super.img")
    p.add_argument("--output", type=Path, help="output .tar.md5; defaults to out/DuyKhaiDeX_AP_SM-F741N.tar.md5")
    args = p.parse_args()
    stock, super_img = args.stock_ap.resolve(), args.super_img.resolve()
    output = (args.output or ROOT / "out/DuyKhaiDeX_AP_SM-F741N.tar.md5").resolve()
    if not stock.is_file() or not super_img.is_file():
        p.error("stock AP and super image must exist")
    if stock == output or super_img == output or output.exists():
        p.error("output must be a new path distinct from inputs; refusing overwrite")
    output.parent.mkdir(parents=True, exist_ok=True)
    needed = stock.stat().st_size + super_img.stat().st_size + 1024**3
    if shutil.disk_usage(output.parent).free < needed:
        p.error(f"insufficient free space for staged AP packaging (need about {needed / 1024**3:.1f} GiB)")
    try:
        names = verify_stock_ap(stock)
        if Path(stock).name.startswith("AP_F956N"):
            raise ValueError("Refusing Fold6 AP as a container; the Odin boot chain must come from F741N")
        if not Path(stock).name.startswith("AP_F741N"):
            raise ValueError("Input AP filename must identify F741N")
        with tempfile.TemporaryDirectory(prefix=".b6q-ap-", dir=output.parent) as td:
            stage = Path(td)
            replacement = stage / "super.img.lz4"
            subprocess.run(["lz4", "-B6", "--content-size", "-12", str(super_img), str(replacement)], check=True)
            archive_path = stage / "candidate.tar"
            replacements = {name for name in names if Path(name).name in SUPER_NAMES}
            if len(replacements) != 1:
                raise ValueError("Stock AP must have exactly one super image")
            with tarfile.open(stock, "r:") as src, tarfile.open(archive_path, "w", format=tarfile.GNU_FORMAT) as dst:
                for member in src:
                    basename = Path(member.name).name
                    if basename in SUPER_NAMES:
                        info = tarfile.TarInfo("super.img.lz4")
                        info.mode, info.mtime = 0o644, member.mtime
                        info.size = replacement.stat().st_size
                        with replacement.open("rb") as payload:
                            dst.addfile(info, payload)
                    else:
                        payload = src.extractfile(member)
                        if payload is None:
                            raise ValueError("Cannot read stock AP member " + member.name)
                        dst.addfile(member, payload)
                        payload.close()
            with archive_path.open("rb") as f:
                md5 = hashlib.file_digest(f, "md5").hexdigest()
            with archive_path.open("ab") as f:
                f.write(f"{md5}  {output.name.removesuffix('.md5')}\n".encode())
            archive_path.rename(output)
        sys.path.insert(0, str(ROOT / "scripts"))
        from import_fw import verify_odin_package
        verify_odin_package(output)
        with tarfile.open(output, "r:") as archive:
            final_names = [Path(x.name).name for x in archive.getmembers()]
            if final_names.count("super.img.lz4") != 1 or any(x in final_names for x in ("super.img",)):
                raise ValueError("Output AP has an invalid super member")
            for name in ("boot.img.lz4", "init_boot.img.lz4", "vendor_boot.img.lz4", "dtbo.img.lz4", "vbmeta.img.lz4", "recovery.img.lz4"):
                if name not in final_names:
                    raise ValueError("Output AP lost F741N target member " + name)
        output.with_name(output.name + ".sha256").write_text(f"{digest(output, 'sha256')}  {output.name}\n")
        print(f"AP candidate built and archive/checksum-verified: {output}")
        print("Contents: original F741N AP boot chain + rebuilt b6q super image.")
        print("NOT FLASH-READY: AVB, boot, radio, camera, encryption and real-device boot remain unvalidated.")
    except (OSError, ValueError, tarfile.TarError, subprocess.CalledProcessError) as e:
        p.exit(1, f"AP build failed: {e}\n")


if __name__ == "__main__":
    main()
