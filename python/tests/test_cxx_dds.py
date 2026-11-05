"""Tests of the DDS types of ``rustorb-idl -bc++11`` (``-Wbdds``,
``-Wbdds_only``): what is written, and the constructs the generator
refuses. The generated code needs rustorb-dds's C++ headers; it is
compiled (syntax only) when RUSTORB_DDS_SRC names a checkout of
https://github.com/rustorb/rustorb-dds and a C++ compiler is found (the
``-Wbdds`` output needs rustorb's headers too, RUSTORB_SRC). rustorb-dds
checks that the types hash as Cyclone DDS's idlc describes them and runs
them (cpp/tests there).

Run from the repository root with idl_parser importable::

    PYTHONPATH=path/to/idl_parser python3 -m unittest discover -s python/tests
"""

import contextlib
import io
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest

from _paths import CODEGEN, TEST_IDL, rustorb  # noqa: E402

if CODEGEN not in sys.path:
    sys.path.insert(0, CODEGEN)

from rustorb_idl import cli  # noqa: E402

OUT = tempfile.mkdtemp(prefix="rustorb-idl-cxx-dds-test-")
RUSTORB_DDS = os.environ.get("RUSTORB_DDS_SRC") or None
if RUSTORB_DDS and not os.path.exists(os.path.join(RUSTORB_DDS, "cpp", "include", "dds", "dds.hpp")):
    RUSTORB_DDS = None  # a rustorb-dds without the C++ binding
CXX = os.environ.get("CXX") or shutil.which("g++") or shutil.which("clang++")


def tearDownModule():
    shutil.rmtree(OUT, ignore_errors=True)


def write_idl(name, text):
    d = os.path.join(OUT, "idl")
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, name)
    with open(path, "w") as f:
        f.write(textwrap.dedent(text))
    return path


def run(outdir, *argv):
    err = io.StringIO()
    with contextlib.redirect_stderr(err):
        status = cli.main(["-bc++11", "-C", outdir] + list(argv))
    return status, err.getvalue()


def generate(idl_text, *options, name="T.idl"):
    """Runs -bc++11 -Wbdds_only; returns (status, stderr, text of T.hh,
    text of T_dds.hh)."""
    path = write_idl(name, idl_text)
    outdir = tempfile.mkdtemp(dir=OUT)
    status, err = run(outdir, "-Wbdds_only", *(list(options) + [path]))
    texts = [None, None]
    if status == 0:
        base = name[:-4]
        for i, f in enumerate((base + ".hh", base + "_dds.hh")):
            with open(os.path.join(outdir, f)) as fh:
                texts[i] = fh.read()
    return status, err, texts[0], texts[1]


def compile_syntax(outdir, header, corba=False):
    """Compiles a source that includes ``header`` (syntax only)."""
    src = os.path.join(outdir, "check.cc")
    with open(src, "w") as f:
        f.write('#include "%s"\n#include <dds/dds.hpp>\n' % header)
    includes = [
        "-I", outdir,
        "-I", os.path.join(RUSTORB_DDS, "cpp", "include"),
        "-I", os.path.join(RUSTORB_DDS, "crates", "rustorb-dds-ffi", "include"),
    ]
    if corba:
        includes += [
            "-I", rustorb("cpp", "include"),
            "-I", rustorb("crates", "rustorb-ffi", "include"),
        ]
    r = subprocess.run(
        [CXX, "-std=c++17", "-Wall", "-Wextra", "-Werror", "-fsyntax-only"] + includes + [src],
        capture_output=True,
        text=True,
    )
    return r.returncode, r.stderr


