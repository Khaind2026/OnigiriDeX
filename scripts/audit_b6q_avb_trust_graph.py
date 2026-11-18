#!/usr/bin/env python3
"""Read-only AVB trust graph for the F741N BL -> rebuilt F956N partitions.

Uses the already collected original F741N BL/AP vbmeta descriptor report.
Never signs, modifies, replaces, unlocks, disables verified boot or flashes.
A descriptor graph and an AVB0 header are NOT cryptographic signature proof.
"""
import argparse
import json
from pathlib import Path
import sys

from analyze_b6q_avb import decode_vbmeta_header
from run_b6q_checkvintf import checked_work_tree

TARGET = "SM-F741N"
DONOR = "SM-F956N"
CHANGED = {"system", "product", "system_ext"}
STOCK_BOOT = ("dtbo", "optics", "prism")


def audit(work, chain_path, stock_vbmeta_system=None):
    checked_work_tree(work)
    result = {
        "model": TARGET, "donor": DONOR,
        "phase": "ORIGINAL_F741N_AVB_DESCRIPTORS_VS_MODIFIED_F956N_PARTITIONS",
        "status": "UNKNOWN_STOCK_AVB_TRUST_GRAPH_NOT_AVAILABLE",
        "flashable": False, "bootable": False,
        "root_public_key_trusted_by_device": "NOT_VERIFIED",
        "root_signature_cryptographically_checked": False,
        "hybrid_partition_hashes_verified_against_stock": False,
        "rollback_policy_verified_on_device": False,
        "stock_root_metadata_can_authenticate_hybrid_as_is": "NOT_VERIFIED",
        "recommendation": "Do not flash or treat a rebuilt image as authenticated by original F741N BL vbmeta",
    }
    if chain_path.is_symlink() or not chain_path.is_file():
        return result
    data = json.loads(chain_path.read_text(encoding="utf-8"))
    if data.get("model") != TARGET or data.get("phase") != "READ_ONLY_STOCK_BL_VBMETA_CHAIN_INSPECTION":
        raise ValueError("Expected authentic source model and BL descriptor report")
    bl = data.get("stock_bl_vbmeta", {})
    descriptions = bl.get("descriptors")
    if not isinstance(descriptions, list) or not descriptions:
        return result
    root_hashtrees = set()
    root_hashes = set()
    chain = set()
    malformed = False
    for item in descriptions:
        if not isinstance(item, dict):
            malformed = True
            continue
        name, kind = item.get("partition"), item.get("type")
        if not isinstance(name, str) or not name:
            malformed = True
            continue
        if kind == "hashtree":
            root_hashtrees.add(name)
        elif kind == "hash":
            root_hashes.add(name)
        elif kind == "chain partition":
            chain.add(name)
        else:
            malformed = True
    overlap = sorted(CHANGED & (root_hashtrees | root_hashes))
    direct = {
        "modified_partition_set": sorted(CHANGED),
        "stock_bl_root_hashtree_partitions": sorted(root_hashtrees),
        "stock_bl_root_hash_partitions": sorted(root_hashes),
        "root_chain_targets": sorted(chain),
        "modified_partition_signed_descriptor_overlap": overlap,
        "vbmeta_system_is_bl_chain_target": "vbmeta_system" in chain,
        "stock_root_chain_targets_match_prior_snapshot": sorted(chain) ==
            sorted(bl.get("chain_targets", [])),
        "root_descriptor_count": len(descriptions),
        "malformed_descriptors": malformed,
    }
    result["trust_graph"] = direct
    header = bl.get("header", {}) if isinstance(bl.get("header"), dict) else {}
    result["root_header"] = {
        "algorithm_type": header.get("algorithm_type"),
        "rollback_index": header.get("rollback_index"),
        "rollback_index_location": header.get("rollback_index_location"),
        "flags": header.get("flags"),
        "signature_verified": False,
    }
    if stock_vbmeta_system and stock_vbmeta_system.is_file() and not stock_vbmeta_system.is_symlink():
        try:
            h = decode_vbmeta_header(stock_vbmeta_system)
            result["stock_vbmeta_system_header"] = {
                "algorithm_type": h["algorithm_type"],
                "rollback_index": h["rollback_index"],
                "signature_verified": False,
            }
        except (OSError, ValueError):
            result["stock_vbmeta_system_header"] = {"status": "UNKNOWN_UNPARSABLE"}
    if malformed or not direct["stock_root_chain_targets_match_prior_snapshot"]:
        result["status"] = "UNKNOWN_INCONSISTENT_STOCK_AVB_DESCRIPTORS"
    elif overlap:
        # Stock BL directly includes a signed descriptor for this partition:
        # flashing a re-created EROFS image cannot simply reuse stock
        # metadata, nor can patching AP vbmeta_system alone update the
        # existing top-level BL signature.
        result["status"] = "BLOCKED_STOCK_BL_ROOT_HASHTREE_COVERS_REBUILT_SYSTEM"
        result["stock_root_metadata_can_authenticate_hybrid_as_is"] = "NO_VALIDATION_PROVEN"
    else:
        result["status"] = "UNKNOWN_NO_DIRECT_OVERLAP_BUT_TRUST_UNPROVEN"
    result["remaining_proofs"] = [
        "Exact F741N device bootloader unlock/trust policy, not a property guess",
        "Cryptographic stock BL root vbmeta public-key and signature verification",
        "Fresh partition image verification against authoritative AVB metadata",
        "Rollback indices and device-specific recovery path",
    ]
    return result


def main(argv=None):
    repo = Path(__file__).resolve().parents[1]
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--work-dir", type=Path,
                     default=repo / "out/target/b6q/SM-F741N/work_dir")
    cli.add_argument("--chain", type=Path,
                     default=repo / "out/b6q/analysis/f741n-bl-vbmeta-chain.json")
    cli.add_argument("--stock-vbmeta-system", type=Path,
                     default=repo / "out/b6q/analysis/f741n-stock-boot-chain/vbmeta_system.img")
    cli.add_argument("--output", type=Path,
                     default=repo / "out/b6q/analysis/f741n-hybrid-avb-trust-graph.json")
    args = cli.parse_args(argv)
    try:
        if args.output.exists() or args.output.is_symlink():
            raise ValueError("Refusing to overwrite report")
        report = audit(args.work_dir, args.chain, args.stock_vbmeta_system)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    except (OSError, ValueError, TypeError, KeyError) as err:
        cli.exit(1, "AVB graph inspect failed: " + str(err) + "\n")
    print("F741N root BL AVB trust graph:", report["status"])
    print("Flash/boot NOT verified; no signatures or images changed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
