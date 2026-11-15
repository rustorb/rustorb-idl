"""Tests of the DDS services of ``rustorb-idl -brust -Wbdds_only
-Wbxtypes`` (``@DDSService`` interfaces, DDS-RPC 1.0): the implied IDL of
the Enhanced Service Mapping and what the generator refuses. rustorb-dds
compiles and runs the generated code (its tests/rpc_service.rs and
tests/rpc.rs).

Run from the repository root with idl_parser importable::

    PYTHONPATH=path/to/idl_parser python3 -m unittest discover -s python/tests
"""

import unittest

from test_rust_dds import run, write_idl  # noqa: E402

from rustorb_idl import frontend as fe  # noqa: E402
from rustorb_idl import rpc  # noqa: E402

IDL = """
    module M {
        exception Oops { string why; };
        @DDSService interface Base {
            long add(in long a, in long b) raises (Oops);
        };
        @DDSService interface Derived : Base {
            void reset();
            double f(in double x, inout string log, out long n);
            readonly attribute string name;
        };
    };
    """


def load(text):
    return fe.load(write_idl("Rpc.idl", text), [fe.IDL_DIR], giop=False, rpc=True)


def node(spec, name):
    for it in fe.definitions(spec):
        if it.node.name == name:
            return it.node
    raise KeyError(name)


def members(n):
    return [
        (m.name, fe.idl_type_text(m.type), fe.is_optional(m)) for m in n.members
    ]


class ImpliedIdlTest(unittest.TestCase):
    def test_types_of_the_enhanced_mapping(self):
        spec = load(IDL)
        self.assertEqual(
            members(node(spec, "Base_add_In")), [("a", "long", False), ("b", "long", False)]
        )
        self.assertEqual(members(node(spec, "Base_add_Out")), [("return_", "long", False)])
        self.assertEqual(
            members(node(spec, "Base_add_Result")),
            [("result", "::M::Base_add_Out", True), ("oops_ex", "::M::Oops_Ex", True)],
        )
        self.assertEqual(members(node(spec, "Oops_Ex")), [("why", "string", False)])
        self.assertEqual(
            members(node(spec, "Derived_reset_In")), [("dummy", "::dds::rpc::UnusedMember", False)]
        )
        self.assertEqual(
            members(node(spec, "Derived_f_In")), [("x", "double", False), ("log", "string", False)]
        )
        self.assertEqual(
            members(node(spec, "Derived_f_Out")),
            [("log", "string", False), ("n", "long", False), ("return_", "double", False)],
        )
        # The hierarchy is flattened, with the types of the base.
        self.assertEqual(
            [m[:2] for m in members(node(spec, "Derived_Request"))],
            [
                ("add", "::M::Base_add_In"),
                ("reset", "::M::Derived_reset_In"),
                ("f", "::M::Derived_f_In"),
                ("get_attribute_name", "::M::Derived_get_attribute_name_In"),
            ],
        )
        reply = node(spec, "Derived_Reply")
        self.assertEqual(
            members(reply)[-1], ("remoteEx", "::dds::rpc::RemoteExceptionCode_t", True)
        )
        self.assertEqual(fe.extensibility(reply), "mutable")
        self.assertEqual(fe.autoid(reply), "hash")
        # The member IDs are the hashes of the names, the same in a base
        # and a derived Request.
        base = node(spec, "Base_Request")
        self.assertEqual(
            fe.member_ids(base, list(base.members))[0],
            fe.member_ids(node(spec, "Derived_Request"), list(node(spec, "Derived_Request").members))[0],
        )
        self.assertEqual(fe.member_ids(base, list(base.members))[0], fe.hashed_id("add"))
        svc = rpc.service_of(node(spec, "Derived"))
        self.assertEqual([op.name for op in svc.own], ["reset", "f", "get_attribute_name"])
        self.assertEqual([b.name for b in svc.bases], ["Base"])

    def test_colliding_names(self):
        spec = load(
            """
            @DDSService interface I {
                long f(out long return_);
                void remoteEx();
            };
            """
        )
        self.assertEqual(members(node(spec, "I_f_Out"))[-1][0], "return_1")
        self.assertEqual(members(node(spec, "I_Reply"))[-1][0], "remoteEx_1")

    def test_attribute_exceptions(self):
        spec = load(
            """
            exception E { long a; };
            @DDSService interface I { attribute long x getraises (E) setraises (E); };
            """
        )
        for op in ("get", "set"):
            self.assertEqual(
                members(node(spec, "I_%s_attribute_x_Result" % op))[1], ("e_ex", "::E_Ex", True)
            )

    def test_only_services(self):
        spec = load("interface Plain { void f(); };")
        self.assertIsNone(rpc.service_of(node(spec, "Plain")))


