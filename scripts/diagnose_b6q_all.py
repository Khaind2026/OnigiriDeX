#!/usr/bin/env python3
"""One-shot READ-ONLY Flip6 F741N / Fold6 F956N diagnostic bundle.

Inspects staged firmware/AVB/VINTF/DeX evidence on the local build host.
Produces one small ZIP with diagnostics, not firmware. Does not patch, sign,
repack, build Odin packages, or communicate with a phone.
"""
import argparse
import datetime
import json
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
MAX_REPORT_BYTES = 3 * 1024 * 1024
REPORT_PATHS = (
    "out/reports/f741n-f956n-odin-layout.json",
    "out/reports/f741n-f956n-super-metadata.json",
    "out/reports/f741n-f956n-stage-validation.json",
    "out/reports/f741n-f956n-framework-audit.json",
    "out/reports/f741n-f956n-dex-candidates.json",
    "out/b6q/analysis/f741n-avb-boot-readiness.json",
    "out/b6q/analysis/f741n-bl-avb-discovery.json",
    "out/b6q/analysis/f741n-bl-vbmeta-chain.json",
    "out/b6q/analysis/f741n-f956n-vintf-mount-triage.json",
    "out/b6q/analysis/f741n-f956n-vintf-mount-triage-v2.json",
    "out/b6q/analysis/f741n-boot-mount-avb-precheck.json",
)
TOOL_NAMES = ("python3", "git", "lz4", "avbtool", "dump.erofs",
              "extract.erofs", "apktool", "lpmake", "lpunpack", "checkvintf")
IMAGE_ORIGINS = {
    "SM-F956N": ("system", "product", "system_ext"),
    "SM-F741N": ("vendor", "odm", "system_dlkm", "vendor_dlkm"),
}


def safe_file(path: Path):
    return path.is_file() and not path.is_symlink()


def command(args, cwd, timeout=10):
    try:
        p = subprocess.run(args, cwd=cwd, capture_output=True, text=True,
                           timeout=timeout, check=False)
        return {"exit": p.returncode, "stdout": p.stdout.strip()[:1500],
                "stderr": p.stderr.strip()[:300]}
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"error": str(exc)[:300]}


def issue(section, detail):
    return {"section": section, "reason": str(detail)[:1500], "result": "UNKNOWN"}


def get_reports(root: Path):
    reports = {}
    included = {}
    for relative in REPORT_PATHS:
        path = root / relative
        if not safe_file(path):
            reports[relative] = {"status": "ABSENT"}
            continue
        size = path.stat().st_size
        if size > MAX_REPORT_BYTES:
            reports[relative] = {"status": "TOO_LARGE", "bytes": size}
            continue
        try:
            raw = path.read_bytes()
            document = json.loads(raw)
            if not isinstance(document, dict):
                raise ValueError("JSON root is not an object")
            reports[relative] = {
                "status": "INCLUDED", "bytes": size,
                "reported_status": document.get("status", "not supplied"),
                "flashable": document.get("flashable"),
            }
            included[relative] = raw
        except (OSError, UnicodeError, ValueError) as error:
            reports[relative] = {"status": "INVALID", "error": str(error)[:200]}
    return reports, included


