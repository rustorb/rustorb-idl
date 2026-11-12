"""Tests of the rustorb-idl command line that do not depend on a backend.

Run from the repository root with idl_parser importable::

    PYTHONPATH=path/to/idl_parser python3 -m unittest discover -s python/tests
"""

import contextlib
import io
import os
import shutil
import sys
import tempfile
import unittest

from _paths import CODEGEN, CPP_IDL, INTEROP_IDL, TEST_IDL, rustorb  # noqa: E402,F401

if CODEGEN not in sys.path:
    sys.path.insert(0, CODEGEN)

from rustorb_idl import cli  # noqa: E402


class IdlDirTest(unittest.TestCase):
    def test_prints_the_directory(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(cli.main(["--idl-dir"]), 0)
        self.assertEqual(out.getvalue().strip(), cli.IDL_DIR)
        self.assertTrue(os.path.isfile(os.path.join(cli.IDL_DIR, "CosNaming.idl")))

    def test_bundled_cosnaming_matches_the_test_copy(self):
        # The tests and scripts use tests/idl/CosNaming.idl; the package
        # ships the same file.
        with open(os.path.join(TEST_IDL, "CosNaming.idl"), "rb") as a:
            with open(os.path.join(cli.IDL_DIR, "CosNaming.idl"), "rb") as b:
                self.assertEqual(a.read(), b.read())

    def test_bundled_directory_is_on_the_include_path(self):
        d = tempfile.mkdtemp(prefix="rustorb-idl-cli-")
        self.addCleanup(shutil.rmtree, d)
        idl = os.path.join(d, "UsesNaming.idl")
        with open(idl, "w") as f:
            f.write('#include "CosNaming.idl"\nmodule UsesNaming { interface Finder {\n'
                    "  Object find(in CosNaming::Name n); }; };\n")
        self.assertEqual(cli.main(["-bpython", "-C", d, idl]), 0)
        self.assertTrue(os.path.isdir(os.path.join(d, "UsesNaming")))


class OutputDirectoryTest(unittest.TestCase):
    def test_creates_nested_output_directory_for_each_backend(self):
        with tempfile.TemporaryDirectory(prefix="rustorb-idl-cli-") as d:
            idl = os.path.join(d, "Echo.idl")
            with open(idl, "w") as f:
                f.write("module Example { interface Echo { string echo(in string value); }; };\n")
            for backend, output in (
                ("python", "Echo_idl.py"),
                ("c++11", "Echo.hh"),
                ("java", os.path.join("Example", "Echo.java")),
                ("rust", "echo.rs"),
            ):
                with self.subTest(backend=backend):
                    outdir = os.path.join(d, backend, "nested", "gen")
                    args = ["-b" + backend, "-C", outdir, idl]
                    if backend == "rust":
                        args.insert(1, "-Wbno_rustfmt")
                    self.assertEqual(cli.main(args), 0)
                    self.assertTrue(os.path.isfile(os.path.join(outdir, output)))
                    # An existing output directory can be reused.
                    self.assertEqual(cli.main(args), 0)


class ContextClauseTest(unittest.TestCase):
    """No backend supports the context clause of an operation (rustorb#151):
    the runtimes have no CORBA::Context to send after the arguments."""

    BACKENDS = ("python", "c++11", "java", "rust")
    LANGUAGES = {"python": "Python", "c++11": "C++", "java": "Java", "rust": "Rust"}

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="rustorb-idl-ctx-")
        self.addCleanup(shutil.rmtree, self.dir)

    def write(self, name, text):
        path = os.path.join(self.dir, name)
        with open(path, "w") as f:
            f.write(text)
        return path

    def run_cli(self, argv):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            status = cli.main(argv)
        return status, err.getvalue()

    def test_operation_with_context_is_an_error(self):
        idl = self.write(
            "Ctx.idl",
            "module Ctx {\n"
            "  interface I {\n"
            "    void plain();\n"
            '    void f(in long a) context ("A", "B*");\n'
            "  };\n"
            "};\n",
        )
        for backend in self.BACKENDS:
            with self.subTest(backend):
                out = os.path.join(self.dir, "out-" + backend)
                status, err = self.run_cli(["-b" + backend, "-C", out, idl])
                self.assertEqual(status, 1, err)
                self.assertIn(
                    "%s:4: the context clause of f is not supported by the %s backend"
                    % (idl, self.LANGUAGES[backend]),
                    err,
                )

    def test_context_in_valuetype_and_abstract_interface(self):
        cases = {
            "abstract": "module A { abstract interface B { void f() context (\"x\"); }; interface I : B {}; };\n",
            "value": "module V { valuetype W { public long x; void f() context (\"x\"); }; };\n",
        }
        for name, text in cases.items():
            idl = self.write("Ctx_%s.idl" % name, text)
            for backend in self.BACKENDS:
                with self.subTest(name=name, backend=backend):
                    out = os.path.join(self.dir, "out-%s-%s" % (name, backend))
                    status, err = self.run_cli(["-b" + backend, "-C", out, idl])
                    self.assertEqual(status, 1, err)
                    self.assertIn("the context clause of f is not supported", err)

    def test_with_ami(self):
        # The sendc_ operation of an operation with a context clause would
        # have the clause too (the implied IDL), so -Wbami is an error the
        # same way, also for an abstract base of another file, whose
        # operations get sendc_ operations in the derived interface.
        base = self.write(
            "CtxBase.idl", 'module CtxBase { abstract interface B { void f() context ("x"); }; };\n'
        )
        main = self.write(
            "CtxAmi.idl",
            '#include "CtxBase.idl"\nmodule CtxAmi { interface I : CtxBase::B { void g(); }; };\n',
        )
        for backend in ("python", "c++11", "java"):
            with self.subTest(backend):
                out = os.path.join(self.dir, "out-ami-" + backend)
                status, err = self.run_cli(
                    ["-b" + backend, "-Wbami", "-I", self.dir, "-C", out, main]
                )
                self.assertEqual(status, 1, err)
                self.assertIn(
                    "%s:1: the context clause of f is not supported by the %s backend"
                    % (base, self.LANGUAGES[backend]),
                    err,
                )


if __name__ == "__main__":
    unittest.main()
