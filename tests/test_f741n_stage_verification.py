"""Safety checks for staged b6q stock image validation."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from verify_b6q_stage import verify_stage, detect_filesystem


def fake_image(path, size):
    with path.open("wb") as stream:
        stream.truncate(size)
        stream.seek(1024)
        stream.write(b"\xe2\xe1\xf5\xe0")


def capacity():
    return {"hybrid_partitions": [
        {"partition": "system", "source": "SM-F956N", "current_image_bytes": 8192},
        {"partition": "vendor", "source": "SM-F741N", "current_image_bytes": 8192}
    ]}


def stage(root, model, partition):
    folder = root / model
    folder.mkdir()
    fake_image(folder / f"{partition}.img", 8192)
    (folder / "manifest.json").write_text(json.dumps({
        "status": "STOCK_IMAGES_ONLY_NOT_BUILDABLE", "model": model,
        "source_ap": f"AP_{model}_test.tar.md5",
        "partitions": [{"partition": partition,
                        "source_partition": partition, "bytes": 8192}]
    }))
    return folder


class StageVerificationTests(unittest.TestCase):
    def test_valid_model_staged_image(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = stage(Path(tmp), "SM-F956N", "system")
            checked = verify_stage(p, "SM-F956N", capacity())
            self.assertEqual(checked["images"][0]["filesystem"], "erofs")
            self.assertEqual(checked["images"][0]["bytes"], 8192)

    def test_manifests_must_match_model(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = stage(Path(tmp), "SM-F741N", "vendor")
            manifest = json.loads((p / "manifest.json").read_text())
            manifest["model"] = "SM-F956N"
            (p / "manifest.json").write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ValueError, "Invalid model"):
                verify_stage(p, "SM-F741N", capacity())

    def test_incorrect_image_size_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = stage(Path(tmp), "SM-F741N", "vendor")
            (p / "vendor.img").write_bytes(b"x" * 5000)
            with self.assertRaisesRegex(ValueError, "LP image size mismatch"):
                verify_stage(p, "SM-F741N", capacity())

    def test_extra_files_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = stage(Path(tmp), "SM-F956N", "system")
            (p / "unexpected.img").write_bytes(b"garbage")
            with self.assertRaisesRegex(ValueError, "Unexpected/missing"):
                verify_stage(p, "SM-F956N", capacity())

    def test_symlinked_image_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            p = stage(base, "SM-F956N", "system")
            (p / "system.img").unlink()
            target = base / "external.img"
            fake_image(target, 8192)
            (p / "system.img").symlink_to(target)
            with self.assertRaisesRegex(ValueError, "Image missing or symlink"):
                verify_stage(p, "SM-F956N", capacity())

    def test_unknown_filesystem_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = stage(Path(tmp), "SM-F741N", "vendor")
            (p / "vendor.img").write_bytes(b"\0" * 8192)
            self.assertEqual(detect_filesystem(p / "vendor.img"), "unknown")
            with self.assertRaisesRegex(ValueError, "Unrecognized filesystem"):
                verify_stage(p, "SM-F741N", capacity())


if __name__ == "__main__":
    unittest.main()
