"""DDS-RPC 1.0: the implied IDL of the services (``@DDSService``
interfaces) for the DDS backends.

:func:`add_rpc` adds to the parsed IDL the request and reply types of the
Enhanced Service Mapping (DDS-RPC 1.0, 7.5.1.2) of every interface marked
``@DDSService`` and of the interfaces it inherits from, in the same module
and file as each interface, after the file's own definitions:

- ``I_op_In`` (the in and inout parameters) and ``I_op_Out`` (the out and
  inout parameters, then the return value as ``return_``) for each
  operation, and ``get_attribute_a`` / ``set_attribute_a`` for each
  attribute (7.5.1.1.3); an empty one has ``dds::rpc::UnusedMember
  dummy``. They are ``@appendable`` (``@mutable`` with ``@Mutable`` on the
  operation) and ``@autoid(HASH)``.
- ``I_op_Result``, ``@mutable @autoid(HASH)``: ``result`` (the Out) and,
  for each exception ``E`` the operation raises, ``<e>_ex`` (``e`` in lower
  case), all ``@optional``: the ``@Choice`` of 7.5.1.2.1.1, exactly one of
  them there. A struct cannot have a member of an exception type in IDL, so
  ``<e>_ex`` is of the struct ``E_Ex``, with the members of ``E``, next to
  ``E``.
- ``I_Request``: a member per operation of ``I`` and its bases (the
  hierarchy flattened, 7.5.1.2.6), named as the operation, of the In of the
  interface that declares it; ``I_Reply``: one of the Result per
  operation, and ``remoteEx`` (``dds::rpc::RemoteExceptionCode_t``). Both
  are ``@Choice`` too.

The member IDs are the hash of the member names (``@autoid(HASH)``,
DDS-XTypes 7.3.1.2.1.1, as ``@Autoid`` asks, 7.5.1.2.1.2), so that a client
of a base interface and the service of a derived one understand each other.

``dds::rpc`` comes from ``dds_rpc.idl`` (of ``rustorb-idl --idl-dir``),
which the main file includes when no file has it; the backends refer to
the runtime's (rustorb-dds provides it).

Each interface remembers what was made for it (:func:`service_of`).
"""

import os

from idl_parser import exception as idl_exception
from idl_parser import type as idl_type

from . import frontend as fe

#: The common types of the Basic Service Mapping (DDS-RPC 1.0, 7.5.1.1.1).
DDS_RPC_IDL = "dds_rpc.idl"


class Operation(object):
    """An operation of a service, as the implied IDL has it.

    ``name`` is its name (``get_attribute_a`` for the getter of attribute
    ``a``), ``iface`` the interface that declares it, ``ins`` and ``outs``
    the ``(name, type node)`` of its in (and inout) and out (and inout)
    parameters, ``returns`` the type node of its return value or None,
    ``return_name`` the member of the Out with it, ``raises`` the
    exceptions, ``oneway`` whether it is one-way. ``node`` is the operation
    or attribute. ``in_struct``, ``out_struct`` and ``result_struct`` are the
    implied structs, set once they are parsed."""

    def __init__(self, name, iface, node):
        self.name = name
        self.iface = iface
        self.node = node
        self.ins = []
        self.outs = []
        self.returns = None
        self.return_name = None
        self.raises = []
        self.oneway = False
        self.mutable = False
        self.in_struct = None
        self.out_struct = None
        self.result_struct = None

    def type_name(self, suffix):
        return "%s_%s_%s" % (self.iface.name, self.name, suffix)

    def exception_member(self, exc):
        return exc.name.lower() + "_ex"


def exception_struct_name(exc):
    """The struct that stands for the exception ``exc`` in a Result."""
    return exc.name + "_Ex"


class Service(object):
    """What :func:`add_rpc` made for an interface: its own operations
    (``own``), all of them with those of its bases (``operations``), its
    bases (``bases``, all of them), the names of the members of the Reply
    (``remote_ex``), and the Request and Reply structs."""

    def __init__(self, iface):
        self.iface = iface
        self.own = []
        self.operations = []
        self.bases = []
        self.remote_ex = "remoteEx"
        self.request = None
        self.reply = None


def exception_struct_of(exc):
    """Whether :func:`add_rpc` made a struct for the exception ``exc``."""
    return getattr(exc, "_rustorb_rpc_struct", False)


def is_service(iface):
    """Whether ``iface`` is marked ``@DDSService`` (DDS-RPC 1.0, 7.3.1.3)."""
    return fe.annotation(iface, "DDSService") is not None


