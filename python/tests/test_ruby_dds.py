"""Tests of the DDS types of ``rustorb-idl -bruby`` (``-Wbdds``,
``-Wbdds_only``): what is written, and the constructs the generator
refuses. The generated code needs rustorb-dds's Ruby binding (the gem
rustorb-dds); it is loaded and its values are written and read back when
RUSTORB_DDS_SRC names a checkout of https://github.com/rustorb/rustorb-dds
whose ruby/ has its extension built (rake compile there). rustorb-dds
checks that the types hash as Cyclone DDS's idlc describes them and runs
them (ruby/test there).

Run from the repository root with idl_parser importable::

    PYTHONPATH=path/to/idl_parser python3 -m unittest discover -s python/tests
"""

import contextlib
import glob
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

OUT = tempfile.mkdtemp(prefix="rustorb-idl-ruby-dds-test-")
RUSTORB_DDS = os.environ.get("RUSTORB_DDS_SRC") or None
RUBY = shutil.which("ruby")
GEM_LIB = os.path.join(RUSTORB_DDS, "ruby", "lib") if RUSTORB_DDS else None
if GEM_LIB and not glob.glob(os.path.join(GEM_LIB, "rustorb", "dds", "rustorb_dds_ext.*")):
    GEM_LIB = None  # no Ruby binding, or its extension is not built
T = "::DDS::Types"


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
        status = cli.main(["-bruby", "-C", outdir] + list(argv))
    return status, err.getvalue()


def read_all(outdir):
    out = {}
    for n in os.listdir(outdir):
        with open(os.path.join(outdir, n)) as f:
            out[n] = f.read()
    return out


def generate(idl_text, *options, name="T.idl"):
    """Runs -bruby -Wbdds_only; returns (status, stderr, {file: text})."""
    path = write_idl(name, idl_text)
    outdir = tempfile.mkdtemp(dir=OUT)
    status, err = run(outdir, "-Wbdds_only", *(list(options) + [path]))
    return status, err, read_all(outdir) if status == 0 else {}


