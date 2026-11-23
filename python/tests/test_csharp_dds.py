"""Tests of the DDS types of ``rustorb-idl -bcsharp`` (``-Wbdds``,
``-Wbdds_only``): what is written, and the constructs the generator
refuses. The generated code needs rustorb-dds's .NET binding
(Rustorb.Dds); it is compiled when RUSTORB_DDS_SRC names a checkout of
https://github.com/rustorb/rustorb-dds with dotnet/ and the dotnet SDK is
found (the IDL sequences come from the NuGet package Rustorb). rustorb-dds
checks that the types hash as Cyclone DDS's idlc describes them and runs
them (dotnet/tests there).

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

from _paths import CODEGEN, TEST_IDL  # noqa: E402

if CODEGEN not in sys.path:
    sys.path.insert(0, CODEGEN)

from rustorb_idl import cli  # noqa: E402

OUT = tempfile.mkdtemp(prefix="rustorb-idl-csharp-dds-test-")
RUSTORB_DDS = os.environ.get("RUSTORB_DDS_SRC") or None
if RUSTORB_DDS and not os.path.isdir(os.path.join(RUSTORB_DDS, "dotnet", "src", "Rustorb.Dds")):
    RUSTORB_DDS = None  # a rustorb-dds without the .NET binding
DOTNET = shutil.which("dotnet")
RD = "global::Rustorb.Dds"


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
        status = cli.main(["-bcsharp", "-C", outdir] + list(argv))
    return status, err.getvalue()


def read_all(outdir):
    out = {}
    for n in os.listdir(outdir):
        with open(os.path.join(outdir, n)) as f:
            out[n] = f.read()
    return out


def generate(idl_text, *options, name="T.idl"):
    """Runs -bcsharp -Wbdds_only; returns (status, stderr, {file: text})."""
    path = write_idl(name, idl_text)
    outdir = tempfile.mkdtemp(dir=OUT)
    status, err = run(outdir, "-Wbdds_only", *(list(options) + [path]))
    return status, err, read_all(outdir) if status == 0 else {}


class GeneratorTest(unittest.TestCase):
    def test_dds_only_writes_the_types_and_their_codecs(self):
        status, err, files = generate("module M { struct S { long a; }; };")
        self.assertEqual(status, 0, err)
        self.assertEqual(sorted(files), ["T.cs", "T_dds.cs"])
        for text in files.values():
            self.assertNotIn("global::CORBA", text)
            self.assertNotIn("Helper", text)

    def test_dds_writes_the_corba_code_too(self):
        path = write_idl("Both.idl", "module M { struct S { long a; }; };")
        outdir = tempfile.mkdtemp(dir=OUT)
        self.assertEqual(run(outdir, "-Wbdds", path)[0], 0)
        files = read_all(outdir)
        self.assertEqual(sorted(files), ["Both.cs", "Both_dds.cs"])
        self.assertIn("class SHelper", files["Both.cs"])
        self.assertIn("__out.WriteInt32(__v.a);", files["Both_dds.cs"])

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
        t = files["T.cs"]
        self.assertIn("B = -2,", t)
        self.assertIn("public enum F : ushort", t)
        self.assertIn("Y = (ushort)1 << 11,", t)
        self.assertIn("public const int N = 3;", t)
        self.assertIn("public sbyte k { get; set; }", t)
        self.assertIn("public string? o { get; set; }", t)
        self.assertIn("public int? ol { get; set; }", t)
        self.assertIn("public global::Omg.Types.ISequence<int> l { get; }", t)
        self.assertIn("public int[][] grid { get; set; }", t)
        self.assertIn("public int @goto { get; set; }", t)
        self.assertIn("e = global::M.E.B;", t)
        self.assertIn("grid = %s.Values.Array<int[]>(2, () => new int[3]);" % RD, t)
        self.assertIn("ext = new global::M.S2();", t)
        self.assertIn("%s.Values.Equal(l, other.l)" % RD, t)

        c = files["T_dds.cs"]
        self.assertIn('new %s.EnumBuilder("M::E", 8, %s.Extensibility.Final)' % (RD, RD), c)
        self.assertIn('.Literal("B", -2, true)', c)
        self.assertIn('new %s.BitmaskBuilder("M::F", 12, %s.Extensibility.Final)' % (RD, RD), c)
        self.assertIn('.Flag("Y", 11)', c)
        self.assertIn('return %s.Types.Alias("M::Longs",' % RD, c)
        self.assertIn("public sealed class SCodec : %s.ICodec<global::M.S>" % RD, c)
        self.assertIn('%s.Types.CheckGeneratedCode(1, "T.idl");' % RD, c)
        self.assertIn('new %s.StructBuilder("M::S", %s.Extensibility.Mutable, %s.TypeFlags.None)'
                      % (RD, RD, RD), c)
        self.assertIn('.Member("k", 0, %s.Types.Primitive(%s.TypeKind.Int8), %s.MemberFlags.Key, null)'
                      % (RD, RD, RD), c)
        self.assertIn('.Member("l", 7, global::M.LongsCodec.DdsType(), %s.MemberFlags.None, null)' % RD, c)
        self.assertIn("%s.MemberFlags.External" % RD, c)
        self.assertIn("%s.TypeFlags.Nested" % RD, c)
        self.assertIn("__out.WriteInt8(__v.k);", c)
        self.assertIn("__out.WritePresent(false);", c)
        self.assertIn("__out.WriteInt32Array(%s.Out.Flatten<int>(__v.grid, 2, 3));" % RD, c)
        self.assertIn("(int[][])%s.In.Unflatten(__in.ReadInt32Array(6), 2, 3);" % RD, c)
        self.assertIn("__out.WriteBitmask((ulong)__v.f);", c)
        self.assertIn("__out.WriteInt32(__v.@goto);", c)
        self.assertIn('.Member("x", 0, %s.Types.Primitive(%s.TypeKind.Int32), new int[] { 1, 2 }, '
                      "%s.MemberFlags.None, null)" % (RD, RD, RD), c)
        self.assertIn("global::System.Array.Empty<int>(), %s.MemberFlags.DefaultLabel" % RD, c)
        self.assertIn("[global::System.Runtime.CompilerServices.ModuleInitializer]", c)
        self.assertIn("%s.TypeSupport.Register<global::M.S>(global::M.SCodec.Instance);" % RD, c)
        self.assertNotIn("Register<global::M.E>", c)

    def test_arrays_of_typedefs_of_arrays(self):
        status, err, files = generate("typedef long Row[3]; struct S { Row m[2]; };")
        self.assertEqual(status, 0, err)
        c = files["T_dds.cs"]
        self.assertIn("%s.Out.CheckLength(__a0, 2);" % RD, c)
        self.assertIn("%s.Out.CheckLength(__e0, 3);" % RD, c)
        self.assertIn("__out.WriteInt32Array(", c)

    def test_autoid_hash_and_hashid(self):
        status, err, files = generate(
            '@autoid(HASH) @mutable struct S { @hashid long a; @hashid("other") long b; };')
        self.assertEqual(status, 0, err)
        c = files["T_dds.cs"]
        self.assertIn("%s.TypeFlags.AutoidHash" % RD, c)
        self.assertIn('MemberFlags.None, "")', c)
        self.assertIn('MemberFlags.None, "other")', c)

    def test_default_extensibility(self):
        status, err, files = generate("struct S { long a; };", "-Wbextensibility=final")
        self.assertEqual(status, 0, err)
        self.assertIn('StructBuilder("S", %s.Extensibility.Final,' % RD, files["T_dds.cs"])
        status, err, files = generate("struct S { long a; };")
        self.assertIn('StructBuilder("S", %s.Extensibility.Appendable,' % RD, files["T_dds.cs"])

    def test_corba_types_are_left_out(self):
        status, err, files = generate(
            "interface I { void f(); }; exception X { long a; }; struct S { long a; };")
        self.assertEqual(status, 0, err)
        self.assertNotIn("interface I", files["T.cs"])
        self.assertNotIn("class X", files["T.cs"])
        self.assertIn("class S ", files["T.cs"])

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


PROJECT = """<Project Sdk="Microsoft.NET.Sdk">
  <PropertyGroup>
    <TargetFramework>net8.0</TargetFramework>
    <Nullable>enable</Nullable>
    <LangVersion>12</LangVersion>
    <ImplicitUsings>disable</ImplicitUsings>
    <TreatWarningsAsErrors>true</TreatWarningsAsErrors>
  </PropertyGroup>
  <ItemGroup>
    <ProjectReference Include="%s" />
    <PackageReference Include="Rustorb" Version="0.7.0" />
  </ItemGroup>