def service_of(iface):
    """The :class:`Service` made for ``iface`` by :func:`add_rpc`, or None."""
    return getattr(iface, "_rustorb_rpc", None)


def _bases(iface):
    return fe._interface_bases(iface)


def all_bases(iface):
    """The interfaces ``iface`` inherits from, directly or not, each once,
    nearest first."""
    out = []
    seen = set()
    todo = list(_bases(iface))
    while todo:
        b = todo.pop(0)
        if id(b) in seen:
            continue
        seen.add(id(b))
        out.append(b)
        todo.extend(_bases(b))
    return out


def services(root):
    """The interfaces of ``root`` (all files) that get the implied IDL: those
    marked ``@DDSService`` and the interfaces they inherit from."""
    found = []
    seen = set()

    def add(i):
        if id(i) not in seen:
            seen.add(id(i))
            found.append(i)

    def walk(scope):
        for d in scope.definitions:
            if fe.is_module(d):
                walk(d)
            elif fe.is_interface(d) and not fe.is_forward(d) and is_service(d):
                add(d)
                for b in all_bases(d):
                    add(b)

    walk(root)
    for i in found:
        if i.is_local or i.is_abstract:
            raise fe.GeneratorError("a DDS service cannot be a local or abstract interface", i)
    return found


def _resolve_exceptions(node, names):
    from .cxx_backend import _resolve_exceptions as resolve

    return resolve(node, names)


def _own_operations(iface):
    ops = []
    for m in fe._all_operations(iface):
        if fe.is_operation(m):
            fe.reject_context(m, "DDS-RPC")
            op = Operation(m.name, iface, m)
            for a in m.arguments:
                if a.direction in ("in", "inout"):
                    op.ins.append((a.name, a.type))
                if a.direction in ("out", "inout"):
                    op.outs.append((a.name, a.type))
            if not isinstance(m.returns, idl_type.IDLVoid):
                op.returns = m.returns
            op.raises = fe.raised_exceptions(m)
            op.oneway = bool(m.oneway)
            op.mutable = fe.annotation(m, "Mutable") is not None
            ops.append(op)
        else:
            get = Operation("get_attribute_" + m.name, iface, m)
            get.returns = m.type
            get.raises = _resolve_exceptions(m, getattr(m, "getraises", None))
            ops.append(get)
            if not m.readonly:
                put = Operation("set_attribute_" + m.name, iface, m)
                put.ins.append((m.name, m.type))
                put.raises = _resolve_exceptions(m, getattr(m, "setraises", None))
                ops.append(put)
    names = set()
    for op in ops:
        if op.name in names:
            raise fe.GeneratorError("%s has two operations %s" % (iface.name, op.name), iface)
        names.add(op.name)
        if op.returns is not None:
            taken = {n for n, _ in op.outs}
            op.return_name = "return_"
            k = 1
            while op.return_name in taken:
                op.return_name = "return_%d" % k
                k += 1
    return ops


def _struct(lines, annotations, name, members):
    lines.append("  %s struct %s {" % (" ".join(annotations), name))
    if not members:
        members = ["::dds::rpc::UnusedMember dummy"]
    for m in members:
        lines.append("    %s;" % m)
    lines.append("  };")


def _types_of(op, lines):
    ext = "@mutable" if op.mutable else "@appendable"
    t = fe.idl_type_text
    _struct(
        lines,
        [ext, "@nested", "@autoid(HASH)"],
        op.type_name("In"),
        ["%s %s" % (t(ty), n) for n, ty in op.ins],
    )
    outs = ["%s %s" % (t(ty), n) for n, ty in op.outs]
    if op.returns is not None:
        outs.append("%s %s" % (t(op.returns), op.return_name))
    _struct(lines, [ext, "@nested", "@autoid(HASH)"], op.type_name("Out"), outs)
    results = ["@optional %s result" % op.type_name("Out")]
    for e in op.raises:
        results.append(
            "@optional %s %s" % (_scoped(e, exception_struct_name(e)), op.exception_member(e))
        )
    _struct(lines, ["@mutable", "@nested", "@autoid(HASH)"], op.type_name("Result"), results)


def _scoped(iface, name):
    return "::" + "::".join(fe.enclosing_modules(iface) + (name,))


