"""Offline tests for the b6q Fold6-system/Flip6-hardware capacity estimate."""
import unittest

from scripts.plan_f741n_f956n_port import report_from_data

SOURCES = {
    "system": "SM-F956N",
    "product": "SM-F956N",
    "system_ext": "SM-F956N",
    "vendor": "SM-F741N",
    "odm": "SM-F741N",
    "system_dlkm": "SM-F741N",
    "vendor_dlkm": "SM-F741N",
}
TARGET_PARTITIONS = {
    "system": 8000000000,
    "product": 1200000000,
    "system_ext": 140000000,
    "vendor": 1800000000,
    "odm": 1048576,
    "system_dlkm": 15000000,
    "vendor_dlkm": 30000000,
}
DONOR_PARTITIONS = {
    "system": 8050000000,
    "product": 1230000000,
    "system_ext": 147000000,
    "vendor": 1900000000,
    "odm": 1048576,
    "system_dlkm": 15000000,
    "vendor_dlkm": 30000000,
}


def model_meta(model, sizes, maximum):
    return {
        "model": model,
        "role": "hardware_target" if model == "SM-F741N" else "system_donor",
        "checksums_valid": True,
        "header_version": "10.0",
        "groups": [{"name": "default", "maximum_bytes": 0},
                   {"name": "qti_dynamic_partitions", "maximum_bytes": maximum}],
        "partitions": [
            {"name": name, "bytes": value, "group": "qti_dynamic_partitions"}
            for name, value in sizes.items()
        ],
    }


def model_input():
    return {
        "devices": [
            model_meta("SM-F741N", TARGET_PARTITIONS, 13837008896),
            model_meta("SM-F956N", DONOR_PARTITIONS, 13941866496),
        ]
    }


def port_plan():
    return {"status": "ANALYSIS_ONLY_NOT_FLASHABLE",
            "system_partition_sources": SOURCES.copy()}


class HybridCapacityTests(unittest.TestCase):
    def test_systems_from_fold6_hardware_from_flip6(self):
        result = report_from_data(model_input(), port_plan())
        self.assertTrue(result["capacity_estimate_pass"])
        index = {x["partition"]: x["source"] for x in result["hybrid_partitions"]}
        self.assertEqual(index, SOURCES)
        self.assertEqual(result["group_limit_delta_bytes"], 104857600)
        self.assertEqual(result["hybrid_total_image_bytes"],
                         sum(DONOR_PARTITIONS[p] if m == "SM-F956N"
                             else TARGET_PARTITIONS[p] for p, m in SOURCES.items()))

    def test_missing_target_partition_is_rejected(self):
        data = model_input()
        data["devices"][0]["partitions"] = [
            x for x in data["devices"][0]["partitions"] if x["name"] != "vendor_dlkm"
        ]
        with self.assertRaisesRegex(ValueError, "absent on actual F741N"):
            report_from_data(data, port_plan())

    def test_wrong_donor_model_is_rejected(self):
        plan = port_plan()
        plan["system_partition_sources"]["system"] = "SM-F956B"
        with self.assertRaisesRegex(ValueError, "Invalid firmware source"):
            report_from_data(model_input(), plan)

    def test_corrupt_metadata_is_rejected(self):
        data = model_input()
        data["devices"][1]["checksums_valid"] = False
        with self.assertRaisesRegex(ValueError, "Unverified metadata"):
            report_from_data(data, port_plan())

    def test_capacity_failure_is_reported(self):
        data = model_input()
        data["devices"][0]["groups"][1]["maximum_bytes"] = 5000000000
        result = report_from_data(data, port_plan())
        self.assertFalse(result["capacity_estimate_pass"])
        self.assertLess(result["estimated_remaining_bytes"], 0)

    def test_suffix_normalization_and_duplicates(self):
        data = model_input()
        data["devices"][0]["partitions"][0]["name"] = "system_a"
        result = report_from_data(data, port_plan())
        self.assertTrue(result["capacity_estimate_pass"])
        data["devices"][0]["partitions"].append(
            {"name": "system_b", "bytes": 1, "group": "qti_dynamic_partitions"})
        with self.assertRaisesRegex(ValueError, "Duplicate normalized"):
            report_from_data(data, port_plan())


if __name__ == "__main__":
    unittest.main()
