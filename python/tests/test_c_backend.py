"""Tests of ``rustorb-idl -bc``: the command line, the generated code and the
constructs the C backend refuses. The generated code is compiled (C99, every
warning an error; and as C++) against the headers of librustorb_c
(rustorb's c/include) when RUSTORB_SRC is set and a compiler is found;
rustorb's c/tests link and run it.

Run from the repository root with idl_parser importable::

    PYTHONPATH=path/to/idl_parser python3 -m unittest discover -s python/tests
"""

import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest

from _paths import CODEGEN, CPP_IDL, INTEROP_IDL, TEST_IDL, rustorb  # noqa: E402,F401

RUNTIME = rustorb("c", "include")
if RUNTIME and not os.path.exists(os.path.join(RUNTIME, "rustorb", "runtime.h")):
    RUNTIME = None
FFI = rustorb("crates", "rustorb-ffi", "include")

if CODEGEN not in sys.path:
    sys.path.insert(0, CODEGEN)

from rustorb_idl import cli  # noqa: E402

OUT = tempfile.mkdtemp(prefix="rustorb-idl-c-test-")
CC = (os.environ.get("CC") or shutil.which("cc") or shutil.which("gcc")) if RUNTIME else None
CXX = (os.environ.get("CXX") or shutil.which("c++") or shutil.which("g++")) if RUNTIME else None

IDLS = [
    os.path.join(INTEROP_IDL, "InteropTest.idl"),
    os.path.join(INTEROP_IDL, "AnyTest.idl"),
    os.path.join(INTEROP_IDL, "PoaProbe.idl"),
    os.path.join(CPP_IDL, "CxxMapping.idl"),
    os.path.join(TEST_IDL, "CosNaming.idl"),
]
NAMES = ("InteropTest", "AnyTest", "PoaProbe", "CxxMapping", "CosNaming")


def tearDownModule():
    shutil.rmtree(OUT, ignore_errors=True)


def write_idl(name, text):
    d = os.path.join(OUT, "idl")
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, name)
    with open(path, "w") as f:
        f.write(textwrap.dedent(text))
    return path


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