def _service_types(svc, lines):
    i = svc.iface
    names = {op.name for op in svc.operations}
    k = 1
    while svc.remote_ex in names:
        svc.remote_ex = "remoteEx_%d" % k
        k += 1
    request = []
    reply = []
    for op in svc.operations:
        request.append("@optional %s %s" % (_scoped(op.iface, op.type_name("In")), op.name))
        reply.append("@optional %s %s" % (_scoped(op.iface, op.type_name("Result")), op.name))
    reply.append("@optional ::dds::rpc::RemoteExceptionCode_t %s" % svc.remote_ex)
    for name, members in (("Request", request), ("Reply", reply)):
        lines.append("  @mutable @autoid(HASH) struct %s_%s {" % (i.name, name))
        for m in members:
            lines.append("    %s;" % m)
        lines.append("  };")


def _new_exceptions(group, svcs, made):
    """The exceptions the operations of the interfaces ``group`` raise that
    have no struct yet, each once."""
    out = []
    for i in group:
        for op in svcs[id(i)].own:
            for e in op.raises:
                if fe.scope_path(e) not in made:
                    made.add(fe.scope_path(e))
                    e._rustorb_rpc_struct = True
                    out.append(e)
    return out


def _find(iface, name):
    for d in iface.parent.definitions:
        if (fe.is_struct(d)) and d.name == name:
            return d
    raise fe.GeneratorError("DDS-RPC: %s was not made" % name, iface)


def add_rpc(parser, root, path):
    """Adds the implied IDL of the services of ``root`` (see the module
    documentation). Returns the services, or [] when there is none."""
    ifaces = services(root)
    if not ifaces:
        return []
    has_rpc = any(
        fe.is_module(d)
        and d.name == "dds"
        and any(fe.is_module(m) and m.name == "rpc" for m in d.definitions)
        for d in root.definitions
    )
    if not has_rpc:
        try:
            parser.load("#include <%s>\n" % DDS_RPC_IDL, filepath=path)
        except idl_exception.IDLParserException as e:
            raise fe.GeneratorError(str(e)) from e
    svcs = {}
    for i in ifaces:
        svc = Service(i)
        svc.own = _own_operations(i)
        svcs[id(i)] = svc
    for i in ifaces:
        svc = svcs[id(i)]
        svc.bases = all_bases(i)
        names = {}
        for owner in [i] + svc.bases:
            for op in svcs[id(owner)].own:
                if op.name in names and names[op.name] is not owner:
                    raise fe.GeneratorError(
                        "%s gets two operations %s (of %s and %s)"
                        % (i.name, op.name, names[op.name].name, owner.name),
                        i,
                    )
                names[op.name] = owner
        # The bases' first, in the order they are found.
        for owner in reversed(svc.bases):
            svc.operations.extend(svcs[id(owner)].own)
        svc.operations.extend(svc.own)
    order = fe.Spec(root, path).included_files() + [path]
    made = set()
    for filepath in order:
        group = [i for i in ifaces if os.path.abspath(i.filepath) == filepath]
        if not group:
            continue
        try:
            with open(filepath, "rb") as f:
                count = f.read().count(b"\n") + 1
        except OSError:
            count = max((i.line_number or 0) for i in group) + 1
        text = ["" for _ in range(count)]
        for e in _new_exceptions(group, svcs, made):
            modules = fe.enclosing_modules(e)
            text.append(" ".join("module %s {" % m for m in modules))
            _struct(
                text,
                ["@appendable", "@nested"],
                exception_struct_name(e),
                ["%s %s" % (fe.idl_type_text(m.type), m.name) for m in e.members],
            )
            text.append(" ".join("};" for _ in modules))
        for i in group:
            svc = svcs[id(i)]
            modules = fe.enclosing_modules(i)
            text.append(" ".join("module %s {" % m for m in modules))
            for op in svc.own:
                _types_of(op, text)
            _service_types(svc, text)
            text.append(" ".join("};" for _ in modules))
        try:
            parser.load("\n".join(text) + "\n", filepath=filepath)
        except idl_exception.IDLParserException as e:
            raise fe.GeneratorError("DDS-RPC: %s" % e) from e
    for i in ifaces:
        svc = svcs[id(i)]
        for op in svc.own:
            op.in_struct = _find(i, op.type_name("In"))
            op.out_struct = _find(i, op.type_name("Out"))
            op.result_struct = _find(i, op.type_name("Result"))
        svc.request = _find(i, i.name + "_Request")
        svc.reply = _find(i, i.name + "_Reply")
        i._rustorb_rpc = svc
    return [svcs[id(i)] for i in ifaces]