class RustTest(unittest.TestCase):
    def test_client_server_and_trait(self):
        status, err, text = run(IDL, "-Wbdds_only", "-Wbxtypes")
        self.assertEqual(status, 0, err)
        self.assertIn("const _: () = ::rustorb_dds::rpc::GENERATED_CODE_VERSION_1;", text)
        self.assertIn("pub trait Derived: Base {", text)
        self.assertIn("pub struct DerivedClient {", text)
        self.assertIn("pub struct DerivedServer<S> {", text)
        self.assertIn("pub enum BaseAddException {", text)
        self.assertIn("Oops(OopsEx),", text)
        # The runtime's dds::rpc, not a copy.
        self.assertIn("::rustorb_dds::rpc::idl::dds::rpc::RemoteExceptionCodeT", text)
        self.assertNotIn("pub mod dds", text)
        # The topics, with the aliases of the base on the server.
        self.assertIn('::std::format!("M_Derived_{service_name}")', text)
        self.assertIn('::std::format!("M_Base_{service_name}_Request"),', text)
        self.assertIn("<S as Base>::add(&self.service, args.a, args.b)", text)

    def test_runtime_path(self):
        status, err, text = run(IDL, "-Wbdds_only", "-Wbxtypes", "-Wbrustorb_dds=crate::dds")
        self.assertEqual(status, 0, err)
        self.assertIn("crate::dds::rpc::RpcError<", text)
        self.assertIn("crate::dds::rpc::idl::dds::rpc::UnusedMember", text)

    def test_pair_of_types(self):
        status, err, text = run(
            """
            #include <dds_rpc.idl>
            @RPCRequestType struct Req { dds::rpc::RequestHeader header; long a; };
            @RPCReplyType struct Rep { dds::rpc::ReplyHeader header; };
            """,
            "-Wbdds_only",
            "-Wbextern=dds=::rustorb_dds::rpc::idl::dds",
        )
        self.assertEqual(status, 0, err)
        self.assertIn("impl ::rustorb_dds::rpc::BasicRequest for Req {", text)
        self.assertIn("impl ::rustorb_dds::rpc::BasicReply for Rep {", text)

    def test_refused(self):
        cases = [
            (IDL, ["-Wbdds_only"], "needs -Wbxtypes"),
            ("@DDSService local interface L { void f(); };", ["-Wbdds_only", "-Wbxtypes"], "local or abstract"),
            ("@DDSService interface I { void timeout(); };", ["-Wbdds_only", "-Wbxtypes"], "a method of its client"),
            (
                "interface A { attribute long x; }; @DDSService interface C : A { void get_attribute_x(); };",
                ["-Wbdds_only", "-Wbxtypes"],
                "two operations get_attribute_x",
            ),
            ("@RPCRequestType struct R { long a; };", ["-Wbdds_only"], "no member header"),
            ("exception E { long a; };", ["-Wbdds_only"], "no form in DDS"),
        ]
        for idl, options, message in cases:
            status, err, _ = run(idl, *options)
            self.assertEqual(status, 1, idl)
            self.assertIn(message, err, idl)


if __name__ == "__main__":
    unittest.main()