class CBackendTest(unittest.TestCase):
    maxDiff = 2000

    @classmethod
    def setUpClass(cls):
        cls.outdir = os.path.join(OUT, "gen")
        assert cli.main(["-bc", "-I", INTEROP_IDL, "-C", cls.outdir] + IDLS) == 0

    def h(self, name):
        return read(os.path.join(self.outdir, name + ".h"))

    def c(self, name):
        return read(os.path.join(self.outdir, name + ".c"))

    def test_outputs(self):
        for name in NAMES:
            for ext in (".h", ".c"):
                self.assertTrue(os.path.exists(os.path.join(self.outdir, name + ext)), name + ext)
        h = self.h("InteropTest")
        self.assertIn("Do not edit", h)
        self.assertIn("#include <rustorb/runtime.h>", h)
        self.assertIn('#include "InteropTest.h"', self.c("InteropTest"))
        self.assertIn("extern const rustorb_c_module InteropTest_idl__module;", h)

    def test_mapping(self):
        h = self.h("InteropTest")
        # Constants are macros; names are the scoped names joined by _.
        self.assertIn("#define InteropTest_MAGIC ((CORBA_long)1381323604)", h)
        # An interface is a CORBA_Object; operations take _obj first and
        # the environment last, in, inout and out as in C mapping 1.21.
        self.assertIn("typedef CORBA_Object InteropTest_Echo;", h)
        self.assertIn(
            "InteropTest_LongSeq* InteropTest_Echo_echo_long_seq(InteropTest_Echo _obj, "
            "const InteropTest_LongSeq* v, CORBA_Environment* _ev);",
            h,
        )
        self.assertIn(
            "CORBA_long InteropTest_Echo_swap(InteropTest_Echo _obj, CORBA_long* a, "
            "CORBA_long* b, CORBA_Environment* _ev);",
            h,
        )
        self.assertIn(
            "CORBA_long InteropTest_Echo_divide(InteropTest_Echo _obj, CORBA_long a, "
            "CORBA_long b, CORBA_long* remainder, CORBA_Environment* _ev);",
            h,
        )
        # Attributes are _get_ and _set_ functions.
        self.assertIn(
            "CORBA_long InteropTest_Echo__get_counter(InteropTest_Echo _obj, CORBA_Environment* _ev);",
            h,
        )
        self.assertIn(
            "void InteropTest_Echo__set_counter(InteropTest_Echo _obj, CORBA_long value, "
            "CORBA_Environment* _ev);",
            h,
        )
        # Arrays return slices; unions are _d and _u; exceptions have ex_.
        self.assertIn("typedef CORBA_double InteropTest_Matrix_slice[3];", h)
        self.assertIn("InteropTest_Matrix_slice* InteropTest_Echo_echo_matrix(", h)
        self.assertIn("  } _u;", h)
        self.assertIn('#define ex_InteropTest_Oops "IDL:rustorb.org/InteropTest/Oops:1.0"', h)
        # The skeleton: the epv, the vepv and the servant struct.
        self.assertIn("} POA_InteropTest_Echo__epv;", h)
        self.assertIn("void POA_InteropTest_Echo__init(PortableServer_Servant _servant, CORBA_Environment* _ev);", h)

        m = self.h("CxxMapping")
        # C keywords get _ (C mapping 1.2); C++ keywords too, so that the
        # header also compiles as C++.
        self.assertIn("  CORBA_long _class;", m)
        # fixed is a struct of its digits and scale.
        self.assertIn("#define CxxMapping_C_FIXED ((CORBA_fixed_4_2){4, 2, {0x01, 0x25, 0x0c}})", m)
        # Multiple inheritance: one epv for each ancestor, farthest first.
        self.assertIn(
            "  POA_CxxMapping_Base__epv* CxxMapping_Base_epv;\n"
            "  POA_CxxMapping_Other__epv* CxxMapping_Other_epv;\n"
            "  POA_CxxMapping_Derived__epv* CxxMapping_Derived_epv;\n"
            "  POA_CxxMapping_Multi__epv* CxxMapping_Multi_epv;\n",
            m,
        )
        # An escaped IDL identifier (_delete) is delete on the wire.
        self.assertIn('{"delete", ', self.c("CxxMapping"))

    def test_typecodes(self):
        h = self.h("AnyTest")
        self.assertIn("#define TC_AnyTest_Node rustorb_c_type_tc(&AnyTest_Node__desc, &AnyTest_idl__module)", h)
        c = self.c("AnyTest")
        self.assertIn("const rustorb_c_type AnyTest_Node__desc = {", c)

    def test_options(self):
        path = os.path.join(INTEROP_IDL, "InteropTest.idl")
        self.assertEqual(cli.main(["-bc", "-Wbami", "-C", OUT, path]), 2)

    def test_unsupported(self):
        # rustorb#187: valuetypes, abstract and local interfaces; and the
        # IDL 4 bitmask and bitset.
        cases = {
            "valuetype": "module U { valuetype V { public long x; }; };",
            "abstract": "module U { abstract interface A { void a(); }; };",
            "local": "module U { local interface L { void a(); }; };",
            "bitmask": "module U { bitmask B { X, Y }; };",
        }
        for name, text in cases.items():
            with self.subTest(name):
                path = write_idl("Unsupported_%s.idl" % name, text)
                self.assertEqual(cli.main(["-bc", "-C", OUT, path]), 1)

    def compile(self, compiler, lang, flags):
        include = ["-I", self.outdir, "-I", RUNTIME, "-I", FFI]
        for name in NAMES:
            with self.subTest(compiler=compiler, name=name):
                src = os.path.join(self.outdir, name + ".c")
                r = subprocess.run(
                    [compiler, "-x", lang] + flags + include + ["-fsyntax-only", src],
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(r.returncode, 0, r.stderr[-4000:])

    @unittest.skipUnless(CC, "needs RUSTORB_SRC and a C compiler")
    def test_compile_c(self):
        self.compile(CC, "c", ["-std=c99", "-Wall", "-Wextra", "-Wpedantic", "-Werror"])

    @unittest.skipUnless(CXX, "needs RUSTORB_SRC and a C++ compiler")
    def test_compile_headers_as_cxx(self):
        # The headers are usable from C++ (extern "C").
        include = ["-I", self.outdir, "-I", RUNTIME, "-I", FFI]
        for name in NAMES:
            with self.subTest(name=name):
                src = os.path.join(self.outdir, name + "_cxx.cc")
                with open(src, "w") as f:
                    f.write('#include "%s.h"\nint main() { return 0; }\n' % name)
                r = subprocess.run(
                    [CXX, "-std=c++11", "-Wall", "-Wextra", "-Werror", "-fsyntax-only"] + include + [src],
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(r.returncode, 0, r.stderr[-4000:])


if __name__ == "__main__":
    unittest.main()