def scan(root: Path):
    """Build in-memory report. Individual failures never abort other checks."""
    report = {
        "project": "DuyKhaiDeX F741N/F956N",
        "scope": "READ_ONLY_OFFLINE_DIAGNOSTICS_NOT_A_FLASH_APPROVAL",
        "target": "SM-F741N", "donor": "SM-F956N",
        "sections": {}, "limitations": [
            "No actual hardware boot/DeX/refresh-rate tests",
            "No cryptographic AVB signature/rollback validation",
            "No complete libvintf checkvintf, FCM version/instance or SKU/APEX validation",
            "No assembled init_boot/vendor_boot first-stage fstab boot verification",
            "No SELinux combined-policy load or allow/deny compatibility proof",
            "No assessment of flashability: DO NOT FLASH engineering preview",
        ]
    }
    sections = report["sections"]
    tooling = {}
    for name in TOOL_NAMES:
        found = shutil.which(name)
        if found is None and safe_file(root / "out/tools/bin" / name):
            found = str(root / "out/tools/bin" / name)
        tooling[name] = {"available": bool(found), "path": found}
    sections["tools"] = tooling

    repo_git = {
        "branch": command(["git", "branch", "--show-current"], root),
        "commit": command(["git", "rev-parse", "--short", "HEAD"], root),
        "working_tree": command(["git", "status", "--porcelain", "--untracked-files=no"], root),
    }
    sections["repository"] = repo_git

    try:
        free = shutil.disk_usage(root)
        sections["storage"] = {"free_gib": round(free.free / (1024 ** 3), 2),
                               "total_gib": round(free.total / (1024 ** 3), 2)}
    except OSError as error:
        sections["storage"] = issue("storage", error)

    staged = {}
    for model, parts in IMAGE_ORIGINS.items():
        folder = root / "out/b6q/extracted" / model
        staged[model] = {}
        for name in parts:
            file = folder / (name + ".img")
            staged[model][name] = {
                "present": safe_file(file),
                "bytes": file.stat().st_size if safe_file(file) else None,
            }
    sections["staged_partition_images"] = staged

    work = root / "out/target/b6q/SM-F741N/work_dir"
    marker_names = (".b6q-prepared", ".b6q-dex-patched", ".b6q-dex-attempted")
    sections["rom_work_tree"] = {
        "present": work.is_dir() and not work.is_symlink(),
        "markers": {m: safe_file(work / m) for m in marker_names},
        "origin_manifest_present": safe_file(work / "port-origin.json"),
    }

    try:
        from verify_b6q_stage import verify_all
        checked = verify_all(
            root, root / "out/reports/f741n-f956n-super-metadata.json",
            root / "target/b6q/port-plan.json", False)
        sections["stock_stage_validation"] = {
            "result": "OK_IMAGE_SIZE_AND_FS_ONLY",
            "models": [{"model": d["model"], "partitions": [
                {"partition": p["partition"], "filesystem": p["filesystem"]}
                for p in d["images"]]} for d in checked["devices"]],
        }
    except (OSError, ValueError, KeyError, TypeError, ImportError) as error:
        sections["stock_stage_validation"] = issue("stock_stage_validation", error)

    try:
        from analyze_b6q_avb import verify_stock_images, decode_vbmeta_header
        boot_folder = root / "out/b6q/analysis/f741n-stock-boot-chain"
        boot = verify_stock_images(boot_folder)
        vm = decode_vbmeta_header(boot_folder / "vbmeta_system.img")
        sections["boot_chain"] = {
            "result": "STOCK_IMAGE_HASHES_MATCH_STAGE_MANIFEST_NOT_BOOT_VERIFIED",
            "stock_images": [x["image"] for x in boot],
            "vbmeta_system_header": vm,
        }
    except (OSError, ValueError, KeyError, TypeError, ImportError) as error:
        sections["boot_chain"] = issue("boot_chain", error)

    try:
        from audit_b6q_vintf_mounts import analyze
        vintf = analyze(work)
        sections["vintf_mount_triage"] = vintf
    except (OSError, ValueError, KeyError, TypeError, ImportError) as error:
        sections["vintf_mount_triage"] = issue("vintf_mount_triage", error)

    # Try the official AOSP host libvintf check in the same one-shot pass.
    # Its missing binary is recorded as NOT_RUN, never a compatibility pass.
    try:
        from run_b6q_checkvintf import run_check
        host_binary = shutil.which("checkvintf")
        local_binary = root / "out/tools/bin/checkvintf"
        if not host_binary and safe_file(local_binary):
            host_binary = str(local_binary)
        sections["host_checkvintf"] = run_check(work, tool=host_binary)
    except (OSError, ValueError, KeyError, TypeError, ImportError) as error:
        sections["host_checkvintf"] = issue("host_checkvintf", error)

    try:
        from audit_b6q_boot_mount_gate import analyze as analyze_boot_mount
        sections["boot_mount_avb_precheck"] = analyze_boot_mount(
            root / "out/b6q/analysis/f741n-stock-boot-chain",
            work,
            root / "out/b6q/analysis/f741n-bl-vbmeta-chain.json",
        )
    except (OSError, ValueError, TypeError, KeyError, ImportError) as error:
        sections["boot_mount_avb_precheck"] = issue(
            "boot_mount_avb_precheck", error
        )

    prev_chain = root / "out/b6q/analysis/f741n-bl-vbmeta-chain.json"
    if safe_file(prev_chain):
        try:
            old = json.loads(prev_chain.read_text(encoding="utf-8"))
            sections["avb_descriptor_summary"] = {
                "result": "DESCRIPTORS_PARSED_SIGNATURES_NOT_VERIFIED",
                "chain_targets": old.get("stock_bl_vbmeta", {}).get("chain_targets"),
                "modified_partition_overlap": old.get("direct_system_hash_or_hashtree_overlap"),
                "flashable": False,
            }
        except (ValueError, OSError, TypeError) as error:
            sections["avb_descriptor_summary"] = issue("avb_descriptor_summary", error)
    else:
        sections["avb_descriptor_summary"] = issue(
            "avb_descriptor_summary", "Existing local BL vbmeta JSON report missing")

    preview = root / "out/b6q/build/DuyKhaiDeX_F741N_BRANDED_SUPER_PREVIEW_NOT_FOR_FLASH.img"
    sections["super_preview"] = {
        "present": safe_file(preview),
        "bytes": preview.stat().st_size if safe_file(preview) else None,
        "checksum_record_present": safe_file(Path(str(preview) + ".sha256")),
        "hash_recomputed": False,
        "flashable": False,
    }

    dex_report = root / "out/reports/f741n-f956n-dex-candidates.json"
    if safe_file(dex_report):
        try:
            dex = json.loads(dex_report.read_text(encoding="utf-8"))
            sections["dex_component_inventory"] = {
                "result": "CANDIDATE_LISTINGS_NOT_FUNCTIONAL_DEX_TESTS",
                "candidates": dex.get("candidate_listing_matches"),
            }
        except (OSError, ValueError) as error:
            sections["dex_component_inventory"] = issue("dex_component_inventory", error)
    else:
        sections["dex_component_inventory"] = issue(
            "dex_component_inventory", "Previous DeX candidate report not found")

    try:
        f = root / "out/b6q/port-logs"
        logs = [p for p in f.glob("DeX-replay-*.log") if safe_file(p)] if f.is_dir() else []
        latest = max(logs, key=lambda p: p.stat().st_mtime) if logs else None
        sections["dex_patch_log"] = {
            "present": latest is not None,
            "last_log_name": latest.name if latest else None,
            "last_log_tail": (latest.read_text(encoding="utf-8", errors="replace")[-16000:]
                              if latest and latest.stat().st_size <= MAX_REPORT_BYTES else None),
        }
    except OSError as error:
        sections["dex_patch_log"] = issue("dex_patch_log", error)

    try:
        all_reports, _ = get_reports(root)
        sections["existing_reports"] = all_reports
    except OSError as error:
        sections["existing_reports"] = issue("existing_reports", error)

    report["bootable"] = "NOT_VERIFIED"
    report["flashable"] = False
    return report


