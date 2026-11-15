"""DDS-RPC in the Rust backend: the function-call style of the services
(``@DDSService`` interfaces) with ``-Wbdds_only -Wbxtypes``.

The request and reply types of the Enhanced Service Mapping are in the
implied IDL (see rpc.py) and written as any struct. For an interface ``I``
this adds, in its module:

- the trait ``I``, with a method for each operation ``I`` declares (and the
  getters and setters of its attributes, ``get_attribute_a`` and
  ``set_attribute_a``), which the service implements; the traits of its
  bases are its supertraits. A method takes the in and inout parameters and
  returns the return value, or the Out struct when there are out or inout
  parameters, or an ``RpcError`` of rustorb-dds: an exception of the
  operation (the enum ``IOpException``, with the ``E_Ex`` structs of the
  exceptions), a remote exception code, or a local error;
- ``IClient``, whose methods (all operations, the bases' too) send a
  request and wait for its reply (DDS-RPC 1.0, 7.11.1.5.4);
- ``IServer<S: I>``, which takes the requests and answers each by calling
  the service ``S`` (7.11.1.5.1, 7.11.1.5.3).

The topics are ``<I>_<service name>_Request`` and ``_Reply``, ``<I>`` the
interface's name with its modules joined by ``_`` and ``Service`` the
service name by default (7.4.1); a server announces those of the bases as
topic aliases (7.4.3). The code refers to rustorb-dds by the absolute path
of ``-Wbrustorb_dds`` (``::rustorb_dds`` by default), and to its
``dds::rpc`` module as an extern module.
"""

from . import frontend as fe
from . import rpc


def _snake(name):
    from .rust_backend import ident, snake

    return ident(snake(name))


def _camel(name):
    from .rust_backend import ident, camel

    return ident(camel(name))


# The methods of a client and of a server, which operations must not take.
CLIENT_METHODS = {
    "new", "with_service_name", "config", "with_config", "requester",
    "wait_for_service", "timeout", "set_timeout",
}


