#!/usr/bin/env python3
"""Stage only essential Fold6 DeX APK/XML/JAR files for DuyKhaiDeX b6q research.

Default mode is read-only preflight against the existing JSON audit.
--extract copies whitelisted files from verified F956N system.img via
dump.erofs --cat, validates file types, and writes SHA-256 manifest in a NEW
local analysis directory. Does not modify source images, patch APKs, flash or
build an Android ROM. Original upstream credits and licensing stay intact.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
import zipfile

from plan_f741n_f956n_port import report_from_data
from verify_b6q_stage import verify_stage

MODEL = "SM-F956N"
LIMIT = 256 * 1024 * 1024
ASSETS = [
    ("KnoxDesktopLauncher.apk",
     "/system/priv-app/KnoxDesktopLauncher/KnoxDesktopLauncher.apk", "apk", True),
    ("DesktopModeUiService.apk",
     "/system/priv-app/DesktopModeUiService/DesktopModeUiService.apk", "apk", True),
    ("DesktopSystemUI.apk",
     "/system/priv-app/DesktopSystemUI/DesktopSystemUI.apk", "apk", True),
    ("privapp-permissions-desktoplauncher.xml",
     "/system/etc/permissions/privapp-permissions-com.sec.android.app.desktoplauncher.xml",
     "xml", True),
    ("privapp-permissions-desktopmode.xml",
     "/system/etc/permissions/privapp-permissions-com.sec.android.desktopmode.uiservice.xml",
     "xml", True),
    ("privapp-permissions-dexsystemui.xml",
     "/system/etc/permissions/privapp-permissions-com.sec.android.dexsystemui.xml",
     "xml", True),
    ("DesktopSystemUICoreLib.jar", "/system/framework/DesktopSystemUICoreLib.jar", "jar", False),
    ("DesktopSystemUIKnoxLib.jar", "/system/framework/DesktopSystemUIKnoxLib.jar", "jar", False),
]


def ensure_inventory(root):
    audit_path = root / "out/reports/f741n-f956n-framework-audit.json"
    audit = json.loads(audit_path.read_text())
    if audit.get("status") != "ANALYSIS_ONLY_NO_ROM":
        raise ValueError("Invalid original read-only framework audit report")
    devices = {d.get("model"): d for d in audit.get("devices", [])}
    if set(devices) != {MODEL, "SM-F741N"}:
        raise ValueError("Expected F956N donor and F741N target in audit")
    system = next((p for p in devices[MODEL]["partitions"]
                   if p.get("partition") == "system"), None)
    vendor = next((p for p in devices["SM-F741N"]["partitions"]
                   if p.get("partition") == "vendor"), None)
    if not system or not vendor:
        raise ValueError("Missing required donor system or target vendor")
    if system.get("build_prop", {}).get("properties", {}).get("ro.build.version.sdk") != "35":
        raise ValueError("Fold6 donor is not confirmed SDK 35")
    if vendor.get("build_prop", {}).get("properties", {}).get("ro.product.vendor.device") != "b6q":
        raise ValueError("Target vendor is not confirmed b6q")
    lists = system.get("directory_probe", {})
    not_seen = []
    for _, path, _, required in ASSETS:
        folder, basename = path.rsplit("/", 1)
        if folder.endswith((
            "/KnoxDesktopLauncher", "/DesktopModeUiService", "/DesktopSystemUI"
        )):
            folder = folder.rsplit("/", 1)[0]
            basename = folder and path.split("/")[-2]  # listing contains APK directory
        matches = lists.get(folder, {}).get("matching_names", [])
        if not any(basename.lower() in line.lower() for line in matches):
            if required:
                not_seen.append(path)
    if not_seen:
        raise ValueError("Required DeX source names not confirmed in audit:\n"
                         + "\n".join(not_seen))
    metadata = json.loads((root / "out/reports/f741n-f956n-super-metadata.json").read_text())
    plan = json.loads((root / "target/b6q/port-plan.json").read_text())
    capacity = report_from_data(metadata, plan)
    verify_stage(root / "out/b6q/extracted" / MODEL, MODEL, capacity)
    return root / "out/b6q/extracted" / MODEL / "system.img"


def inspect_type(path, kind):
    if kind in ("apk", "jar"):
        if not zipfile.is_zipfile(path):
            raise ValueError(f"Expected ZIP-based {kind} archive: {path}")
        with zipfile.ZipFile(path) as archive:
            if not archive.namelist():
                raise ValueError(f"Empty {kind} archive: {path}")
    elif kind == "xml":
        with path.open("rb") as stream:
            ET.parse(stream)


def copy_from_erofs(binary, image, source_path, output):
    """Read binary stdout in chunks and cap total bytes (no shell and no patching)."""
    with tempfile.TemporaryFile() as errors, output.open("xb") as file:
        process = subprocess.Popen(
            [binary, "--cat", f"--path={source_path}", str(image)],
            stdout=subprocess.PIPE, stderr=errors
        )
        digest = hashlib.sha256()
        size = 0
        try:
            while True:
                part = process.stdout.read(1024 * 1024)
                if not part:
                    break
                size += len(part)
                if size > LIMIT:
                    raise ValueError(f"Asset exceeds maximum {LIMIT} bytes: {source_path}")
                digest.update(part)
                file.write(part)
            status = process.wait()
        finally:
            if process.poll() is None:
                process.kill()
            process.wait()
            process.stdout.close()
        errors.seek(0)
        error_text = errors.read(2048).decode("utf-8", "replace").strip()
        if status != 0:
            raise ValueError(f"Read failed ({status}) for {source_path}: {error_text}")
        if size == 0:
            raise ValueError(f"Empty DeX asset: {source_path}")
        return {"bytes": size, "sha256": digest.hexdigest()}


def extract(binary, image, destination):
    if destination.exists() or destination.is_symlink():
        raise FileExistsError(f"Refusing to replace existing DeX assets: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".fold6-dex-", dir=destination.parent) as tmp:
        temporary = Path(tmp)
        gathered = []
        for name, path, kind, required in ASSETS:
            candidate = temporary / name
            try:
                record = copy_from_erofs(binary, image, path, candidate)
                inspect_type(candidate, kind)
            except (OSError, ValueError, ET.ParseError, zipfile.BadZipFile) as error:
                candidate.unlink(missing_ok=True)
                if required:
                    raise ValueError(f"Required source asset failed: {path}: {error}") from error
                gathered.append({"name": name, "source_path": path, "required": False,
                                 "status": "NOT_EXTRACTED", "reason": str(error)})
                continue
            gathered.append({"name": name, "source_path": path, "required": required,
                             "kind": kind, "status": "COPIED", **record})
            print(f"Copied {name} ({record['bytes']} bytes)", flush=True)

        report = {"status": "FOLD6_SOURCE_DEX_ASSETS_ONLY_NOT_PATCHED",
                  "model": MODEL, "source_image": str(image),
                  "files": gathered, "notice": "No phone access, ROM build or flashing."}
        (temporary / "manifest.json").write_text(json.dumps(report, indent=2) + "\n")
        temporary.rename(destination)
    return report


def main(argv=None):
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--extract", action="store_true",
                        help="Copy only approved assets into new local analysis directory")
    parser.add_argument("--dump-tool", default=None, help="Exact dump.erofs executable path")
    parser.add_argument("--destination", type=Path,
                        default=root / "out/b6q/analysis/fold6-dex-assets")
    args = parser.parse_args(argv)
    try:
        image = ensure_inventory(root)
        binary = args.dump_tool or shutil.which("dump.erofs")
        if not binary:
            raise ValueError("Cannot find dump.erofs: export PATH=\"$PWD/out/tools/bin:$PATH\"")
        if args.destination.exists() or args.destination.is_symlink():
            raise FileExistsError(f"Output already exists: {args.destination}")
        print("Fold6 DeX: 6 required APK/XML files and 2 optional JAR files.")
        print(f"Source: {image}")
        if not args.extract:
            print("PREFLIGHT PASS: no files copied. Run with --extract to stage assets.")
            return 0
        manifest = extract(binary, image, args.destination)
        copied = sum(entry["status"] == "COPIED" for entry in manifest["files"])
        print(f"Source assets copied and hashed: {copied}/{len(ASSETS)}")
        print(f"Local output: {args.destination}")
        print("No APK patched, no ROM built or flashed.")
        return 0
    except (OSError, ValueError, KeyError, TypeError) as error:
        parser.exit(1, f"DeX asset staging failed: {error}\n")


if __name__ == "__main__":
    sys.exit(main())