class OutputTest(unittest.TestCase):
    def test_dds_only_writes_the_types_and_their_support(self):
        path = write_idl("Only.idl", "module M { struct S { long a; }; };")
        outdir = tempfile.mkdtemp(dir=OUT)
        self.assertEqual(run(outdir, "-Wbdds_only", path)[0], 0)
        self.assertEqual(sorted(os.listdir(outdir)), ["Only.hh", "Only_dds.hh"])
        with open(os.path.join(outdir, "Only.hh")) as f:
            text = f.read()
        self.assertNotIn("CORBA", text)
        self.assertNotIn("rustorb/cdr.h", text)

    def test_dds_writes_the_corba_code_too(self):
        path = write_idl("Both.idl", "module M { struct S { long a; }; };")
        outdir = tempfile.mkdtemp(dir=OUT)
        self.assertEqual(run(outdir, "-Wbdds", path)[0], 0)
        self.assertEqual(sorted(os.listdir(outdir)), ["Both.cc", "Both.hh", "Both_dds.hh"])
        with open(os.path.join(outdir, "Both.hh")) as f:
            self.assertIn("rustorb/cdr.h", f.read())

    def test_types(self):
        status, err, types, dds = generate(
            """
            module M {
              const long N = 3;
              @bit_bound(8) enum E { A, @value(-2) @default_literal B };
              @bit_bound(12) bitmask F { X, @position(11) Y };
              typedef sequence<long, 5> Longs;
              @mutable struct S {
                @key long id;
                @id(7) Longs l;
                @optional string<10> o;
                long grid[N][2];
                @external E e;
                F f;
                long delete;
              };
              union U switch (E) { case A: long x; default: string s; };
            };
            """
        )
        self.assertEqual(status, 0, err)
        # T.hh: no CORBA, @value, std::optional, bounded as unbounded
        self.assertIn("enum class E : int32_t { A = 0, B = -2 };", types)
        self.assertIn("using Longs = std::vector<int32_t>;", types)
        self.assertIn("std::optional<std::string> _m_o", types)
        self.assertIn('throw ::std::invalid_argument("the union member is not selected");', types)
        self.assertIn("inline constexpr int32_t N = 3;", types)
        # T_dds.hh
        self.assertIn('enum_builder b("M::E", 8, RDDS_FINAL);', dds)
        self.assertIn('b.literal("B", -2, true);', dds)
        self.assertIn('bitmask_builder b("M::F", 12, RDDS_FINAL);', dds)
        self.assertIn('b.flag("Y", 11);', dds)
        self.assertIn(
            'alias_type("M::Longs", ::rustorb::dds::sequence_type('
            "::rustorb::dds::primitive_type(RDDS_TK_INT32).get(), 5).get());",
            dds,
        )
        self.assertIn('struct_builder b("M::S", RDDS_MUTABLE, 0);', dds)
        self.assertIn(
            'b.member("id", 0u, ::rustorb::dds::primitive_type(RDDS_TK_INT32).get(), RDDS_MEMBER_KEY, nullptr);',
            dds,
        )
        self.assertIn('b.member("l", 7u, ::rustorb::dds::idl::M::Longs(), 0, nullptr);', dds)
        self.assertIn(
            'b.member("o", 8u, ::rustorb::dds::string_type(false, 10).get(), RDDS_MEMBER_OPTIONAL, nullptr);',
            dds,
        )
        self.assertIn(
            "array_type(::rustorb::dds::primitive_type(RDDS_TK_INT32).get(), {3u, 2u}).get()", dds
        )
        self.assertIn("RDDS_MEMBER_EXTERNAL", dds)
        self.assertIn("::rustorb::dds::shape::sequence<::rustorb::dds::shape::prim<int32_t>>::write(s, v.l());", dds)
        self.assertIn("::rustorb::dds::shape::optional<::rustorb::dds::shape::string>::write(s, v.o());", dds)
        self.assertIn("::rustorb::dds::shape::array<::rustorb::dds::shape::prim<int32_t>, 2>::write(s, v.grid());", dds)
        self.assertIn("::rustorb::dds::shape::prim<int32_t>::write(s, v._cxx_delete());", dds)
        self.assertIn(
            'union_builder b("M::U", RDDS_APPENDABLE, 0, ::rustorb::dds::idl::M::E());', dds
        )
        self.assertIn('b.member("x", 0u, ::rustorb::dds::primitive_type(RDDS_TK_INT32).get(), {0}, 0, nullptr);', dds)
        self.assertIn("RDDS_MEMBER_DEFAULT_LABEL", dds)
        self.assertIn("template <> struct is_topic_type<::M::S> {", dds)
        self.assertIn('static std::string value() { return "M::S"; }', dds)
        self.assertNotIn("is_topic_type<::M::U>", dds)

    def test_arrays_of_typedefs_of_arrays(self):
        # long m[2][3] is one array of two dimensions; Row r[2] is an array
        # of arrays: their shapes differ though their C++ types do not.
        _, err, _, dds = generate(
            "typedef long Row[3]; struct S { long m[2][3]; Row r[2]; };"
        )
        self.assertIn("shape::array<::rustorb::dds::shape::prim<int32_t>, 2>::write(s, v.m());", dds)
        self.assertIn(
            "shape::array<::rustorb::dds::shape::array<::rustorb::dds::shape::prim<int32_t>, 1>, 1>"
            "::write(s, v.r());",
            dds,
        )

    def test_nested_and_topic(self):
        _, _, _, dds = generate(
            """
            @nested struct A { long a; };
            @default_nested module M {
              struct Hidden { long a; };
              @topic struct Shown { long a; };
            };
            """
        )
        self.assertIn('struct_builder b("A", RDDS_APPENDABLE, RDDS_TYPE_NESTED);', dds)
        self.assertNotIn("is_topic_type<::A>", dds)
        self.assertNotIn("is_topic_type<::M::Hidden>", dds)
        self.assertIn("is_topic_type<::M::Shown>", dds)

    def test_autoid_hash_and_hashid(self):
        _, _, _, dds = generate(
            '@autoid(HASH) @mutable struct H { long alpha; @hashid string beta; @hashid("other") long gamma; };'
        )
        self.assertIn("RDDS_TYPE_AUTOID_HASH", dds)
        self.assertIn(', 0, "");', dds)
        self.assertIn(', 0, "other");', dds)

    def test_default_extensibility(self):
        _, _, _, dds = generate("struct S { long a; };", "-Wbextensibility=final")
        self.assertIn('struct_builder b("S", RDDS_FINAL, 0);', dds)

    def test_included_types(self):
        write_idl("Base.idl", "module B { struct P { long x; }; };")
        status, err, types, dds = generate(
            '#include "Base.idl"\nmodule M { struct S { B::P p; }; };', name="Top.idl"
        )
        self.assertEqual(status, 0, err)
        self.assertIn('#include "Base.hh"', types)
        self.assertIn('#include "Base_dds.hh"', dds)
        self.assertIn("::rustorb::dds::shape::type<::B::P>::write(s, v.p());", dds)

    def test_corba_types_are_left_out(self):
        status, err, types, dds = generate(
            """
            module M {
              interface I { void f(); };
              exception X { long code; };
              struct S { long a; };
            };
            """
        )
        self.assertEqual(status, 0, err)
        self.assertNotIn("class I", types)
        self.assertNotIn("class X", types)
        self.assertIn("class S", types)

    def test_refused(self):
        for idl, what in (
            ("struct A { long a; }; struct B : A { long b; };", "inheritance"),
            ("@mutable union U switch (long) { case 1: long x; };", "mutable unions"),
            ("struct S; struct T { long a; }; struct S { long a; };", "forward declarations"),
            ("struct S { @key @optional long a; };", "both @key and @optional"),
            ("struct S { @non_serialized long a; };", "@non_serialized"),
            ("struct S { any a; };", "no form in DDS"),
            ("struct S { fixed<5, 2> a; };", "no form in DDS"),
            ("interface I {}; struct S { I i; };", "no form in DDS"),
            ("struct O { struct In { long a; } i; };", "inside"),
        ):
            status, err, _, _ = generate(idl)
            self.assertEqual(status, 1, idl)
            self.assertIn(what, err, idl)


@unittest.skipIf(not (RUSTORB_DDS and CXX), "needs RUSTORB_DDS_SRC and a C++ compiler")
class CompileTest(unittest.TestCase):
    def test_dds_only(self):
        for idl in ("DdsMapping.idl", "DdsXTypes.idl"):
            outdir = tempfile.mkdtemp(dir=OUT)
            path = os.path.join(TEST_IDL, idl)
            status, err = run(outdir, "-Wbdds_only", path)
            self.assertEqual(status, 0, err)
            rc, err = compile_syntax(outdir, idl[:-4] + "_dds.hh")
            self.assertEqual(rc, 0, err)

    @unittest.skipIf(rustorb() is None, "needs RUSTORB_SRC")
    def test_with_corba(self):
        outdir = tempfile.mkdtemp(dir=OUT)
        status, err = run(outdir, "-Wbdds", os.path.join(TEST_IDL, "DdsCorba.idl"))
        self.assertEqual(status, 0, err)
        rc, err = compile_syntax(outdir, "DdsCorba_dds.hh", corba=True)
        self.assertEqual(rc, 0, err)


if __name__ == "__main__":
    unittest.main()
