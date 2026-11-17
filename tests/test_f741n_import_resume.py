"""Unit tests for idempotent F741N/F956N import, without any Odin payload."""
from contextlib import redirect_stdout
import io
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from import_duykhaidex_f741n import import_both, model_spec  # noqa: E402
from preflight_f741n import EXPECTED, ODIN_ROLES  # noqa: E402


def fake_names(model):
    return [
        f"{role}_{EXPECTED[model][role]}_{model.replace('SM-', '')}_{role}.tar.md5"
        for role in ODIN_ROLES
    ]


def populate_source(folder):
    for model in ("SM-F741N", "SM-F956N"):
        for name in fake_names(model):
            (folder / name).write_bytes(b"placeholder-not-a-real-odin-file")


def make_existing(folder, root, model):
    dest = root / f"{model}_SKC"
    dest.mkdir()
    (dest / ".downloaded").write_text(model_spec(model)["version"])
    for filename in fake_names(model):
        os.symlink((folder / filename).resolve(), dest / filename)
    return dest


class ImportResumeTests(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.TemporaryDirectory()
        self.addCleanup(self.t.cleanup)
        self.root = Path(self.t.name)
        self.source = self.root / "incoming"
        self.output = self.root / "out"
        self.source.mkdir()
        self.output.mkdir()
        populate_source(self.source)

    @mock.patch("import_duykhaidex_f741n.verify_odin_package")
    @mock.patch("import_duykhaidex_f741n.import_directory")
    def test_existing_flip6_is_verified_and_fold6_imported(self, do_import, verify):
        existing = make_existing(self.source, self.output, "SM-F741N")

        def simulate_import(stage, spec, destination):
            destination.mkdir()
            (destination / ".downloaded").write_text(spec["version"])
            for entry in stage.iterdir():
                os.symlink(entry.resolve(), destination / entry.name)

        do_import.side_effect = simulate_import
        with redirect_stdout(io.StringIO()):
            import_both(self.source, self.output)
        self.assertEqual(do_import.call_count, 1)
        self.assertEqual(do_import.call_args.args[1]["model"], "SM-F956N")
        self.assertEqual(verify.call_count, 4)
        self.assertTrue(existing.is_dir())
        self.assertEqual(len(list((self.output / "SM-F956N_SKC").iterdir())), 5)

    @mock.patch("import_duykhaidex_f741n.verify_odin_package")
    @mock.patch("import_duykhaidex_f741n.import_directory")
    def test_repeat_with_both_valid_imports_never_overwrites(self, do_import, verify):
        make_existing(self.source, self.output, "SM-F741N")
        make_existing(self.source, self.output, "SM-F956N")
        with redirect_stdout(io.StringIO()):
            import_both(self.source, self.output)
        do_import.assert_not_called()
        self.assertEqual(verify.call_count, 8)

    @mock.patch("import_duykhaidex_f741n.verify_odin_package")
    @mock.patch("import_duykhaidex_f741n.import_directory")
    def test_wrong_version_marker_refuses_to_continue(self, do_import, _verify):
        folder = make_existing(self.source, self.output, "SM-F741N")
        (folder / ".downloaded").write_text("WRONG")
        with self.assertRaisesRegex(ValueError, "version marker"):
            import_both(self.source, self.output)
        do_import.assert_not_called()
        self.assertFalse((self.output / "SM-F956N_SKC").exists())

    @mock.patch("import_duykhaidex_f741n.verify_odin_package")
    @mock.patch("import_duykhaidex_f741n.import_directory")
    def test_wrong_symlink_refuses_to_continue(self, do_import, _verify):
        folder = make_existing(self.source, self.output, "SM-F741N")
        name = fake_names("SM-F741N")[0]
        (folder / name).unlink()
        os.symlink((self.source / fake_names("SM-F956N")[0]).resolve(), folder / name)
        with self.assertRaisesRegex(ValueError, "different file"):
            import_both(self.source, self.output)
        do_import.assert_not_called()
        self.assertFalse((self.output / "SM-F956N_SKC").exists())


if __name__ == "__main__":
    unittest.main()