def summary_text(report):
    sections = report["sections"]
    vintf = sections["vintf_mount_triage"]
    if vintf.get("result") == "UNKNOWN":
        vf = "UNKNOWN: " + vintf["reason"]
    else:
        vf = ("target HAL names=" + str(len(vintf.get("device_manifest_hal_names", [])))
              + "; donor matrix files=" + str(vintf.get("framework_matrix_count", "?"))
              + "; donor required HAL names="
              + str(len(vintf.get("framework_required_hal_names", [])))
              + "; coverage=" + str(vintf.get("framework_hal_coverage", "?"))
              + "; missing-name candidates=" + str(
                  vintf.get("candidate_missing_hal_names_unverified")))
    markers = sections["rom_work_tree"]["markers"]
    return "\n".join([
        "DUYKHAIDEX F741N / F956N — ONE-SHOT OFFLINE DIAGNOSTIC",
        "Target: SM-F741N   Donor: SM-F956N",
        "VINTF: " + vf,
        "AVB: " + str(sections["avb_descriptor_summary"]),
        "AOSP host checkvintf: " + str(
            sections.get("host_checkvintf", {}).get("status", "UNKNOWN")
        ),
        "Boot/mount/AVB gate: " + str(
            sections.get("boot_mount_avb_precheck", {}).get("status", "UNKNOWN")
        ),
        "Boot: " + str(sections["boot_chain"].get("result", "UNKNOWN")),
        "Image stage: " + str(sections["stock_stage_validation"].get("result", "UNKNOWN")),
        "DeX work-tree flags: " + str(markers),
        "Super preview: " + ("present" if sections["super_preview"]["present"] else "absent"),
        "Read-only offline diagnostics only. No Odin AP. No firmware modified.",
        "BOOTABILITY: NOT VERIFIED. DO NOT FLASH THE SUPER PREVIEW.",
        "",
        "See summary.json and reports/* inside ZIP for evidence and limitations.",
    ]) + "\n"


def package(root, dest, report):
    if dest.exists() or dest.is_symlink():
        raise ValueError("Output already exists, refusing overwrite: " + str(dest))
    dest.parent.mkdir(parents=True, exist_ok=True)
    reports, included = get_reports(root)
    report["sections"]["existing_reports"] = reports
    with zipfile.ZipFile(dest, "x", compression=zipfile.ZIP_DEFLATED) as zipfile_out:
        zipfile_out.writestr("summary.txt", summary_text(report))
        zipfile_out.writestr("summary.json", json.dumps(report, ensure_ascii=False, indent=2) + "\n")
        for relative, raw in included.items():
            zipfile_out.writestr("reports/" + relative.replace("/", "__"), raw)
    return len(included)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args(argv)
    repo = args.repo_root.resolve()
    if not (repo / "scripts/audit_b6q_vintf_mounts.py").is_file():
        parser.exit(2, "Not a DuyKhaiDeX repository: " + str(repo) + "\n")
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
    dest = args.output or (repo / "out/b6q/diagnostics" /
                           ("DuyKhaiDeX_F741N_F956N_ALL_" + stamp + ".zip"))
    if not dest.is_absolute():
        dest = repo / dest
    sys.path.insert(0, str(repo / "scripts"))
    try:
        report = scan(repo)
        count = package(repo, dest, report)
    except (OSError, ValueError, zipfile.BadZipFile) as error:
        parser.exit(1, "Diagnostic bundle failed: " + str(error) + "\n")
    print(summary_text(report))
    print("Archived existing JSON reports:", count)
    print("FINAL DIAGNOSTIC ZIP:", dest)
    print("Upload this ONE ZIP in ChatGPT instead of screenshots.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
