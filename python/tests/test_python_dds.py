"""Tests of the DDS types of ``rustorb-idl -bpython`` (``-Wbdds``,
``-Wbdds_only``): what is written, and the constructs the generator
refuses. The generated code needs the rustorb_dds package (rustorb-dds's
Python binding); the tests that run it are skipped without it.
rustorb-dds checks that the TypeObjects of such code match those of
Cyclone DDS (python/tests/test_generated.py there).

Run from the repository root with idl_parser importable::

    PYTHONPATH=path/to/idl_parser python3 -m unittest discover -s python/tests
"""

import contextlib
import importlib
import io
import os
import shutil
import sys
import tempfile
import textwrap
import unittest

from _paths import CODEGEN  # noqa: E402

if CODEGEN not in sys.path:
    sys.path.insert(0, CODEGEN)

from rustorb_idl import cli  # noqa: E402

try:
    import rustorb_dds
except ImportError:
    rustorb_dds = None

OUT = tempfile.mkdtemp(prefix="rustorb-idl-python-dds-test-")


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
        status = cli.main(["-bpython", "-C", outdir] + list(argv))
    return status, err.getvalue()


def generate(idl_text, *options, name="T.idl"):
    """Runs -bpython -Wbdds_only; returns (status, stderr, text of
    T_dds.py)."""
    path = write_idl(name, idl_text)
    outdir = tempfile.mkdtemp(dir=OUT)
    status, err = run(outdir, "-Wbdds_only", *(list(options) + [path]))
    text = None
    if status == 0:
        for d, _, files in os.walk(outdir):
            if name[:-4] + "_dds.py" in files:
                with open(os.path.join(d, name[:-4] + "_dds.py")) as f:
                    text = f.read()
    return status, err, text


class OutputTest(unittest.TestCase):
    def test_dds_only_writes_one_module(self):
        path = write_idl("Only.idl", "module M { struct S { long a; }; };")
        outdir = tempfile.mkdtemp(dir=OUT)
        self.assertEqual(run(outdir, "-Wbdds_only", path)[0], 0)
        self.assertEqual(os.listdir(outdir), ["Only_dds.py"])

    def test_dds_writes_the_corba_code_too(self):
        path = write_idl("Both.idl", "module M { struct S { long a; }; };")
        outdir = tempfile.mkdtemp(dir=OUT)
        self.assertEqual(run(outdir, "-Wbdds", "-Wbno_stubs", path)[0], 0)
        self.assertEqual(sorted(os.listdir(outdir)), ["Both_dds.py", "Both_idl.py", "M", "M__POA"])

    def test_declarations(self):
        status, err, text = generate(
            """
            module M {
              const long N = 3;
              enum E { A, @default_literal B };
              typedef sequence<long, 5> Longs;
              @mutable struct S {
                @key long id;
                @id(7) Longs l;
                @optional string<10> o;
                long grid[N][2];
                E e;
                long from;
              };
              union U switch (E) { case A: long x; default: string s; };
            };
            """
        )
        self.assertEqual(status, 0, err)
        self.assertIn('M = _0_types.ModuleType("T_dds.M")', text)
        self.assertIn("M.N = 3", text)
        self.assertIn('@_0_dds.enum("M::E", default_literal="B")', text)
        self.assertIn('M.Longs = _0_dds.typedef("M::Longs", _0_dds.sequence(_0_dds.int32, 5))', text)
        self.assertIn('@_0_dds.struct("M::S", extensibility="mutable")', text)
        self.assertIn("    id: _0_dds.key(_0_dds.int32)", text)
        self.assertIn("    l: _0_dds.member(M.Longs, id=7)", text)
        self.assertIn("    o: _0_dds.member(_0_dds.string(10), optional=True)", text)
        self.assertIn("    grid: _0_dds.array(_0_dds.int32, 3, 2)", text)
        self.assertIn('    _from: _0_dds.member(_0_dds.int32, name="from")', text)
        self.assertIn("    x: _0_dds.case(_0_dds.int32, M.E.A)", text)
        self.assertIn("    s: _0_dds.default_case(_0_dds.string())", text)

    def test_default_extensibility(self):
        _, _, text = generate("struct S { long a; };", "-Wbextensibility=final")
        self.assertIn('@_0_dds.struct("S")', text)
        _, _, text = generate("struct S { long a; };")
        self.assertIn('@_0_dds.struct("S", extensibility="appendable")', text)

    def test_included_types(self):
        write_idl("Base.idl", "module B { struct P { long x; }; };")
        status, err, text = generate(
            '#include "Base.idl"\nmodule M { struct S { B::P p; }; };', name="Top.idl"
        )
        self.assertEqual(status, 0, err)
        self.assertIn("import Base_dds as _0_f_Base_dds  # Base.idl", text)
        self.assertIn("    p: _0_f_Base_dds.B.P", text)
        status, err, text = generate(
            '#include "Base.idl"\nstruct S { B::P p; };', "-Wbpackage=pkg", name="Top2.idl"
        )
        self.assertIn("import pkg.Base_dds as _0_f_Base_dds", text)

    def test_refused(self):
        for idl, what in (
            ("struct A { long a; }; struct B : A { long b; };", "inheritance"),
            ("@mutable union U switch (long) { case 1: long x; };", "mutable unions"),
            ("struct S; struct T { sequence<S> s; }; struct S { long a; };", "forward declarations"),
            ("struct S { @key @optional long a; };", "both @key and @optional"),
            ("struct S { @non_serialized long a; };", "@non_serialized"),
            ("struct S { any a; };", "no form in DDS"),
            ("interface I {}; struct S { I i; };", "no form in DDS"),
        ):
            status, err, _ = generate(idl)
            self.assertEqual(status, 1, idl)
            self.assertIn(what, err, idl)


@unittest.skipIf(rustorb_dds is None, "needs the rustorb_dds package")
class RunTest(unittest.TestCase):
    def load(self, idl_text, name):
        path = write_idl(name + ".idl", idl_text)
        outdir = tempfile.mkdtemp(dir=OUT)
        status, err = run(outdir, "-Wbdds_only", path)
        self.assertEqual(status, 0, err)
        sys.path.insert(0, outdir)
        try:
            return importlib.import_module(name + "_dds")
        finally:
            sys.path.remove(outdir)

    def test_types_and_values(self):
        m = self.load(
            """
            module M {
              enum E { A, B };
              @bit_bound(8) bitmask F { X, @position(3) Y };
              typedef string<8> Name;
              @appendable struct S { @key long id; Name n; E e; F f; long grid[2][2]; };
              union U switch (char) { case 'a': long x; case 'b': S s; };
            };
            """,
            "Run",
        )
        t = rustorb_dds.type_of(m.M.S)
        self.assertEqual(t.name, "M::S")
        self.assertTrue(t.keyed)
        s = m.M.S(id=1, n="x", e=m.M.E.B, f=m.M.F.X | m.M.F.Y, grid=[[1, 2], [3, 4]])
        self.assertEqual(s.grid, [[1, 2], [3, 4]])
        self.assertEqual(rustorb_dds.type_of(m.M.U).describe()[0], "union")
        self.assertEqual(m.M.U("b", s).value, s)


if __name__ == "__main__":
    unittest.main()
