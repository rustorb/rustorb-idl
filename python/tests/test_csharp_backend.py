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
    os.path.join(INTEROP_IDL, "ValueTest.idl"),
    os.path.join(INTEROP_IDL, "CustomTest.idl"),
    os.path.join(INTEROP_IDL, "AbstractTest.idl"),
    os.path.join(CPP_IDL, "CxxMapping.idl"),
    os.path.join(CPP_IDL, "Idl4.idl"),
    os.path.join(TEST_IDL, "LocalTest.idl"),
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
        self.assertEqual(cli.main(["-bcsharp", "-Wbh=.h", "-C", OUT, path]), 2)
        self.assertEqual(cli.main(["-bcs", "-C", os.path.join(OUT, "cs"), path]), 0)

    def test_valuetypes(self):
        v = self.cs("ValueTest")
        # 7.6: an abstract class with properties (private members
        # protected), operations and factories abstract.
        self.assertIn("public abstract class Point : global::Corba.ValueBase", v)
        self.assertIn("public abstract class Point3 : global::ValueTest.Point", v)
        self.assertIn('private static readonly string[] __ids = { "IDL:ValueTest/Point3:1.0", '
                      '"IDL:ValueTest/Point:1.0" };', v)
        self.assertIn('protected string label { get; set; } = "";', v)
        self.assertIn("public abstract int doubled();", v)
        self.assertIn("[global::Omg.Types.Factory]\n        public abstract void init(int balance);", v)
        # A supported interface: its operations; the tie.
        self.assertIn("public abstract class Tally : global::Corba.ValueBase, "
                      "global::ValueTest.ICounterOperations", v)
        self.assertIn("public class CounterPOATie : CounterPOA", v)
        # The OBV_ class and the default factory of a valuetype without
        # operations, none for one with.
        self.assertIn("namespace OBV_ValueTest", v)
        self.assertIn("public Point3(int x, int y, int z, string label)", v)
        self.assertIn('global::Rustorb.Values.Default("IDL:ValueTest/Point:1.0", '
                      "() => new global::OBV_ValueTest.Point());", v)
        self.assertNotIn('Values.Default("IDL:ValueTest/Account:1.0"', v)
        self.assertIn("[global::System.Runtime.CompilerServices.ModuleInitializer]", v)
        # Value boxes.
        self.assertIn("public class LongBox : global::Corba.ValueBase", v)
        self.assertIn("public int value { get; set; }", v)
        self.assertIn("global::Rustorb.TypeCodes.ValueBox(__id, \"LongBox\"", v)
        c = self.cs("CustomTest")
        self.assertIn("public abstract class Blob : global::Corba.ValueBase, global::Corba.ICustomMarshal", c)
        self.assertIn("public abstract void marshal(global::Corba.DataOutputStream os);", c)
        a = self.cs("AbstractTest")
        # An abstract interface: the interface, the stub, read and written
        # as a reference or a value.
        self.assertIn("public interface INamed\n", a)
        self.assertIn("public class Named : global::Corba.Object, INamed", a)
        self.assertIn("public interface IPersonOperations : global::AbstractTest.INamed", a)
        self.assertIn("public abstract class Card : global::Corba.ValueBase, global::AbstractTest.INamed", a)
        self.assertIn("__out.write_abstract(__v);", a)
        self.assertIn("tk_abstract_interface", a)

    def test_ami(self):
        out = os.path.join(OUT, "ami")
        path = os.path.join(INTEROP_IDL, "InteropTest.idl")
        self.assertEqual(cli.main(["-bcsharp", "-Wbami", "-C", out, path]), 0)
        echo = self.cs("InteropTest", out)
        # The implied handler interface, on Messaging.ReplyHandler.
        self.assertIn("public interface IAMI_EchoHandlerOperations : global::Messaging.IReplyHandlerOperations", echo)
        self.assertIn("void divide_excep(global::Messaging.ExceptionHolder? excep_holder);", echo)
        # sendc_ on the stub class only.
        self.assertIn("public void sendc_divide(global::InteropTest.IAMI_EchoHandler? ami_handler, int a, int b)", echo)
        self.assertIn('global::Rustorb.Ami.Sendc(this, "divide", ami_handler,', echo)
        self.assertIn("public void sendc_get_counter(global::InteropTest.IAMI_EchoHandler? ami_handler)", echo)
        self.assertNotIn("void sendc_divide(global::InteropTest.IAMI_EchoHandler? ami_handler, int a, int b);", echo)
        # Every user exception is known to the runtime.
        self.assertIn('global::Rustorb.UserExceptions.Register<global::InteropTest.Oops>("IDL:rustorb.org/InteropTest/Oops:1.0"', echo)
        if DOTNET:
            proj = os.path.join(out, "Compile.csproj")
            with open(proj, "w") as f:
                f.write(textwrap.dedent("""\
                    <Project Sdk="Microsoft.NET.Sdk">
                      <PropertyGroup>
                        <TargetFramework>net8.0</TargetFramework>
                        <TreatWarningsAsErrors>true</TreatWarningsAsErrors>
                      </PropertyGroup>
                      <ItemGroup>
                        <ProjectReference Include="%s" />
                      </ItemGroup>
                    </Project>
                    """) % RUNTIME)
            r = subprocess.run([DOTNET, "build", proj], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stdout[-4000:] + r.stderr[-2000:])

    def test_local_interfaces(self):
        m = self.cs("LocalTest")
        # An abstract class on LocalObject to derive from, no stub, skeleton or tie.
        self.assertIn("public abstract class Loud : global::Corba.LocalObject, ILoud", m)
        # With the operations of the bases.
        self.assertIn("public abstract void shout();", m)
        self.assertIn("public abstract string greet(string who);", m)
        self.assertIn("public abstract int count { get; set; }", m)
        self.assertNotIn("GreeterPOA", m)
        self.assertIn("tk_local_interface", m)
        self.assertIn('throw new global::Corba.MARSHAL("a local object cannot be sent", 4', m)

    def test_bitmask_and_bitset(self):
        m = self.cs("Idl4")
        self.assertIn("[global::System.Flags]\n    public enum Flags : byte", m)
        self.assertIn("WRITE = (byte)1 << 3,", m)
        self.assertIn("public enum Wide : ulong", m)
        self.assertIn("HIGH = (ulong)1 << 39,", m)
        self.assertIn("public struct Header : global::System.IEquatable<Header>", m)
        self.assertIn("public short delta { get; set; }", m)
        # Sent as the unsigned integer that holds the bits, with its TypeCode.
        self.assertIn("__out.write_ushort(__x);", m)
        self.assertIn("__r.delta = (short)((long)(((__x >> 3) & 0x1FUL) << 59) >> 59);", m)
        self.assertIn("TCKind.tk_ulonglong", m)
        # int8 has the TypeCode of octet, as in the C++ mapping.
        self.assertIn("public sbyte offset { get; set; }", m)
        # @default sets the initial value; @range is checked when sent and read.
        self.assertIn("            retries = 7;\n            enabled = true;\n            ratio = 2.5d;\n", m)
        self.assertIn("if (__v.level < (short)0 || __v.level > (short)10)", m)
        self.assertIn("if (__m_step < (short)1 || __m_step > (short)5) __in.fail();", m)

    def test_unsupported(self):
        path = write_idl("Unsupported_bitset.idl", """\
            module U { bitset A { bitfield<2> a; }; bitset B : A { bitfield<3> b; }; };
            """)
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
