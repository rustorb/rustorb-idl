"""Golden test: the generator's output for the test IDL is exactly the one
checked in under tests/golden/ (python/tests/golden.py lists the cases).

When a change of the generator changes its output on purpose, run
tools/update-golden.py and commit the new files with the change. The Rust
output is formatted with rustfmt, so the Rust cases need it on PATH.

Run from the repository root with idl_parser importable::

    PYTHONPATH=path/to/idl_parser python3 -m unittest discover -s python/tests
"""

import difflib
import os
import shutil
import unittest

import golden


class GoldenTest(unittest.TestCase):
    def check(self, directory):
        if directory == "rust" and not shutil.which("rustfmt"):
            self.skipTest("rustfmt is not on PATH")
        out = golden.temp_dir()
        try:
            golden.generate(directory, out)
            expected = golden.expected_dir(directory)
            self.assertEqual(golden.files(out), golden.files(expected),
                             "the generated files differ from tests/golden/%s" % directory)
            for rel in golden.files(out):
                with open(os.path.join(out, rel), encoding="utf-8") as f:
                    got = f.read()
                with open(os.path.join(expected, rel), encoding="utf-8") as f:
                    want = f.read()
                if got != want:
                    diff = "".join(list(difflib.unified_diff(
                        want.splitlines(True), got.splitlines(True),
                        "tests/golden/%s/%s" % (directory, rel), "generated"))[:200])
                    self.fail("tests/golden/%s/%s is out of date "
                              "(tools/update-golden.py):\n%s" % (directory, rel, diff))
        finally:
            shutil.rmtree(out, ignore_errors=True)

    def test_rust(self):
        self.check("rust")

    def test_python(self):
        self.check("python")

    def test_cxx(self):
        self.check("c++11")

    def test_java(self):
        self.check("java")


if __name__ == "__main__":
    unittest.main()
