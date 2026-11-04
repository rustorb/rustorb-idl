"""The implied IDL of callback AMI that -Wbami adds (frontend.add_ami)."""

import contextlib
import io
import os
import shutil
import sys
import tempfile
import unittest

from _paths import CODEGEN, TEST_IDL

if CODEGEN not in sys.path:
    sys.path.insert(0, CODEGEN)

from rustorb_idl import cli, frontend  # noqa: E402


def load(ami=True):
    return frontend.load(os.path.join(TEST_IDL, "Ami.idl"), [TEST_IDL, cli.IDL_DIR], ami=ami)


def find(scope, *names):
    n = scope
    for name in names:
        n = next(d for d in n.definitions if d.name == name and not getattr(d, "is_forward", False))
    return n


def signature(iface):
    """The operations of a handler, as IDL text."""
    out = []
    for m in iface.methods:
        args = ", ".join(
            "%s %s %s" % (a.direction, frontend.idl_type_text(a.type), a.name) for a in m.arguments
        )
        out.append("%s(%s)" % (m.name, args))
    return out


class ImpliedIdlTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.spec = load()
        cls.root = cls.spec.root

    def test_handler_operations(self):
        handler = find(self.root, "AmiTest", "AMI_CalcHandler")
        self.assertEqual(
            signature(handler),
            [
                "add(in long ami_return_val, in long carry)",
                "add_excep(in ::Messaging::ExceptionHolder excep_holder)",
                "swap(in ::AmiTest::Calc::Pairs ami_return_val, in ::AmiTest::Calc::Pairs ps)",
                "swap_excep(in ::Messaging::ExceptionHolder excep_holder)",
                "nothing()",
                "nothing_excep(in ::Messaging::ExceptionHolder excep_holder)",
                "get_label(in string ami_return_val)",
                "get_label_excep(in ::Messaging::ExceptionHolder excep_holder)",
                "set_label()",
                "set_label_excep(in ::Messaging::ExceptionHolder excep_holder)",
                "get_count(in long ami_return_val)",
                "get_count_excep(in ::Messaging::ExceptionHolder excep_holder)",
            ],
        )

    def test_handlers_follow_the_inheritance(self):
        calc = find(self.root, "AmiTest", "AMI_CalcHandler")
        base = find(self.root, "AmiTest", "AMI_BaseHandler")
        self.assertEqual([b.name for b in calc.inheritances], ["AMI_BaseHandler"])
        self.assertEqual(
            [frontend.scope_path(b.obj if hasattr(b, "obj") else b) for b in base.inheritances],
            [("Messaging", "ReplyHandler")],
        )
        # Abstract bases have no handler.
        concrete = find(self.root, "AmiTest", "AMI_ConcreteHandler")
        self.assertEqual([b.name for b in concrete.inheritances], ["ReplyHandler"])

    def test_handlers_are_in_the_file_of_their_interface(self):
        calc = find(self.root, "AmiTest", "AMI_CalcHandler")
        base = find(self.root, "AmiTest", "AMI_BaseHandler")
        self.assertTrue(self.spec.is_main(calc))
        self.assertFalse(self.spec.is_main(base))
        self.assertEqual(base.filepath, os.path.join(TEST_IDL, "AmiBase.idl"))
        # After the definitions of the file.
        names = [i.node.name for i in frontend.definitions(self.spec)]
        self.assertLess(names.index("Concrete"), names.index("AMI_CalcHandler"))
        self.assertEqual(
            self.spec.included_files(),
            [os.path.join(TEST_IDL, "AmiBase.idl"), os.path.join(cli.IDL_DIR, "Messaging.idl")],
        )

    def test_repository_ids_follow_the_interface(self):
        self.assertEqual(
            find(self.root, "AmiTest", "AMI_CalcHandler").repository_id,
            "IDL:example.org/AmiTest/AMI_CalcHandler:1.0",
        )

    def test_outside_modules(self):
        d = tempfile.mkdtemp(prefix="rustorb-idl-ami-")
        self.addCleanup(shutil.rmtree, d)
        path = os.path.join(d, "Outside.idl")
        with open(path, "w") as f:
            f.write('#pragma prefix "example.org"\ninterface Outside { void t(); };\n')
        root = frontend.load(path, [cli.IDL_DIR], ami=True).root
        handler = find(root, "AMI_OutsideHandler")
        self.assertEqual(handler.repository_id, "IDL:example.org/AMI_OutsideHandler:1.0")
        self.assertEqual(signature(handler), ["t()", "t_excep(in ::Messaging::ExceptionHolder excep_holder)"])

    def test_links(self):
        calc = find(self.root, "AmiTest", "Calc")
        handler = frontend.handler_of(calc)
        self.assertEqual(handler.name, "AMI_CalcHandler")
        self.assertIs(frontend.ami_source(handler), calc)
        self.assertIsNone(frontend.ami_source(calc))

    def test_clashing_names(self):
        self.assertEqual(frontend.handler_of(find(self.root, "AmiTest", "Clash")).name, "AMI_AMI_ClashHandler")
        self.assertEqual(
            frontend.handler_of(find(self.root, "AmiTest", "AMI_ClashHandler")).name,
            "AMI_AMI_ClashHandlerHandler",
        )

    def test_no_handlers_for_local_and_abstract_interfaces(self):
        names = {d.name for d in find(self.root, "AmiTest").definitions}
        self.assertNotIn("AMI_LocalHandler", names)
        self.assertNotIn("AMI_AbstractHandler", names)

    def test_nothing_without_ami(self):
        root = load(ami=False).root
        names = {d.name for d in find(root, "AmiTest").definitions}
        self.assertNotIn("AMI_CalcHandler", names)
        self.assertNotIn("Messaging", {d.name for d in root.definitions})


class CommandLineTest(unittest.TestCase):
    def run_cli(self, argv):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            status = cli.main(argv)
        return status, err.getvalue()

    def test_rust_refuses_ami(self):
        d = tempfile.mkdtemp(prefix="rustorb-idl-ami-")
        self.addCleanup(shutil.rmtree, d)
        status, err = self.run_cli(["-brust", "-Wbami", "-I", TEST_IDL, "-C", d, os.path.join(TEST_IDL, "Ami.idl")])
        self.assertEqual(status, 2)
        self.assertIn("-Wbami", err)

    def test_backends_write_the_handlers(self):
        for backend, path in (
            ("python", "Ami_idl.py"),
            ("c++11", "Ami.hh"),
            ("java", "AmiTest/AMI_CalcHandlerOperations.java"),
        ):
            d = tempfile.mkdtemp(prefix="rustorb-idl-ami-")
            self.addCleanup(shutil.rmtree, d)
            status, err = self.run_cli(
                ["-b" + backend, "-Wbami", "-I", TEST_IDL, "-C", d, os.path.join(TEST_IDL, "Ami.idl")]
            )
            self.assertEqual(status, 0, err)
            with open(os.path.join(d, path)) as f:
                self.assertIn("AMI_CalcHandler", f.read(), backend)


if __name__ == "__main__":
    unittest.main()