class GeneratorTest(unittest.TestCase):
    def test_dds_only_writes_the_types_with_their_dds_types(self):
        status, err, files = generate("module M { struct S { long a; }; };")
        self.assertEqual(status, 0, err)
        self.assertEqual(sorted(files), ["T_dds.rb"])
        t = files["T_dds.rb"]
        self.assertNotIn("CORBA", t)
        self.assertIn('require "rustorb/dds"', t)
        self.assertIn("class S < ::DDS::Struct", t)

    def test_dds_writes_the_corba_code_too(self):
        path = write_idl("Both.idl", "module M { struct S { long a; }; };")
        outdir = tempfile.mkdtemp(dir=OUT)
        self.assertEqual(run(outdir, "-Wbdds", path)[0], 0)
        files = read_all(outdir)
        self.assertEqual(sorted(files), ["BothC.rb", "BothS.rb", "Both_dds.rb"])
        self.assertIn("class S < ::CORBA::Portable::Struct", files["BothC.rb"])
        d = files["Both_dds.rb"]
        self.assertIn('require_relative "BothC"', d)
        self.assertIn("class ::M::S\n", d)
        self.assertNotIn("MEMBERS", d)
        self.assertIn('["a", 0, %s::INT32, 0, nil],' % T, d)

    def test_types(self):
        status, err, files = generate(
            """
            module M {
              @bit_bound(8) enum E { A, @default_literal @value(-2) B };
              @bit_bound(12) bitmask F { X, @position(11) Y };
              typedef sequence<long> Longs;
              const long N = 3;
              const int8 I = -4;
              const long double LD = 1.5;
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
                @hashid("h") string s;
              };
              union U switch (long) { case 1: case 2: long x; default: string s; };
            };
            """
        )
        self.assertEqual(status, 0, err)
        t = files["T_dds.rb"]
        self.assertIn("    B = -2\n", t)
        self.assertIn('ENUMERATORS = ["A", "B"].freeze', t)
        self.assertIn("  B = -2\n", t)
        self.assertIn('%s.enum_type("M::E", 8, :final, [["A", 0], ["B", -2, true]])' % T, t)
        self.assertIn("BIT_BOUND = 12", t)
        self.assertIn("Y = 1 << 11", t)
        self.assertIn('%s.bitmask_type("M::F", 12, :final, [["X", 0], ["Y", 11]])' % T, t)
        self.assertIn('%s.alias_type("M::Longs", %s.sequence(%s::INT32, 0))' % (T, T, T), t)
        self.assertIn("N = 3", t)
        self.assertIn("I = -4", t)
        self.assertIn("LD = ::DDS::LongDouble.new(1.5)", t)
        self.assertIn('MEMBERS = ["k", "o", "ol", "ext", "l", "grid", "e", "f", "r_goto", "s"].freeze'
                      .replace("r_goto", "goto"), t)
        self.assertIn('"e" => ::M::E::B', t)
        self.assertIn('"grid" => -> { Array.new(2) { Array.new(3, 0) } }', t)
        self.assertIn('"ext" => -> { ::M::S2.new }', t)
        self.assertIn('"o" => nil', t)
        self.assertIn('%s.struct_type(self, "M::S", :mutable, 0, [' % T, t)
        self.assertIn('["k", 0, %s::INT8, %s::KEY, nil],' % (T, T), t)
        self.assertIn('["o", 1, %s.string(0), %s::OPTIONAL, nil],' % (T, T), t)
        self.assertIn('["ext", 3, ::M::S2._dds_type, %s::EXTERNAL, nil],' % T, t)
        self.assertIn('["l", 7, ::M::Longs._dds_type, 0, nil],' % (), t)
        self.assertIn('["grid", 8, %s.array(%s::INT32, [2, 3]), 0, nil],' % (T, T), t)
        self.assertIn(", %s.string(0), 0, \"h\"]," % T, t)
        self.assertIn('%s.struct_type(self, "M::S2", :appendable, %s::NESTED, [' % (T, T), t)
        self.assertIn('%s.union_type(self, "M::U", :appendable, 0, %s::INT32, [' % (T, T), t)
        self.assertIn('["x", 0, %s::INT32, [1, 2], 0, nil],' % T, t)
        self.assertIn('["s", 1, %s.string(0), [], %s::DEFAULT_LABEL, nil],' % (T, T), t)
        self.assertIn('def x = _get("x")', t)
        self.assertIn('DEFAULTS = { "x" => 0, "s" => -> { +"" } }.freeze', t)
        self.assertIn('%s.check_generated_code(1, "T.idl")' % T, t)

    def test_ruby_names(self):
        status, err, files = generate("module demo { struct S { long class; long end; }; };")
        self.assertEqual(status, 0, err)
        t = files["T_dds.rb"]
        self.assertIn("module Demo", t)
        self.assertIn('MEMBERS = ["r_class", "r_end"].freeze', t)
        self.assertIn('["class", 0, %s::INT32, 0, nil],' % T, t)
        self.assertIn('%s.struct_type(self, "demo::S"' % T, t)

    def test_unions_by_char_bool_and_enum(self):
        status, err, files = generate(
            """
            enum E { R, G };
            union C switch (char) { case 'a': long a; };
            union B switch (boolean) { case TRUE: long t; };
            union X switch (E) { case G: long g; };
            """
        )
        self.assertEqual(status, 0, err)
        t = files["T_dds.rb"]
        self.assertIn('["a", 0, %s::INT32, [97], 0, nil],' % T, t)
        self.assertIn('["t", 0, %s::INT32, [1], 0, nil],' % T, t)
        self.assertIn('["g", 0, %s::INT32, [1], 0, nil],' % T, t)
        self.assertIn("::E._dds_type, [", t)

    def test_autoid_hash(self):
        status, err, files = generate('@autoid(HASH) @mutable struct S { @hashid long a; };')
        self.assertEqual(status, 0, err)
        self.assertIn("%s::AUTOID_HASH" % T, files["T_dds.rb"])
        self.assertIn(', 0, ""],', files["T_dds.rb"])

    def test_default_extensibility(self):
        status, err, files = generate("struct S { long a; };", "-Wbextensibility=final")
        self.assertEqual(status, 0, err)
        self.assertIn('struct_type(self, "S", :final,', files["T_dds.rb"])
        status, err, files = generate("struct S { long a; };")
        self.assertIn('struct_type(self, "S", :appendable,', files["T_dds.rb"])

    def test_corba_types_are_left_out(self):
        status, err, files = generate(
            "interface I { void f(); }; exception X { long a; }; struct S { long a; };")
        self.assertEqual(status, 0, err)
        t = files["T_dds.rb"]
        self.assertNotIn("module I", t)
        self.assertNotIn("class X", t)
        self.assertIn("class S < ::DDS::Struct", t)

    def test_includes(self):
        write_idl("Base.idl", "module B { struct P { long a; }; };")
        status, err, files = generate('#include "Base.idl"\nstruct S { B::P p; };', "-I", os.path.join(OUT, "idl"))
        self.assertEqual(status, 0, err)
        self.assertIn('require_relative "Base_dds"', files["T_dds.rb"])
        self.assertIn("::B::P._dds_type", files["T_dds.rb"])

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
            ("bitset BS { bitfield<3> a; }; struct S { BS b; };", "bitset"),
        ):
            status, err, _ = generate(idl)
            self.assertEqual(status, 1, idl)
            self.assertIn(what, err, idl)


ROUND_TRIP = """
$LOAD_PATH.unshift(ARGV.shift)
$LOAD_PATH.unshift(ARGV.shift)
ARGV.each { |f| require f }
n = 0
ObjectSpace.each_object(Class).select { |c| c < DDS::Struct || c < DDS::Union }.sort_by(&:name).each do |c|
  v = c.new
  [false, true].each do |xcdr2|
    data = DDS::Types.serialize(v, xcdr2: xcdr2, type: c)
    back = DDS::Types.deserialize(c, data)
    raise "#{c} changed: #{back.inspect}" unless back == v
  end
  n += 1
end
puts n
"""


@unittest.skipIf(not (GEM_LIB and RUBY), "needs RUSTORB_DDS_SRC with the Ruby extension built, and ruby")
class RunTest(unittest.TestCase):
    """Loads the generated code with rustorb-dds's gem and round-trips a
    new value of each struct and union."""

    def test_dds_only(self):
        outdir = tempfile.mkdtemp(dir=OUT)
        for idl in ("DdsMapping.idl", "DdsXTypes.idl"):
            status, err = run(outdir, "-Wbdds_only", os.path.join(TEST_IDL, idl))
            self.assertEqual(status, 0, err)
        p = subprocess.run([RUBY, "-w", "-e", ROUND_TRIP, GEM_LIB, outdir, "DdsMapping_dds", "DdsXTypes_dds"],
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True)
        self.assertEqual(p.returncode, 0, p.stdout)
        self.assertGreater(int(p.stdout.strip().splitlines()[-1]), 20, p.stdout)


if __name__ == "__main__":
    unittest.main()
