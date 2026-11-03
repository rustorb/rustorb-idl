"""The golden test cases: what tools/update-golden.py writes to tests/golden/
and what test_golden.py compares with it.

Each case runs rustorb-idl on one IDL file of tests/idl/ into
tests/golden/<directory>/. The cases of one directory must not write the
same files.
"""

import os
import tempfile

from _paths import GOLDEN, TEST_IDL

#: (directory, options, IDL file relative to tests/idl/)
CASES = [
    ("rust", ["-brust"], "RustMapping.idl"),
    ("rust", ["-brust", "-Wbdds_only"], "DdsMapping.idl"),
    ("rust", ["-brust", "-Wbdds"], "DdsCorba.idl"),
    ("rust", ["-brust"], "CosNaming.idl"),
    ("python", ["-bpython"], "Mapping.idl"),
    ("python", ["-bpython"], "CosNaming.idl"),
    ("c++11", ["-bc++11"], "cpp/CxxMapping.idl"),
    ("c++11", ["-bc++11"], "CosNaming.idl"),
    ("java", ["-bjava"], "cpp/CxxMapping.idl"),
    ("java", ["-bjava"], "CosNaming.idl"),
]


def generate(directory, outdir):
    """Runs the cases of one directory into outdir."""
    from rustorb_idl import cli

    for d, options, idl in CASES:
        if d != directory:
            continue
        path = os.path.join(TEST_IDL, idl)
        argv = list(options) + ["-I", os.path.dirname(path), "-C", outdir, path]
        if cli.main(argv) != 0:
            raise RuntimeError("rustorb-idl %s failed" % " ".join(argv))


def directories():
    return sorted({d for d, _, _ in CASES})


def files(root):
    """The files under root, as paths relative to it."""
    out = []
    for dirpath, _, names in os.walk(root):
        for n in names:
            if n.endswith(".pyc") or "__pycache__" in dirpath:
                continue
            out.append(os.path.relpath(os.path.join(dirpath, n), root))
    return sorted(out)


def expected_dir(directory):
    return os.path.join(GOLDEN, directory)


def temp_dir():
    return tempfile.mkdtemp(prefix="rustorb-idl-golden-")
