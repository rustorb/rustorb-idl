"""Where the tests find the generator, the test IDL and, optionally, rustorb.

The tests that compile or run generated code need the rustorb runtime (the
Python package, the C++ headers, the Java sources). They run only when
RUSTORB_SRC names a checkout of https://github.com/rustorb/rustorb; without
it they are skipped and the rest checks the generator on its own (including
the golden test, test_golden.py).
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.normpath(os.path.join(HERE, "..", ".."))
CODEGEN = os.path.join(REPO, "python")
TEST_IDL = os.path.join(REPO, "tests", "idl")
# Copies of rustorb's interop/idl and cpp/tests/idl.
INTEROP_IDL = os.path.join(TEST_IDL, "interop")
CPP_IDL = os.path.join(TEST_IDL, "cpp")
GOLDEN = os.path.join(REPO, "tests", "golden")

RUSTORB = os.environ.get("RUSTORB_SRC") or None
if RUSTORB:
    RUSTORB = os.path.abspath(RUSTORB)

if CODEGEN not in sys.path:
    sys.path.insert(0, CODEGEN)


def rustorb(*parts):
    """A path in the rustorb checkout of RUSTORB_SRC, or None without one."""
    return os.path.join(RUSTORB, *parts) if RUSTORB else None
