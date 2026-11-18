"""Synthetic tests for F741N vendor_boot to vendor filesystem fstab comparison."""
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from compare_b6q_first_stage_fstab import evaluate, PARTITIONS


def entry(name, fs="erofs", avb=True):
    return {"mountpoint": "/" + name, "fs_type": fs, "logical": True,
            "first_stage_mount": True, "avb": avb}


def evidence():
    vendor = {p: {"variants": [entry(p)]} for p in PARTITIONS}
    ram = [entry(p) for p in PARTITIONS]
    for name in ("system", "system_dlkm"):
        for fs in ("f2fs", "ext4"):
            vendor[name]["variants"].append(entry(name, fs))
            ram.append(entry(name, fs))
    return {
        "boot_mount_avb_precheck": {
            "model": "SM-F741N",
            "status": "BOOT_MOUNT_LAYOUT_INSPECTED_FULL_VERIFICATION_PENDING",
            "target_fstab": {"partitions": vendor},
        },
        "stock_ramdisk_content": {
            "model": "SM-F741N", "ramdisks": [
                {"source": "init_boot.img", "status": "CPIO_INSPECTED",
                 "first_stage_fstab_dynamic_entries": []},
                {"source": "vendor_boot.img/fragment_0", "status": "CPIO_INSPECTED",
                 "first_stage_fstab_dynamic_entries": ram},
            ]
        },
    }


class MatchTests(unittest.TestCase):
    def test_actual_shape_7_partitions_11_rules_match(self):
        r = evaluate(evidence())
        self.assertEqual(r["status"], "MATCHED_STRUCTURE_ONLY_NOT_BOOT_VERIFIED")
        self.assertEqual(r["matching_partition_count"], 7)
        self.assertEqual(r["unique_rule_variants_compared"], 11)
        self.assertFalse(r["bootable"])
        self.assertFalse(r["flashable"])

    def test_one_changed_avb_flag_is_mismatch(self):
        d = evidence()
        for e in d["stock_ramdisk_content"]["ramdisks"][1]["first_stage_fstab_dynamic_entries"]:
            if e["mountpoint"] == "/odm":
                e["avb"] = False
        r = evaluate(d)
        self.assertEqual(r["status"], "DIFFERENT_OR_MISSING_FIRST_STAGE_FSTAB_RULES")
        self.assertEqual(r["mismatched_partitions"], ["odm"])
        self.assertFalse(r["flashable"])

    def test_missing_vendor_ramdisk_not_passed(self):
        d = evidence()
        d["stock_ramdisk_content"]["ramdisks"][1]["status"] = "INSPECTION_ERROR"
        r = evaluate(d)
        self.assertEqual(r["status"], "UNKNOWN_INSUFFICIENT_FSTAB_EVIDENCE")
        self.assertFalse(r["flashable"])

    def test_missing_one_partition_not_passed(self):
        d = evidence()
        d["stock_ramdisk_content"]["ramdisks"][1]["first_stage_fstab_dynamic_entries"] = [
            e for e in d["stock_ramdisk_content"]["ramdisks"][1]["first_stage_fstab_dynamic_entries"]
            if e["mountpoint"] != "/system_ext"]
        r = evaluate(d)
        self.assertEqual(r["mismatched_partitions"], ["system_ext"])
        self.assertFalse(r["bootable"])

    def test_wrong_model_does_not_pass(self):
        d = evidence()
        d["boot_mount_avb_precheck"]["model"] = "SM-F956N"
        self.assertEqual(evaluate(d)["status"], "UNKNOWN_INSUFFICIENT_FSTAB_EVIDENCE")


if __name__ == "__main__":
    unittest.main()
