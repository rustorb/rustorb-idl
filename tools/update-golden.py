#!/usr/bin/env python3
"""Writes the generator's output for the golden test cases to tests/golden/
(python/tests/golden.py lists them). Needs idl_parser importable (or
IDL_PARSER_DIR set to a checkout of it) and rustfmt on PATH.

    IDL_PARSER_DIR=path/to/idl_parser tools/update-golden.py
"""

import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "python", "tests"))
if os.environ.get("IDL_PARSER_DIR"):
    sys.path.insert(0, os.environ["IDL_PARSER_DIR"])

import golden  # noqa: E402


def main():
    for directory in golden.directories():
        out = golden.expected_dir(directory)
        shutil.rmtree(out, ignore_errors=True)
        os.makedirs(out)
        golden.generate(directory, out)
        print("tests/golden/%s: %d files" % (directory, len(golden.files(out))))


if __name__ == "__main__":
    main()
