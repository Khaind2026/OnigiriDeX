#!/usr/bin/env python3
"""Read-only One UI 7 / Samsung DeX compatibility inventory for F956N -> F741N.

Uses staged, checked EROFS images. Reads small build.prop and VINTF files via
'dump.erofs --cat' and lists selected framework/app directories via '--ls'.
Does NOT extract entire images, patch frameworks, build a ROM, or flash.
"""
import argparse
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET

from plan_f741n_f956n_port import report_from_data
from verify_b6q_stage import verify_stage

PARTITIONS = {
    "SM-F956N": ("system", "product", "system_ext"),
    "SM-F741N": ("vendor", "odm", "system_dlkm", "vendor_dlkm"),
}
PROP_KEYS = (
    "ro.build.version.sdk", "ro.build.version.release",
    "ro.build.version.incremental", "ro.product.model",
    "ro.product.device", "ro.product.vendor.model",
    "ro.product.vendor.device", "ro.vendor.build.version.sdk",
    "ro.vendor.build.version.release", "ro.product.first_api_level",
    "ro.board.first_api_level", "ro.vndk.version",
)
PROPERTY_PATHS = {
    "system": ("/system/build.prop", "/build.prop", "/system/system/build.prop"),
    "product": ("/build.prop", "/product/build.prop"),
    "system_ext": ("/build.prop", "/system_ext/build.prop"),
    "vendor": ("/build.prop", "/vendor/build.prop"),
    "odm": ("/build.prop", "/odm/build.prop"),
}
VINTF_PATHS = ("/etc/vintf/manifest.xml", "/etc/vintf/compatibility_matrix.xml")
DIRECTORIES = {
    "system": ("/system/priv-app", "/system/app", "/system/framework",
               "/system/etc/permissions", "/system/etc/sysconfig"),
    "product": ("/priv-app", "/app", "/etc/permissions", "/etc/sysconfig"),
    "system_ext": ("/priv-app", "/app", "/etc/permissions"),
    "vendor": ("/etc/vintf", "/etc/vintf/manifest", "/etc/init", "/lib64/hw"),
    "odm": ("/etc/vintf", "/etc/vintf/manifest"),
}
RELEVANT = re.compile(r"dex|desktop|display|systemui|sem|knox|multiwindow|freeform|"
                      r"window|external|hdmi|virtual", re.I)
MAX_CAPTURE = 2 * 1024 * 1024


def dump_tool(binary, image, operation, path):
    command = [binary, operation, f"--path={path}", str(image)]
    try:
        completed = subprocess.run(command, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, timeout=45, check=False)
    except subprocess.TimeoutExpired:
        return None, "command timeout"
    if completed.returncode:
        message = completed.stderr.decode("utf-8", errors="replace").strip()
        return None, message[-400:] or f"exit code {completed.returncode}"
    if len(completed.stdout) > MAX_CAPTURE:
        return None, f"output exceeds {MAX_CAPTURE} byte safety limit"
    return completed.stdout, None


def try_file(binary, image, alternatives):
    misses = []
    for path in alternatives:
        content, error = dump_tool(binary, image, "--cat", path)
        if error is None:
            return path, content, []
        misses.append({"path": path, "error": error})
    return None, None, misses


def properties(raw):
    found = {}
    for line in raw.decode("utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key in PROP_KEYS:
            found[key] = value
    return found


def vintf_summary(raw):
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as error:
        return {"parsed": False, "error": str(error)}
    hals = []
    for node in root.findall(".//hal"):
        name = node.findtext("name")
        if name:
            hals.append(name)
    return {
        "parsed": True,
        "root": root.tag,
        "target_level": root.attrib.get("target-level"),
        "hal_count": len(hals),
        "hal_names": sorted(set(hals))[:120],
    }


def scan_model(root, model, binary, capacity):
    folder = root / "out/b6q/extracted" / model
    verify_stage(folder, model, capacity)
    partitions = []
    for part in PARTITIONS[model]:
        image = folder / f"{part}.img"
        report = {"partition": part, "image_bytes": image.stat().st_size}
        if part in PROPERTY_PATHS:
            selected, payload, failures = try_file(binary, image, PROPERTY_PATHS[part])
            report["build_prop"] = {"source_path": selected,
                                    "properties": properties(payload) if payload else {},
                                    "not_found": failures if selected is None else []}
        if part in ("system", "product", "system_ext", "vendor", "odm"):
            vintf = {}
            for path in VINTF_PATHS:
                payload, error = dump_tool(binary, image, "--cat", path)
                if error is None:
                    vintf[path] = vintf_summary(payload)
                else:
                    vintf[path] = {"present": False, "reason": error}
            report["vintf"] = vintf
        listings = {}
        for path in DIRECTORIES.get(part, ()):
            raw, error = dump_tool(binary, image, "--ls", path)
            if error is None:
                lines = raw.decode("utf-8", errors="replace").splitlines()
                hits = [line.strip() for line in lines if RELEVANT.search(line)]
                listings[path] = {"present": True, "lines": len(lines),
                                  "matching_names": hits[:75]}
            else:
                listings[path] = {"present": False, "reason": error}
        report["directory_probe"] = listings
        partitions.append(report)
    return {"model": model, "partitions": partitions}


def run(root, binary):
    metadata = json.loads((root / "out/reports/f741n-f956n-super-metadata.json").read_text())
    plan = json.loads((root / "target/b6q/port-plan.json").read_text())
    capacity = report_from_data(metadata, plan)
    if not capacity["capacity_estimate_pass"]:
        raise ValueError("Target group capacity estimate has failed")
    help_text = subprocess.run([binary, "--help"], capture_output=True, text=True,
                               timeout=15, check=False)
    help_output = help_text.stdout + help_text.stderr
    if "--cat" not in help_output or "--ls" not in help_output or "--path" not in help_output:
        raise ValueError("dump.erofs build lacks --cat/--ls/--path support. Run 'dump.erofs --help'")
    devices = [scan_model(root, model, binary, capacity) for model in PARTITIONS]
    return {"status": "ANALYSIS_ONLY_NO_ROM", "devices": devices,
            "notice": "Only selected stock properties, VINTF and directory names; "
                      "DeX activation/compatibility not yet established."}


def main(argv=None):
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dump-tool", default=None, help="Path to dump.erofs")
    parser.add_argument("--output", type=Path,
                        default=root / "out/reports/f741n-f956n-framework-audit.json")
    args = parser.parse_args(argv)
    binary = args.dump_tool or shutil.which("dump.erofs")
    if not binary:
        parser.exit(1, "Missing dump.erofs. Export PATH=\"$PWD/out/tools/bin:$PATH\" first.\n")
    try:
        result = run(root, binary)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
        parser.exit(1, f"Audit failed: {exc}\n")
    for device in result["devices"]:
        print(device["model"])
        for partition in device["partitions"]:
            name = partition["partition"]
            props = partition.get("build_prop", {}).get("properties", {})
            print(f"  {name}: {len(props)} selected build properties")
            for key in ("ro.build.version.sdk", "ro.product.vendor.device",
                        "ro.vendor.build.version.sdk"):
                if key in props:
                    print(f"    {key}={props[key]}")
            for folder, entry in partition["directory_probe"].items():
                if entry["present"]:
                    print(f"    {folder}: {len(entry['matching_names'])} relevant names")
    print(f"Audit report: {args.output}")
    print("No images modified; no b6q ROM built or flashed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
