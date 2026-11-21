"""Tests of ``rustorb-idl -bcsharp``: the command line, the generated code and
the constructs the C# backend refuses. The generated code is compiled with
the .NET runtime of rustorb (dotnet/src/Rustorb.Corba) when RUSTORB_SRC is
set and dotnet is found; rustorb's dotnet/tests run it.

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

RUNTIME = rustorb("dotnet", "src", "Rustorb.Corba", "Rustorb.Corba.csproj")
if RUNTIME and not os.path.exists(RUNTIME):
    RUNTIME = None

if CODEGEN not in sys.path:
    sys.path.insert(0, CODEGEN)

from rustorb_idl import cli  # noqa: E402

OUT = tempfile.mkdtemp(prefix="rustorb-idl-csharp-test-")
DOTNET = shutil.which("dotnet") if RUNTIME else None

IDLS = [
    os.path.join(INTEROP_IDL, "InteropTest.idl"),
    os.path.join(INTEROP_IDL, "AnyTest.idl"),
    os.path.join(INTEROP_IDL, "PoaProbe.idl"),
    os.path.join(CPP_IDL, "CxxMapping.idl"),
    os.path.join(TEST_IDL, "CosNaming.idl"),
]


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


class CSharpBackendTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.outdir = os.path.join(OUT, "gen")
        assert cli.main(["-bcsharp", "-I", INTEROP_IDL, "-C", cls.outdir] + IDLS) == 0
        cls.dotnet_dir = os.path.join(OUT, "dotnet")
        assert cli.main(["-bcsharp", "-Wbdotnet_naming", "-I", INTEROP_IDL, "-C", cls.dotnet_dir] + IDLS) == 0

    def cs(self, name, outdir=None):
        return read(os.path.join(outdir or self.outdir, name + ".cs"))

    def test_outputs(self):
        for name in ("InteropTest", "AnyTest", "PoaProbe", "CxxMapping", "CosNaming"):
            self.assertTrue(os.path.exists(os.path.join(self.outdir, name + ".cs")), name)
        echo = self.cs("InteropTest")
        self.assertIn("Do not edit", echo)
        self.assertIn("namespace InteropTest", echo)
        # A.2: the operations interface, the interface, the stub class and
        # the skeleton.
        self.assertIn("public interface IEchoOperations", echo)
        self.assertIn("public interface IEcho : global::Corba.IObject, IEchoOperations", echo)
        self.assertIn("public class Echo : global::Corba.Object, IEcho", echo)
        self.assertIn("public abstract class EchoPOA : global::PortableServer.Servant, IEchoOperations", echo)
        self.assertIn("public static class EchoHelper", echo)

    def test_mapping(self):
        echo = self.cs("InteropTest")
        # Constants of a module are in a static partial class Constants.
        self.assertIn("public static partial class Constants", echo)
        self.assertIn("public const int MAGIC = 1381323604;", echo)
        # Sequences are ISequence<T>, arrays C# arrays, and parameter modes
        # ref and out.
        self.assertIn("global::Omg.Types.ISequence<int> echo_long_seq(global::Omg.Types.ISequence<int> v);", echo)
        self.assertIn("double[][] echo_matrix(double[][] v);", echo)
        self.assertIn("int swap(ref int a, ref int b);", echo)
        self.assertIn("int divide(int a, int b, out int remainder);", echo)
        # Attributes are properties.
        self.assertIn("int counter { get; set; }", echo)
        self.assertIn("string name { get; }", echo)
        # Structs are classes with properties; sequence members have no
        # setter.
        self.assertIn("public class Record : global::System.IEquatable<Record>", echo)
        self.assertIn("public global::Omg.Types.ISequence<int> values { get; }", echo)
        # Unions: the discriminator and the Set<Member> methods.
        self.assertIn("public int Discriminator { get => __d; private set => __d = value; }", echo)
        self.assertIn("public void Setl(int value, int discriminator)", echo)
        # User exceptions derive from Corba.UserException.
        self.assertIn("public class Oops : global::Corba.UserException", echo)

        m = self.cs("CxxMapping")
        # C# keywords get @; types inside a struct or an interface nest.
        self.assertIn("public int @class { get; set; }", m)
        self.assertIn("this.@class = @class;", m)
        self.assertIn("public class Inner : global::System.IEquatable<Inner>", m)
        self.assertIn("public class BaseError : global::Corba.UserException", m)
        # Interface inheritance.
        self.assertIn(
            "public interface IMultiOperations : global::CxxMapping.IDerivedOperations, "
            "global::CxxMapping.IOtherOperations",
            m,
        )
        # fixed and long double are decimal.
        self.assertIn("decimal echo_money(decimal m, ref decimal total, out decimal whole);", m)
        self.assertIn("public const decimal C_FIXED = 12.5m;", m)
        # An escaped IDL identifier (_delete) loses its underscore, on the
        # wire too.
        self.assertIn('"delete"', m)
        self.assertIn("void delete(string what);", m)

    def test_dotnet_naming(self):
        echo = self.cs("InteropTest", self.dotnet_dir)
        self.assertIn("bool EchoBoolean(bool v);", echo)
        self.assertIn("public int Id { get; set; }", echo)
        self.assertIn('"echo_boolean"', echo)
        m = self.cs("CxxMapping", self.dotnet_dir)
        self.assertIn("public int Class { get; set; }", m)

    def test_typecodes(self):
        any_test = self.cs("AnyTest")
        # Recursion refers back to the TypeCode being built.
        self.assertIn("global::Rustorb.TypeCodes.Recursive(", any_test)
        m = self.cs("CxxMapping")
        self.assertIn("global::Rustorb.TypeCodes.Fixed(5, 2)", m)

    def test_options(self):
        path = os.path.join(INTEROP_IDL, "InteropTest.idl")
        self.assertEqual(cli.main(["-bcsharp", "-Wbami", "-C", OUT, path]), 2)
        self.assertEqual(cli.main(["-bcsharp", "-Wbh=.h", "-C", OUT, path]), 2)
        self.assertEqual(cli.main(["-bcs", "-C", os.path.join(OUT, "cs"), path]), 0)

    def test_unsupported(self):
        # rustorb#186: valuetypes, abstract and local interfaces; and the
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
                self.assertEqual(cli.main(["-bcsharp", "-C", OUT, path]), 1)

    @unittest.skipUnless(DOTNET, "needs RUSTORB_SRC and dotnet")
    def test_compile(self):
        for outdir in (self.outdir, self.dotnet_dir):
            with self.subTest(outdir):
                proj = os.path.join(outdir, "Compile.csproj")
                with open(proj, "w") as f:
                    f.write(
                        textwrap.dedent(
                            """\
                            <Project Sdk="Microsoft.NET.Sdk">
                              <PropertyGroup>
                                <TargetFramework>net8.0</TargetFramework>
                                <TreatWarningsAsErrors>true</TreatWarningsAsErrors>
                              </PropertyGroup>
                              <ItemGroup>
                                <Compile Remove="CosNaming.cs" />
                                <ProjectReference Include="%s" />
                              </ItemGroup>
                            </Project>
                            """
                        )
                        % RUNTIME
                    )
                r = subprocess.run([DOTNET, "build", proj], capture_output=True, text=True)
                self.assertEqual(r.returncode, 0, r.stdout[-4000:] + r.stderr[-2000:])


if __name__ == "__main__":
    unittest.main()
