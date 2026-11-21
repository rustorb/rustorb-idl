"""Tests of ``rustorb-idl -bruby``: the command line, the generated code and
the constructs the Ruby backend refuses. The generated files are checked
with ``ruby -wc`` when a ruby is found; rustorb's ruby/test loads and runs
the code of CxxMapping.idl and InteropTest.idl.

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

from _paths import CODEGEN, CPP_IDL, INTEROP_IDL, TEST_IDL  # noqa: E402

if CODEGEN not in sys.path:
    sys.path.insert(0, CODEGEN)

from rustorb_idl import cli  # noqa: E402

OUT = tempfile.mkdtemp(prefix="rustorb-idl-ruby-test-")
RUBY = os.environ.get("RUBY") or shutil.which("ruby")

IDLS = [
    os.path.join(INTEROP_IDL, "InteropTest.idl"),
    os.path.join(INTEROP_IDL, "AnyTest.idl"),
    os.path.join(INTEROP_IDL, "PoaProbe.idl"),
    os.path.join(CPP_IDL, "CxxMapping.idl"),
    os.path.join(CPP_IDL, "Idl4.idl"),
    os.path.join(TEST_IDL, "CosNaming.idl"),
    os.path.join(TEST_IDL, "LocalTest.idl"),
]
NAMES = ("InteropTest", "AnyTest", "PoaProbe", "CxxMapping", "Idl4", "CosNaming", "LocalTest")


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


class RubyBackendTest(unittest.TestCase):
    maxDiff = 2000

    @classmethod
    def setUpClass(cls):
        cls.outdir = os.path.join(OUT, "gen")
        assert cli.main(["-bruby", "-I", INTEROP_IDL, "-C", cls.outdir] + IDLS) == 0

    def stubs(self, name):
        return read(os.path.join(self.outdir, name + "C.rb"))

    def skels(self, name):
        return read(os.path.join(self.outdir, name + "S.rb"))

    def test_outputs(self):
        for name in NAMES:
            for suffix in ("C.rb", "S.rb"):
                self.assertTrue(os.path.exists(os.path.join(self.outdir, name + suffix)), name + suffix)
        self.assertIn('require "rustorb"', self.stubs("CosNaming"))
        self.assertIn("::Rustorb.check_generated_code(1)", self.stubs("CosNaming"))
        self.assertIn('require_relative "CosNamingC"', self.skels("CosNaming"))

    @unittest.skipUnless(RUBY, "no ruby")
    def test_ruby_syntax(self):
        for name in NAMES:
            for suffix in ("C.rb", "S.rb"):
                path = os.path.join(self.outdir, name + suffix)
                r = subprocess.run([RUBY, "-wc", path], capture_output=True, text=True)
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertEqual(r.stderr.strip(), "", path)

    def test_types(self):
        s = self.stubs("InteropTest")
        self.assertIn("module InteropTest\n", s)
        self.assertIn("MAGIC = 1381323604", s)
        self.assertIn("class Point < ::CORBA::Portable::Struct", s)
        self.assertIn('MEMBERS = ["x", "y"].freeze', s)
        self.assertIn("attr_accessor :x, :y", s)
        self.assertIn("::Rustorb.register_type(Point)", s)
        self.assertIn("class Oops < ::CORBA::UserException", s)
        self.assertIn("module Color\n", s)
        self.assertIn("    RED = 0\n", s)
        self.assertIn('ENUMERATORS = ["RED", "GREEN", "BLUE"].freeze', s)
        # Enumerators are also in the enclosing scope, as IDL scopes them.
        self.assertIn("\n  RED = 0\n", s)
        self.assertIn(
            "::CORBA::TypeCode.create_union_tc(ID, \"Value\", ::CORBA._tc_long, [[1, \"l\", "
            "::CORBA._tc_long], [2, \"s\", ::CORBA._tc_string], [3, \"p\", ::InteropTest::Point._tc], "
            "[4, \"seq\", ::InteropTest::LongSeq._tc], [5, \"seq\", ::InteropTest::LongSeq._tc], "
            "[:default, \"flag\", ::CORBA._tc_boolean]])",
            s,
        )
        self.assertIn('def seq = _get("seq")', s)
        self.assertIn("::Rustorb.lazy_tc(self, ID, recursive: false) { ::CORBA::TypeCode.create_alias_tc(ID, "
                      "\"Matrix\", ::CORBA::TypeCode.create_array_tc(2, ::CORBA::TypeCode.create_array_tc(3, "
                      "::CORBA._tc_double))) }", s)

    def test_interfaces(self):
        s = self.stubs("InteropTest")
        self.assertIn("module Echo\n", s)
        self.assertIn("extend ::Rustorb::InterfaceModule", s)
        self.assertIn(
            '"divide" => ::Rustorb::Operation.new("divide", result: ::CORBA._tc_long, params: [[:in, '
            "::CORBA._tc_long], [:in, ::CORBA._tc_long], [:out, ::CORBA._tc_long]], exceptions: "
            "[::InteropTest::DivideByZero])",
            s,
        )
        self.assertIn('def divide(a, b) = _invoke(::InteropTest::Echo._ops["divide"], [a, b])', s)
        self.assertIn('def swap(a, b) = _invoke(::InteropTest::Echo._ops["swap"], [a, b])', s)
        self.assertIn('def counter = _invoke(::InteropTest::Echo._ops["_get_counter"], [])', s)
        self.assertIn("def counter=(value)", s)
        self.assertNotIn("def name=(", s)  # readonly
        self.assertIn('"post" => ::Rustorb::Operation.new("post", params: [[:in, ::CORBA._tc_string]], oneway: true)', s)
        self.assertIn("::Rustorb.stub_class(self)", s)
        k = self.skels("InteropTest")
        self.assertIn("module POA\n  module InteropTest\n    class Echo < ::PortableServer::Servant", k)
        self.assertIn('IDS = ["IDL:rustorb.org/InteropTest/Echo:1.0"].freeze', k)
        self.assertIn('"_set_counter" => [:counter=, ::InteropTest::Echo._ops["_set_counter"]]', k)

    def test_inheritance(self):
        s = self.stubs("CxxMapping")
        self.assertIn("module Multi\n", s)
        self.assertIn("    include ::CxxMapping::Derived\n    include ::CxxMapping::Other\n", s)
        k = self.skels("CxxMapping")
        self.assertIn(
            'IDS = ["IDL:rustorb.org/CxxMapping/Multi:1.0", "IDL:rustorb.org/CxxMapping/Derived:1.0", '
            '"IDL:rustorb.org/CxxMapping/Other:1.0", "IDL:rustorb.org/CxxMapping/Base:1.0"].freeze',
            k,
        )
        self.assertIn('"base_op" => [:base_op, ::CxxMapping::Base._ops["base_op"]]', k)

    def test_constants_and_names(self):
        s = self.stubs("CxxMapping")
        self.assertIn('C_STRING = "abcd"', s)
        self.assertIn("C_WSTRING = [119, 105, 100, 101].freeze", s)
        self.assertIn('C_CHAR = "q"', s)
        self.assertIn("C_WCHAR = 119", s)
        self.assertIn('C_FIXED = BigDecimal("12.50")', s)
        self.assertIn("C_QUAD = ::CORBA::LongDouble.new(2.5)", s)
        self.assertIn("C_ENUM = ::CxxMapping::Fruit::BANANA", s)
        self.assertIn("GLOBAL_LIMIT = 10", s)
        # Ruby keywords and methods every object has get r_.
        self.assertIn('MEMBERS = ["r_class", "namespace"].freeze', s)
        self.assertIn('[["class", ::CORBA._tc_long], ["namespace", ::CORBA._tc_string]]', s)
        self.assertIn('"delete" => ::Rustorb::Operation.new("delete"', s)
        # A struct nested in another and its enum.
        self.assertIn("::CxxMapping::Outer::Inner._tc", s)
        self.assertIn("      OFF = 1\n", s)

    def test_idl4(self):
        s = self.stubs("Idl4")
        self.assertIn("SMALLEST = -128", s)
        self.assertIn("    WRITE = 1 << 3\n", s)
        self.assertIn("def self._tc = ::CORBA._tc_ulonglong", s)
        self.assertIn("class Header < ::Rustorb::Bitset", s)
        self.assertIn('["delta", 3, 5, :signed].freeze', s)
        self.assertIn("::CORBA::TypeCode._bitset_tc(::CORBA::TK_USHORT, self)", s)
        self.assertIn('DEFAULTS = { "retries" => 7, "enabled" => true, "ratio" => 2.5 }.freeze', s)
        self.assertIn('RANGES = { "level" => [0, 10].freeze, "step" => [1, 5].freeze }.freeze', s)
        self.assertIn('["offset", ::CORBA._tc_int8]', s)

    def test_local_interfaces(self):
        s, sk = self.stubs("LocalTest"), self.skels("LocalTest")
        # A module for the implementations, with the nested definitions; no
        # stub and no skeleton.
        self.assertIn("  module Greeter\n    ID = \"IDL:LocalTest/Greeter:1.0\"\n"
                      "    extend ::Rustorb::LocalInterfaceModule\n", s)
        self.assertIn('::CORBA::TypeCode.create_local_interface_tc(ID, "Greeter")', s)
        self.assertIn("    N = 3\n", s)
        self.assertIn("    class Msg < ::CORBA::Portable::Struct", s)
        self.assertIn("  module Loud\n    ID = \"IDL:LocalTest/Loud:1.0\"\n"
                      "    extend ::Rustorb::LocalInterfaceModule\n    include ::LocalTest::Greeter\n", s)
        self.assertIn("    include ::LocalTest::Remote\n", s)
        self.assertEqual(s.count("::Rustorb.stub_class(self)"), 1)
        self.assertIn("class Remote < ::PortableServer::Servant", sk)
        self.assertNotIn("class Greeter", sk)

    def test_lower_case_names(self):
        path = write_idl("lower.idl", """\
            module lower {
              const long max = 3;
              enum shade { dark, light };
              struct point { long X; long end; };
              interface thing { void end(in long Begin, in long hash); };
            };
            """)
        out = os.path.join(OUT, "lower")
        self.assertEqual(cli.main(["-bruby", "-C", out, path]), 0)
        s = read(os.path.join(out, "lowerC.rb"))
        self.assertIn("module Lower\n", s)
        self.assertIn("Max = 3", s)
        self.assertIn("module Shade\n", s)
        self.assertIn("Dark = 0", s)
        self.assertIn("class Point < ", s)
        self.assertIn('MEMBERS = ["X", "r_end"].freeze', s)
        self.assertIn("def r_end(_Begin, hash) = _invoke(::Lower::Thing._ops[\"end\"], [_Begin, hash])", s)
        k = read(os.path.join(out, "lowerS.rb"))
        self.assertIn("class Thing < ::PortableServer::Servant", k)
        if RUBY:
            for f in ("lowerC.rb", "lowerS.rb"):
                r = subprocess.run([RUBY, "-wc", os.path.join(out, f)], capture_output=True, text=True)
                self.assertEqual(r.returncode, 0, r.stderr)

    def test_includes(self):
        a = write_idl("inc_a.idl", "module IncA { struct S { long v; }; };\n")
        b = write_idl("inc_b.idl", '#include "inc_a.idl"\n#include <CosNaming.idl>\n'
                      "module IncB { struct T { IncA::S s; CosNaming::Name n; }; };\n")
        out = os.path.join(OUT, "inc")
        self.assertEqual(cli.main(["-bruby", "-I", os.path.dirname(a), "-C", out, b]), 0)
        s = read(os.path.join(out, "inc_bC.rb"))
        self.assertIn('require_relative "inc_aC"', s)
        # CosNaming.idl of rustorb-idl: the gem has its code.
        self.assertIn('require "CosNamingC"', s)
        self.assertNotIn("module IncA", s)

    def unsupported(self, text, message, options=()):
        path = write_idl("bad.idl", text)
        out = os.path.join(OUT, "bad")
        from io import StringIO
        err = StringIO()
        old = sys.stderr
        sys.stderr = err
        try:
            status = cli.main(["-bruby"] + list(options) + ["-C", out, path])
        finally:
            sys.stderr = old
        self.assertNotEqual(status, 0)
        self.assertIn(message, err.getvalue())

    def test_unsupported(self):
        self.unsupported("valuetype V { public long x; };\n", "valuetypes are not supported by the Ruby backend")
        self.unsupported("abstract interface A { void f(); };\n", "abstract interfaces are not supported")
        self.unsupported("bitset B { bitfield<2> a; };\nbitset C : B { bitfield<2> b; };\n",
                         "bitset inheritance is not supported")
        self.unsupported("interface I { void f(); };\n", "-Wbami is not for ruby", ["-Wbami"])


if __name__ == "__main__":
    unittest.main()
