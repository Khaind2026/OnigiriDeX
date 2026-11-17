#!/usr/bin/env python3
"""Summarize the user's local Fold6/Flip6 EROFS audit for DeX porting.

Consumes out/reports/f741n-f956n-framework-audit.json, NOT the large ROM
images. Reports candidate files and notable vendor/system compatibility
attributes. A directory listing match is NOT evidence the APK works.
"""
import argparse
import json
from pathlib import Path
import sys

CANDIDATES = {
    "KnoxDesktopLauncher": "system APK",
    "DesktopModeUiService": "system APK",
    "DesktopSystemUI": "system APK",
    "privapp-permissions-com.sec.android.app.desktoplauncher": "permission XML",
    "privapp-permissions-com.sec.android.desktopmode.uiservice": "permission XML",
    "privapp-permissions-com.sec.android.dexsystemui": "permission XML",
}
KEYWORDS = ("dex", "desktop", "hdmi", "external", "display", "window",
            "surfaceflinger", "systemui", "virtual")
PREFERRED_PROPS = (
    "ro.build.version.sdk", "ro.build.version.release",
    "ro.build.version.incremental", "ro.product.vendor.device",
    "ro.vendor.build.version.sdk", "ro.product.first_api_level",
    "ro.board.first_api_level",
)


def summarize(report):
    if report.get("status") != "ANALYSIS_ONLY_NO_ROM":
        raise ValueError("Not a DuyKhaiDeX framework audit report")
    models = {d.get("model"): d for d in report.get("devices", [])}
    if set(models) != {"SM-F741N", "SM-F956N"}:
        raise ValueError("Expected one Flip6 target and one Fold6 donor")

    result = {"status": "DE X_CANDIDATE_INVENTORY_NOT_ROM".replace(" ", ""),
              "candidate_listing_matches": {}, "relevant_names": {},
              "properties": {}, "vintf": {}, "caveat":
              "Only literal directory listing matches. Rebase/verify APK, "
              "framework, VINTF and SELinux before any b6q ROM build."}

    for model in ("SM-F956N", "SM-F741N"):
        model_data = models[model]
        if not isinstance(model_data.get("partitions"), list):
            raise ValueError(f"Invalid partitions for {model}")
        entries = []
        props = {}
        manifests = []
        for partition in model_data["partitions"]:
            name = partition.get("partition", "")
            props.update(partition.get("build_prop", {}).get("properties", {}))
            for location, record in partition.get("directory_probe", {}).items():
                if record.get("present"):
                    for line in record.get("matching_names", []):
                        if not isinstance(line, str):
                            continue
                        entries.append({"partition": name, "directory": location,
                                        "entry": line.strip()})
            for path, record in partition.get("vintf", {}).items():
                if record.get("parsed"):
                    manifests.append({
                        "partition": name, "path": path,
                        "target_level": record.get("target_level"),
                        "hal_count": record.get("hal_count"),
                        "graphics_and_display_hals": [
                            hal for hal in record.get("hal_names", [])
                            if any(key in hal.lower() for key in
                                   ("graphics", "display", "composer"))
                        ],
                    })
        result["properties"][model] = {k: props[k] for k in PREFERRED_PROPS if k in props}
        result["vintf"][model] = manifests
        result["relevant_names"][model] = [
            e for e in entries if any(keyword in e["entry"].lower() for keyword in KEYWORDS)
        ]
        result["candidate_listing_matches"][model] = {
            candidate: [e for e in entries if candidate.lower() in e["entry"].lower()]
            for candidate in CANDIDATES
        }
    return result


def format_summary(summary):
    lines = ["DuyKhaiDeX — Fold6/Flip6 DeX candidate inventory (read-only)"]
    for model in ("SM-F956N", "SM-F741N"):
        lines.append(f"\n{model}")
        for key, value in summary["properties"][model].items():
            lines.append(f"  {key}={value}")
        if model == "SM-F956N":
            lines.append("  Expected Fold5-source DeX components in Fold6 listings:")
            for name, matches in summary["candidate_listing_matches"][model].items():
                lines.append(
                    f"    {name}: " +
                    ("LISTED " + "; ".join(x["directory"] + ": " + x["entry"]
                                         for x in matches[:3])
                     if matches else "NOT SEEN (does not prove absent)")
                )
        lines.append("  DeX/display-related directory listing matches:")
        for entry in summary["relevant_names"][model][:65]:
            lines.append(f"    [{entry['partition']}] {entry['directory']}: {entry['entry']}")
        if not summary["relevant_names"][model]:
            lines.append("    None were captured by the initial audit")
        for vintf in summary["vintf"][model]:
            lines.append(f"  VINTF {vintf['partition']}:{vintf['path']} "
                         f"target_level={vintf['target_level']}, "
                         f"HAL count={vintf['hal_count']}")
            for hal in vintf["graphics_and_display_hals"]:
                lines.append(f"    HAL: {hal}")
    lines.append("\nOnly name evidence, not functional DeX or ROM compatibility.")
    return "\n".join(lines)


def main(argv=None):
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audit", type=Path,
                        default=root / "out/reports/f741n-f956n-framework-audit.json")
    parser.add_argument("--output", type=Path,
                        default=root / "out/reports/f741n-f956n-dex-candidates.json")
    args = parser.parse_args(argv)
    try:
        data = json.loads(args.audit.read_text())
        result = summarize(data)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    except (OSError, ValueError, KeyError, TypeError) as exc:
        parser.exit(1, f"DeX inventory error: {exc}\n")
    print(format_summary(result))
    print(f"\nCandidate JSON report: {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