class RpcMixin(object):
    """The DDS-RPC part of :class:`rust_backend.RustBackend`."""

    @property
    def DDSR(self):
        return self.opt.rustorb_dds

    @property
    def RP(self):
        return self.opt.rustorb_dds + "::rpc"

    def rpc_result_type(self, op, cur):
        """The Rust type of what a method of ``op`` gives back."""
        if op.outs:
            return self.ref(op.out_struct, cur)
        if op.returns is not None:
            return self.rtype(fe.type_of(op.returns, op.node), cur, op.node)
        return "()"

    def rpc_exception_name(self, op):
        return _camel("%s_%s_Exception" % (op.iface.name, op.name))

    def rpc_exception_type(self, op, cur):
        if not op.raises:
            return "::std::convert::Infallible"
        return self.ref(op.iface, cur, name=self.rpc_exception_name(op))

    def rpc_params(self, op, cur):
        """``[(Rust name, Rust type)]`` of the in and inout parameters."""
        members = list(op.in_struct.members) if op.ins else []
        names = self.field_names(op.in_struct, [m.name for m in members])
        return [
            (n, self.dds_field_type(m, fe.type_of(m.type, m), cur)) for n, m in zip(names, members)
        ]

    def rpc_signature(self, op, cur):
        args = ", ".join("%s: %s" % p for p in self.rpc_params(op, cur))
        return "fn %s(&self%s) -> ::std::result::Result<%s, %s::RpcError<%s>>" % (
            _snake(op.name),
            ", " + args if args else "",
            self.rpc_result_type(op, cur),
            self.RP,
            self.rpc_exception_type(op, cur),
        )

    def rpc_doc(self, op):
        node = op.node
        if fe.is_operation(node):
            return "Operation `%s`." % op.name
        return "The %s of attribute `%s`." % (
            "getter" if op.name.startswith("get_") else "setter",
            node.name,
        )

    def rpc_topic_base(self, iface):
        """``<modules>_<I>``: the interface part of the topic names."""
        return "_".join(fe.scope_path(iface))

    def rpc_service(self, w, node, cur):
        svc = rpc.service_of(node)
        if self.opt.xtypes is None:
            raise fe.GeneratorError(
                "the DDS service %s needs -Wbxtypes, for the types its endpoints announce"
                % node.name,
                node,
            )
        name = self.item_name(node)
        client = name + "Client"
        server = name + "Server"
        for n, what in ((name, "trait"), (client, "client"), (server, "server")):
            self.claim(cur, n, "the %s of service %s" % (what, node.name), node)
        for op in svc.operations:
            if _snake(op.name) in CLIENT_METHODS:
                raise fe.GeneratorError(
                    "the operation %s of %s takes the name of a method of its client"
                    % (op.name, op.iface.name),
                    op.node,
                )
        request = self.item_name(svc.request)
        reply = self.item_name(svc.reply)
        rfields = self.field_names(svc.request, [m.name for m in svc.request.members])
        pfields = self.field_names(svc.reply, [m.name for m in svc.reply.members])
        remote = pfields[-1]
        full = "::".join(fe.scope_path(node))
        RP = self.RP
        D = self.DDSR

        # The exceptions of its own operations.
        for op in svc.own:
            if not op.raises:
                continue
            en = self.rpc_exception_name(op)
            self.claim(cur, en, "the exceptions of %s" % op.name, op.node)
            w("/// The exceptions of `%s` of the DDS service `%s`." % (op.name, full))
            w("#[derive(Debug, Clone)]")
            w("pub enum %s {" % en)
            for e in op.raises:
                w("    /// `%s`." % "::".join(fe.scope_path(e)))
                w("    %s(%s)," % (_camel(e.name), self.ref(e, cur, name=_camel(rpc.exception_struct_name(e)))))
            w("}")
            w()

        # The trait of the service.
        bases = [self.ref(b, cur) for b in fe._interface_bases(node)]
        w("/// The DDS service `%s` (DDS-RPC 1.0): what its implementation" % full)
        w("/// does, called by [`%s`]." % server)
        w("pub trait %s%s {" % (name, (": " + " + ".join(bases)) if bases else ""))
        w.indent()
        for op in svc.own:
            w("/// %s" % self.rpc_doc(op))
            w("%s;" % self.rpc_signature(op, cur))
        w.dedent()
        w("}")
        w()

        base = self.rpc_topic_base(node)

        # The client.
        w("/// A client of the DDS service `%s` (DDS-RPC 1.0, the function-call" % full)
        w("/// style): each method sends a request and waits for its reply.")
        w("#[derive(Debug)]")
        w("pub struct %s {" % client)
        w("    requester: %s::Requester<%s, %s>," % (RP, request, reply))
        w("    timeout: ::std::time::Duration,")
        w("}")
        w()
        w("impl %s {" % client)
        w.indent()
        w("/// A client of the topics `%s_Service_Request` and" % base)
        w("/// `%s_Service_Reply` (DDS-RPC 1.0, 7.4.1)." % base)
        w("pub fn new(participant: &%s::DomainParticipant) -> %s::Result<Self> {" % (D, D))
        w('    Self::with_config(participant, &Self::config("Service"))')
        w("}")
        w()
        w("/// A client of the topics of the service named `service_name`.")
        w(
            "pub fn with_service_name(participant: &%s::DomainParticipant, service_name: &str) -> %s::Result<Self> {"
            % (D, D)
        )
        w("    Self::with_config(participant, &Self::config(service_name))")
        w("}")
        w()
        w("/// The topics `%s_<service_name>_Request` and `_Reply`, with the" % base)
        w("/// QoS of DDS-RPC (RELIABLE, KEEP_ALL).")
        w("pub fn config(service_name: &str) -> %s::RpcConfig {" % RP)
        w('    %s::RpcConfig::new(&::std::format!("%s_{service_name}"))' % (RP, base))
        w("}")
        w()
        w("/// A client made as `config` says. It registers the request and")
        w("/// reply types.")
        w(
            "pub fn with_config(participant: &%s::DomainParticipant, config: &%s::RpcConfig) -> %s::Result<Self> {"
            % (D, RP, D)
        )
        w.indent()
        w("participant.register_type::<%s>()?;" % request)
        w("participant.register_type::<%s>()?;" % reply)
        w("Ok(%s {" % client)
        w("    requester: %s::Requester::with_config(participant, config)?," % RP)
        w("    timeout: ::std::time::Duration::from_secs(10),")
        w("})")
        w.dedent()
        w("}")
        w()
        w("/// The requester the client sends with.")
        w("pub fn requester(&self) -> &%s::Requester<%s, %s> {" % (RP, request, reply))
        w("    &self.requester")
        w("}")
        w()
        w("/// Waits until a service is matched, or `timeout` passes.")
        w("pub fn wait_for_service(&self, timeout: ::std::time::Duration) -> bool {")
        w("    self.requester.wait_for_service(timeout)")
        w("}")
        w()
        w("/// How long a call waits for its reply (10 s at first).")
        w("pub fn timeout(&self) -> ::std::time::Duration {")
        w("    self.timeout")
        w("}")
        w()
        w("/// Sets how long a call waits for its reply.")
        w("pub fn set_timeout(&mut self, timeout: ::std::time::Duration) {")
        w("    self.timeout = timeout;")
        w("}")
        for op, rf, pf in zip(svc.operations, rfields, pfields):
            w()
            self.rpc_client_method(w, op, rf, pf, remote, request, cur)
        w.dedent()
        w("}")
        w()

        # The server.
        w("/// A server of the DDS service `%s` (DDS-RPC 1.0, the function-call" % full)
        w("/// style): it takes the requests and answers each by calling the")
        w("/// service.")
        w("#[derive(Debug)]")
        w("pub struct %s<S> {" % server)
        w("    replier: %s::Replier<%s, %s>," % (RP, request, reply))
        w("    service: S,")
        w("}")
        w()
        w("impl<S: %s> %s<S> {" % (name, server))
        w.indent()
        w("/// A server of the topics `%s_Service_Request` and" % base)
        w("/// `%s_Service_Reply` (DDS-RPC 1.0, 7.4.1)." % base)
        w("pub fn new(participant: &%s::DomainParticipant, service: S) -> %s::Result<Self> {" % (D, D))
        w('    Self::with_config(participant, &Self::config("Service"), service)')
        w("}")
        w()
        w("/// A server of the topics of the service named `service_name`.")
        w(
            "pub fn with_service_name(participant: &%s::DomainParticipant, service_name: &str, service: S) -> %s::Result<Self> {"
            % (D, D)
        )
        w("    Self::with_config(participant, &Self::config(service_name), service)")
        w("}")
        w()
        aliases = [self.rpc_topic_base(b) for b in rpc.all_bases(node)]
        w("/// The topics `%s_<service_name>_Request` and `_Reply`, with the" % base)
        if aliases:
            w("/// QoS of DDS-RPC (RELIABLE, KEEP_ALL), and those of the bases as")
            w("/// aliases (DDS-RPC 1.0, 7.4.3).")
        else:
            w("/// QoS of DDS-RPC (RELIABLE, KEEP_ALL).")
        w("pub fn config(service_name: &str) -> %s::RpcConfig {" % RP)
        w.indent()
        if aliases:
            w('let mut config = %s::RpcConfig::new(&::std::format!("%s_{service_name}"));' % (RP, base))
            for kind in ("request", "reply"):
                suffix = kind.capitalize()
                w("config.%s_topic_aliases = ::std::vec![" % kind)
                for a in aliases:
                    w('    ::std::format!("%s_{service_name}_%s"),' % (a, suffix))
                w("];")
            w("config")
        else:
            w('%s::RpcConfig::new(&::std::format!("%s_{service_name}"))' % (RP, base))
        w.dedent()
        w("}")
        w()
        w("/// A server made as `config` says. It registers the request and")
        w("/// reply types.")
        w(
            "pub fn with_config(participant: &%s::DomainParticipant, config: &%s::RpcConfig, service: S) -> %s::Result<Self> {"
            % (D, RP, D)
        )
        w.indent()
        w("participant.register_type::<%s>()?;" % request)
        w("participant.register_type::<%s>()?;" % reply)
        w("Ok(%s {" % server)
        w("    replier: %s::Replier::with_config(participant, config)?," % RP)
        w("    service,")
        w("})")
        w.dedent()
        w("}")
        w()
        w("/// The service.")
        w("pub fn service(&self) -> &S {")
        w("    &self.service")
        w("}")
        w()
        w("/// The replier the server answers with.")
        w("pub fn replier(&self) -> &%s::Replier<%s, %s> {" % (RP, request, reply))
        w("    &self.replier")
        w("}")
        w()
        w("/// Waits up to `timeout` for requests and answers those that came;")
        w("/// returns how many.")
        w("pub fn process(&self, timeout: ::std::time::Duration) -> %s::Result<usize> {" % D)
        w.indent()
        w("let requests = self.replier.receive_requests(timeout)?;")
        w("let n = requests.len();")
        w("for r in requests {")
        w("    if let Some(reply) = self.dispatch(r.data) {")
        w("        self.replier.send_reply(&reply, &r.id)?;")
        w("    }")
        w("}")
        w("Ok(n)")
        w.dedent()
        w("}")
        w()
        w("/// Answers requests until `stop` is set.")
        w("pub fn run(&self, stop: &::std::sync::atomic::AtomicBool) -> %s::Result<()> {" % D)
        w("    while !stop.load(::std::sync::atomic::Ordering::Relaxed) {")
        w("        self.process(::std::time::Duration::from_millis(100))?;")
        w("    }")
        w("    Ok(())")
        w("}")
        w()
        w("/// The reply to a request, by calling the service; `None` for a")
        w("/// one-way operation.")
        w("fn dispatch(&self, request: %s) -> ::std::option::Option<%s> {" % (request, reply))
        w.indent()
        w("let present = [")
        for rf in rfields:
            w("    request.%s.is_some()," % rf)
        w("]")
        w(".iter()")
        w(".filter(|p| **p)")
        w(".count();")
        w("if present != 1 {")
        w("    return Some(%s {" % reply)
        w("        %s: Some(if present == 0 {" % remote)
        w("            %s::RemoteExceptionCode::RemoteExUnknownOperation" % RP)
        w("        } else {")
        w("            %s::RemoteExceptionCode::RemoteExInvalidArgument" % RP)
        w("        }),")
        w("        ..::std::default::Default::default()")
        w("    });")
        w("}")
        for op, rf, pf in zip(svc.operations, rfields, pfields):
            self.rpc_server_arm(w, op, rf, pf, remote, reply, cur)
        w("None")
        w.dedent()
        w("}")
        w.dedent()
        w("}")
        w()

    def rpc_out_value(self, op, var, cur):
        """The Out struct of ``op`` made from ``var``, what a method gave."""
        out = self.ref(op.out_struct, cur)
        if op.outs:
            return var
        fields = self.field_names(op.out_struct, [m.name for m in op.out_struct.members])
        if op.returns is not None:
            return "%s { %s: %s }" % (out, fields[-1], var)
        return "%s { %s: 0 }" % (out, fields[0])

    def rpc_client_method(self, w, op, rf, pf, remote, request, cur):
        RP = self.RP
        params = self.rpc_params(op, cur)
        w("/// %s" % self.rpc_doc(op))
        if op.oneway:
            w("///")
            w("/// One-way: it sends the request and does not wait.")
        w("pub %s {" % self.rpc_signature(op, cur))
        w.indent()
        if params:
            args = "%s { %s }" % (self.ref(op.in_struct, cur), ", ".join(n for n, _ in params))
        else:
            dummy = self.field_names(op.in_struct, [m.name for m in op.in_struct.members])[0]
            args = "%s { %s: 0 }" % (self.ref(op.in_struct, cur), dummy)
        w("let request = %s {" % request)
        w("    %s: Some(%s)," % (rf, args))
        w("    ..::std::default::Default::default()")
        w("};")
        if op.oneway:
            w("self.requester.send_request(&request)?;")
            w("Ok(())")
            w.dedent()
            w("}")
            return
        w("let reply = self.requester.request(&request, self.timeout)?;")
        w("if let Some(code) = reply.%s {" % remote)
        w("    return Err(%s::RpcError::Remote(code));" % RP)
        w("}")
        w("let result = reply.%s.ok_or(%s::RpcError::InvalidReply)?;" % (pf, RP))
        rfs = self.field_names(op.result_struct, [m.name for m in op.result_struct.members])
        w("if let Some(out) = result.%s {" % rfs[0])
        if op.outs:
            w("    return Ok(out);")
        elif op.returns is not None:
            ofs = self.field_names(op.out_struct, [m.name for m in op.out_struct.members])
            w("    return Ok(out.%s);" % ofs[-1])
        else:
            w("    let _ = out;")
            w("    return Ok(());")
        w("}")
        for e, f in zip(op.raises, rfs[1:]):
            w("if let Some(e) = result.%s {" % f)
            w(
                "    return Err(%s::RpcError::Exception(%s::%s(e)));"
                % (RP, self.rpc_exception_type(op, cur), _camel(e.name))
            )
            w("}")
        w("Err(%s::RpcError::InvalidReply)" % RP)
        w.dedent()
        w("}")

    def rpc_server_arm(self, w, op, rf, pf, remote, reply, cur):
        RP = self.RP
        params = self.rpc_params(op, cur)
        trait = self.ref(op.iface, cur)
        call = "<S as %s>::%s(&self.service%s)" % (
            trait,
            _snake(op.name),
            "".join(", args.%s" % n for n, _ in params),
        )
        w("if let Some(args) = request.%s {" % rf)
        w.indent()
        if not params:
            w("let _ = args;")
        if op.oneway:
            w("let _ = %s;" % call)
            w("return None;")
            w.dedent()
            w("}")
            return
        result = self.ref(op.result_struct, cur)
        rfs = self.field_names(op.result_struct, [m.name for m in op.result_struct.members])
        w("let result = match %s {" % call)
        w.indent()
        void = not op.outs and op.returns is None
        w("Ok(%s) => %s {" % ("()" if void else "v", result))
        w("    %s: Some(%s)," % (rfs[0], self.rpc_out_value(op, "v", cur)))
        w("    ..::std::default::Default::default()")
        w("},")
        if op.raises:
            w("Err(%s::RpcError::Exception(e)) => match e {" % RP)
            for e, f in zip(op.raises, rfs[1:]):
                w("    %s::%s(e) => %s {" % (self.rpc_exception_type(op, cur), _camel(e.name), result))
                w("        %s: Some(e)," % f)
                w("        ..::std::default::Default::default()")
                w("    },")
            w("},")
        else:
            w("Err(%s::RpcError::Exception(e)) => match e {}," % RP)
        w("Err(e) => {")
        w("    return Some(%s {" % reply)
        w("        %s: Some(e.remote_code())," % remote)
        w("        ..::std::default::Default::default()")
        w("    });")
        w("}")
        w.dedent()
        w("};")
        w("return Some(%s {" % reply)
        w("    %s: Some(result)," % pf)
        w("    ..::std::default::Default::default()")
        w("});")
        w.dedent()
        w("}")

    def rpc_pair_type(self, w, node, name, fields):
        """``impl BasicRequest`` / ``impl BasicReply`` for a struct marked
        ``@RPCRequestType`` / ``@RPCReplyType``, the request and reply types
        of a service defined by a pair of types in the Basic Service
        Mapping (DDS-RPC 1.0, 7.3.1.4): its member ``header`` is the
        header."""
        for ann, trait, header in (
            ("RPCRequestType", "BasicRequest", "RequestHeader"),
            ("RPCReplyType", "BasicReply", "ReplyHeader"),
        ):
            if fe.annotation(node, ann) is None:
                continue
            members = [m.name for m in node.members]
            if "header" not in members:
                raise fe.GeneratorError("@%s %s has no member header" % (ann, node.name), node)
            f = fields[members.index("header")]
            w("impl %s::%s for %s {" % (self.RP, trait, name))
            w("    fn header(&self) -> &%s::%s {" % (self.RP, header))
            w("        &self.%s" % f)
            w("    }")
            w()
            w("    fn header_mut(&mut self) -> &mut %s::%s {" % (self.RP, header))
            w("        &mut self.%s" % f)
            w("    }")
            w("}")
            w()
