"""Tests of the DDS types of ``rustorb-idl -bjava`` (``-Wbdds``,
``-Wbdds_only``): what is written, and the constructs the generator
refuses. The generated code needs rustorb-dds's Java binding; it is
compiled when RUSTORB_DDS_SRC names a checkout of
https://github.com/rustorb/rustorb-dds and javac (22 or newer) is found
(the ``-Wbdds`` output needs rustorb's Java sources too, RUSTORB_SRC).
rustorb-dds checks that the types hash as Cyclone DDS's idlc describes
them and runs them (java/src/test there).

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

OUT = tempfile.mkdtemp(prefix="rustorb-idl-java-dds-test-")
RUSTORB_DDS = os.environ.get("RUSTORB_DDS_SRC") or None
if RUSTORB_DDS and not os.path.isdir(os.path.join(RUSTORB_DDS, "java", "src", "main", "java")):
    RUSTORB_DDS = None  # a rustorb-dds without the Java binding
JAVAC = shutil.which("javac")


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
        status = cli.main(["-bjava", "-C", outdir] + list(argv))
    return status, err.getvalue()


def read_all(outdir):
    """{path relative to outdir: text} of the files written."""
    out = {}
    for dirpath, _, names in os.walk(outdir):
        for n in names:
            p = os.path.join(dirpath, n)
            with open(p) as f:
                out[os.path.relpath(p, outdir).replace(os.sep, "/")] = f.read()
    return out


def generate(idl_text, *options, name="T.idl"):
    """Runs -bjava -Wbdds_only; returns (status, stderr, {file: text})."""
    path = write_idl(name, idl_text)
    outdir = tempfile.mkdtemp(dir=OUT)
    status, err = run(outdir, "-Wbdds_only", *(list(options) + [path]))
    return status, err, read_all(outdir) if status == 0 else {}


class GeneratorTest(unittest.TestCase):
    def test_dds_only_writes_the_types_and_their_codecs(self):
        status, err, files = generate("module M { struct S { long a; }; };")
        self.assertEqual(status, 0, err)
        self.assertEqual(sorted(files), ["M/S.java", "M/SCodec.java"])
        for text in files.values():
            self.assertNotIn("org.omg.CORBA", text)

    def test_dds_writes_the_corba_code_too(self):
        path = write_idl("Both.idl", "module M { struct S { long a; }; };")
        outdir = tempfile.mkdtemp(dir=OUT)
        self.assertEqual(run(outdir, "-Wbdds", path)[0], 0)
        files = read_all(outdir)
        self.assertEqual(sorted(files), ["M/S.java", "M/SCodec.java", "M/SHelper.java", "M/SHolder.java"])
        self.assertIn("org.omg.CORBA.portable.IDLEntity", files["M/S.java"])
        self.assertIn("v.a = $in.readInt32();", files["M/SCodec.java"])

    def test_types(self):
        status, err, files = generate(
            """
            module M {
              @bit_bound(8) enum E { A, @default_literal @value(-2) B };
              @bit_bound(12) bitmask F { X, @position(11) Y };
              typedef sequence<long> Longs;
              const long N = 3;
              @nested struct S2 { long a; };
              @mutable struct S {
                @key int8 k;
                @optional string o;
                @optional long ol;
                @external S2 ext;
                @id(7) Longs l;
                long grid[2][3];
                E e;
                F f;
                long goto;
              };
              union U switch (long) { case 1: case 2: long x; default: string s; };
            };
            """
        )
        self.assertEqual(status, 0, err)
        e = files["M/E.java"]
        self.assertIn("public enum E {", e)
        self.assertIn("B(-2);", e)
        self.assertIn("public static E valueOf(int value) {", e)
        self.assertIn("public enum FFlags {", files["M/FFlags.java"])
        self.assertIn("Y(11);", files["M/FFlags.java"])
        self.assertIn("int value = 3;", files["M/N.java"])
        s = files["M/S.java"]
        self.assertIn("public byte k;", s)
        self.assertIn("public String o;", s)
        self.assertIn("public Integer ol;", s)
        self.assertIn("public int[] l;", s)
        self.assertIn("public int[][] grid;", s)
        self.assertIn("public java.util.BitSet f;", s)
        self.assertIn("public int _goto;", s)
        self.assertIn("this.e = M.E.B;", s)
        self.assertIn("this.grid = new int[2][3];", s)
        self.assertIn("this.ext = new M.S2();", s)

        self.assertIn('new org.rustorb.dds.Types.EnumBuilder("M::E", 8, org.rustorb.dds.Types.FINAL)',
                      files["M/ECodec.java"])
        self.assertIn('.literal("B", -2, true)', files["M/ECodec.java"])
        f = files["M/FCodec.java"]
        self.assertIn('new org.rustorb.dds.Types.BitmaskBuilder("M::F", 12, org.rustorb.dds.Types.FINAL)', f)
        self.assertIn('.flag("Y", 11)', f)
        self.assertIn("public static long bits(java.util.BitSet v) {", f)
        self.assertIn('return org.rustorb.dds.Types.alias("M::Longs",', files["M/LongsCodec.java"])
        c = files["M/SCodec.java"]
        self.assertIn("public final class SCodec implements org.rustorb.dds.Codec<M.S> {", c)
        self.assertIn('org.rustorb.dds.Types.checkGeneratedCode(1, "T.idl");', c)
        self.assertIn('new org.rustorb.dds.Types.StructBuilder("M::S", org.rustorb.dds.Types.MUTABLE, 0, null)', c)
        self.assertIn('.member("k", 0, org.rustorb.dds.Types.primitive(org.rustorb.dds.Types.TK_INT8), '
                      "org.rustorb.dds.Types.MEMBER_KEY, null)", c)
        self.assertIn('.member("l", 7, M.LongsCodec.type(), 0, null)', c)
        self.assertIn("org.rustorb.dds.Types.MEMBER_EXTERNAL", c)
        self.assertIn("$out.writeInt8(v.k);", c)
        self.assertIn("$out.writePresent(false);", c)
        self.assertIn("$out.writeInt32Array(v.l);", c)
        self.assertIn("$out.writeInt32Array((int[]) org.rustorb.dds.Out.flatten(v.grid, 2, 3));", c)
        self.assertIn("v.grid = (int[][]) org.rustorb.dds.In.unflatten($in.readInt32Array(6), 2, 3);", c)
        self.assertIn("$out.writeBitmask(M.FCodec.bits(v.f));", c)
        self.assertIn("v.f = M.FCodec.of($in.readBitmask());", c)
        self.assertIn("$out.writeInt32(v._goto);", c)
        self.assertIn("org.rustorb.dds.Types.TYPE_NESTED", files["M/S2Codec.java"])
        u = files["M/UCodec.java"]
        self.assertIn('.member("x", 0, org.rustorb.dds.Types.primitive(org.rustorb.dds.Types.TK_INT32), '
                      "new int[] {1, 2}, 0, null)", u)
        self.assertIn("org.rustorb.dds.Types.MEMBER_DEFAULT_LABEL", u)
        self.assertIn("if ($l == 1L || $l == 2L) {", u)
        self.assertIn("v.x($d, $m0);", u)
        self.assertIn('throw new IllegalStateException("the union member is not selected");',
                      files["M/U.java"])

    def test_arrays_of_typedefs_of_arrays(self):
        status, err, files = generate("typedef long Row[3]; struct S { Row m[2]; };")
        self.assertEqual(status, 0, err)
        c = files["SCodec.java"]
        self.assertIn("org.rustorb.dds.Out.checkLength(v.m, 2);", c)
        self.assertIn("for (int[] $e0 : v.m) {", c)
        self.assertIn("$out.writeInt32Array($e0);", c)

    def test_package_option(self):
        status, err, files = generate("module M { struct S { long a; }; };", "-Wbpackage=org.example")
        self.assertEqual(status, 0, err)
        self.assertIn("org/example/M/SCodec.java", files)
        self.assertIn("org.example.M.S", files["org/example/M/SCodec.java"])

    def test_autoid_hash_and_hashid(self):
        status, err, files = generate(
            '@autoid(HASH) @mutable struct S { @hashid long a; @hashid("other") long b; };')
        self.assertEqual(status, 0, err)
        c = files["SCodec.java"]
        self.assertIn("org.rustorb.dds.Types.TYPE_AUTOID_HASH", c)
        self.assertIn(', 0, "")', c)
        self.assertIn(', 0, "other")', c)

    def test_default_extensibility(self):
        status, err, files = generate("struct S { long a; };", "-Wbextensibility=final")
        self.assertEqual(status, 0, err)
        self.assertIn('StructBuilder("S", org.rustorb.dds.Types.FINAL, 0, null)', files["SCodec.java"])

    def test_corba_types_are_left_out(self):
        status, err, files = generate(
            "interface I { void f(); }; exception X { long a; }; struct S { long a; };")
        self.assertEqual(status, 0, err)
        self.assertEqual(sorted(files), ["S.java", "SCodec.java"])

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
            status, err, _ = generate(idl)
            self.assertEqual(status, 1, idl)
            self.assertIn(what, err, idl)


def javac(outdir, sources, classpath):
    classes = tempfile.mkdtemp(dir=OUT)
    files = []
    for root in sources:
        for dirpath, _, names in os.walk(root):
            files += [os.path.join(dirpath, n) for n in names if n.endswith(".java")]
    p = subprocess.run(
        [JAVAC, "-proc:none", "--release", "22", "-d", classes, "-cp", os.pathsep.join(classpath)] + files,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True)
    return p.returncode, p.stdout


@unittest.skipIf(not (RUSTORB_DDS and JAVAC), "needs RUSTORB_DDS_SRC and javac")
class CompileTest(unittest.TestCase):
    """Compiles the generated code with rustorb-dds's Java sources."""

    def dds_sources(self):
        return [os.path.join(RUSTORB_DDS, "java", "src", "main", "java")]

    def test_dds_only(self):
        for idl in ("DdsMapping.idl", "DdsXTypes.idl"):
            outdir = tempfile.mkdtemp(dir=OUT)
            status, err = run(outdir, "-Wbdds_only", os.path.join(TEST_IDL, idl))
            self.assertEqual(status, 0, err)
            rc, out = javac(outdir, [outdir] + self.dds_sources(), [])
            self.assertEqual(rc, 0, out)

    @unittest.skipIf(rustorb() is None, "needs RUSTORB_SRC")
    def test_with_corba(self):
        outdir = tempfile.mkdtemp(dir=OUT)
        status, err = run(outdir, "-Wbdds", os.path.join(TEST_IDL, "DdsCorba.idl"))
        self.assertEqual(status, 0, err)
        rc, out = javac(outdir, [outdir, rustorb("java", "src", "main", "java")] + self.dds_sources(), [])
        self.assertEqual(rc, 0, out)


if __name__ == "__main__":
    unittest.main()