</Project>
"""


@unittest.skipIf(not (RUSTORB_DDS and DOTNET), "needs RUSTORB_DDS_SRC and dotnet")
class CompileTest(unittest.TestCase):
    """Compiles the generated code with rustorb-dds's Rustorb.Dds."""

    def build(self, outdir):
        project = os.path.join(RUSTORB_DDS, "dotnet", "src", "Rustorb.Dds", "Rustorb.Dds.csproj")
        with open(os.path.join(outdir, "Generated.csproj"), "w") as f:
            f.write(PROJECT % project)
        p = subprocess.run([DOTNET, "build", outdir], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                           universal_newlines=True)
        return p.returncode, p.stdout

    def test_dds_only(self):
        outdir = tempfile.mkdtemp(dir=OUT)
        for idl in ("DdsMapping.idl", "DdsXTypes.idl"):
            status, err = run(outdir, "-Wbdds_only", os.path.join(TEST_IDL, idl))
            self.assertEqual(status, 0, err)
        rc, out = self.build(outdir)
        self.assertEqual(rc, 0, out)

    def test_with_corba(self):
        outdir = tempfile.mkdtemp(dir=OUT)
        status, err = run(outdir, "-Wbdds", os.path.join(TEST_IDL, "DdsCorba.idl"))
        self.assertEqual(status, 0, err)
        rc, out = self.build(outdir)
        self.assertEqual(rc, 0, out)


if __name__ == "__main__":
    unittest.main()
