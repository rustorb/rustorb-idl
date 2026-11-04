"""Reading IDL with idl_parser, and a uniform view of its types.

The backends work on the definition nodes of idl_parser, through the
helpers here:

- :func:`load` parses one IDL file (with its includes);
- :func:`definitions` lists the definitions of a scope in the order they
  are written, with reopened modules taken apart (:class:`Item`);
- :func:`type_of` turns the type of a member, argument, typedef, ... into a
  :class:`Type`.
"""

import os

from idl_parser import bitmask as idl_bitmask
from idl_parser import bitset as idl_bitset
from idl_parser import enum as idl_enum
from idl_parser import exception as idl_exception
from idl_parser import interface as idl_interface
from idl_parser import module as idl_module
from idl_parser import native as idl_native
from idl_parser import parser as idl_parser_mod
from idl_parser import struct as idl_struct
from idl_parser import type as idl_type
from idl_parser import typedef as idl_typedef
from idl_parser import union as idl_union
from idl_parser import const as idl_const
from idl_parser import valuetype as idl_valuetype


class GeneratorError(Exception):
    """An IDL construct the generator cannot handle."""

    def __init__(self, message, node=None):
        where = ""
        if node is not None and getattr(node, "filepath", None):
            line = getattr(node, "line_number", None)
            where = "%s:%s: " % (node.filepath, line if line is not None else "?")
        Exception.__init__(self, where + message)


# ---------------------------------------------------------------------------
# Loading


class Spec(object):
    """A parsed IDL file: ``root`` is the global scope and ``path`` the
    absolute path of the file (definitions of included files have other
    ``filepath``)."""

    def __init__(self, root, path):
        self.root = root
        self.path = path

    def is_main(self, node):
        fp = getattr(node, "filepath", None)
        return fp is not None and os.path.abspath(fp) == self.path

    def included_files(self):
        """The files, other than the main one, whose definitions the main
        file can use, in the order they are first seen."""
        files = []

        def walk(scope):
            for d in scope.definitions:
                fp = getattr(d, "filepath", None)
                if isinstance(d, idl_module.IDLModule):
                    walk(d)
                    continue
                if fp is not None:
                    fp = os.path.abspath(fp)
                    if fp != self.path and fp not in files:
                        files.append(fp)

        walk(self.root)
        return files


def load(path, include_dirs=(), defines=None, encoding=None, giop=True, ami=False):
    """Parses the IDL file ``path``. With ``giop`` (code for CORBA), the
    annotations GIOP has no form for are refused (:func:`check_annotations`);
    without it (code for DDS only) they are left to the backend. With
    ``ami``, the implied IDL of callback AMI is added (:func:`add_ami`);
    ``Messaging.idl`` must then be on ``include_dirs``."""
    path = os.path.abspath(path)
    p = idl_parser_mod.IDLParser(
        idl_dirs=[os.path.abspath(d) for d in include_dirs],
        defines=defines,
        encoding=encoding,
    )
    if encoding is None:
        with open(path, "rb") as f:
            data = f.read()
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            text = data.decode("latin-1")
    else:
        with open(path, encoding=encoding) as f:
            text = f.read()
    try:
        root = p.load(text, include_dirs=[os.path.dirname(path)], filepath=path)
    except idl_exception.IDLParserException as e:
        raise GeneratorError(str(e)) from e
    if giop:
        check_annotations(root)
    if ami:
        add_ami(p, root, path)
    return Spec(root, path)


# ---------------------------------------------------------------------------
# Definitions in the order they are written


class Item(object):
    """A definition and the IDL modules it is in (``("Mapping", "Inner")``)."""

    def __init__(self, node, modules):
        self.node = node
        self.modules = modules


def _order_key(node, index):
    line = getattr(node, "line_number", None)
    return (line if line is not None else 0, index)


def definitions(spec):
    """The definitions of the main file outside modules, each with the
    modules it is in, in the order they are written. A module opened
    several times contributes its definitions where each opening is."""
    items = []

    def walk(scope, modules):
        for d in scope.definitions:
            if isinstance(d, idl_module.IDLModule):
                walk(d, modules + (d.name,))
            elif spec.is_main(d):
                items.append(Item(d, modules))

    walk(spec.root, ())
    indexed = list(enumerate(items))
    indexed.sort(key=lambda p: _order_key(p[1].node, p[0]))
    return [it for _, it in indexed]


def modules(spec):
    """Every IDL module (as a tuple of names) the main file defines
    something in, outer modules first."""
    found = []
    for it in definitions(spec):
        for i in range(1, len(it.modules) + 1):
            m = it.modules[:i]
            if m not in found:
                found.append(m)
    return found


def members_of(scope):
    """The definitions nested in an interface, struct, union or exception,
    in the order they are written."""
    return list(getattr(scope, "definitions", []) or [])


# ---------------------------------------------------------------------------
# Kinds of definitions


def is_module(n):
    return isinstance(n, idl_module.IDLModule)


def is_interface(n):
    return isinstance(n, idl_interface.IDLInterface) and not is_valuetype(n)


def is_valuetype(n):
    return isinstance(n, idl_valuetype.IDLValueType)


def is_operation(n):
    return isinstance(n, idl_interface.IDLMethod) and not isinstance(n, idl_valuetype.IDLFactory)


def is_attribute(n):
    return isinstance(n, idl_interface.IDLAttribute)


def is_exception(n):
    return isinstance(n, idl_struct.IDLException)


def is_struct(n):
    return isinstance(n, idl_struct.IDLStruct) and not is_exception(n)


def is_union(n):
    return isinstance(n, idl_union.IDLUnion)


def is_enum(n):
    return isinstance(n, idl_enum.IDLEnum)


def is_typedef(n):
    return isinstance(n, idl_typedef.IDLTypedef)


def is_const(n):
    return isinstance(n, idl_const.IDLConst)


def is_bitmask(n):
    return isinstance(n, idl_bitmask.IDLBitmask)


def is_bitset(n):
    return isinstance(n, idl_bitset.IDLBitset)


# Types of IDL 4 that only the C++ backend maps.
CXX_ONLY = {"int8": "int8", "bitmask": "bitmask", "bitset": "bitset"}


def is_native(n):
    return isinstance(n, idl_native.IDLNative)


def is_forward(n):
    return bool(getattr(n, "is_forward", False))


def kind_name(n):
    return type(n).__name__.replace("IDL", "").lower()


def scope_path(node):
    """Names of the scopes a definition is in, from the outermost module,
    and its own name: ``("CosNaming", "NamingContext", "NotFound")``."""
    names = []
    n = node
    while n is not None and n.parent is not None:
        names.append(n.name)
        n = n.parent
    return tuple(reversed(names))


def enclosing_modules(node):
    """The modules around a definition (``("Mapping", "Inner")``)."""
    names = []
    n = node.parent
    while n is not None and n.parent is not None:
        if is_module(n):
            names.append(n.name)
        n = n.parent
    return tuple(reversed(names))


def inner_scope(node):
    """The names of the interfaces / structs / unions / exceptions around
    a definition, inside its innermost module."""
    names = []
    n = node.parent
    while n is not None and n.parent is not None and not is_module(n):
        names.append(n.name)
        n = n.parent
    return tuple(reversed(names))


# ---------------------------------------------------------------------------
# Types

# Basic type names of idl_parser -> names used by the backends
BASIC = {
    "short": "short",
    "int16": "short",
    "long": "long",
    "int32": "long",
    "unsigned short": "ushort",
    "uint16": "ushort",
    "unsigned long": "ulong",
    "uint32": "ulong",
    "long long": "longlong",
    "int64": "longlong",
    "unsigned long long": "ulonglong",
    "uint64": "ulonglong",
    "float": "float",
    "double": "double",
    "long double": "longdouble",
    "boolean": "boolean",
    "char": "char",
    "wchar": "wchar",
    "octet": "octet",
    "uint8": "octet",
    "int8": "int8",
    "any": "any",
    "Object": "Object",
    "TypeCode": "TypeCode",
    "Principal": "Principal",
    "void": "void",
}


class Type(object):
    """A type as the backends see it.

    ``kind`` is one of:

    - a basic type name of :data:`BASIC` (``"long"``, ``"any"``, ...);
    - ``"string"`` / ``"wstring"`` with ``bound`` (0 if unbounded);
    - ``"sequence"`` with ``content`` and ``bound``;
    - ``"array"`` with ``content`` and ``length`` (one dimension);
    - ``"fixed"`` with ``digits`` and ``scale``;
    - ``"bitmask"`` / ``"bitset"`` with ``node`` (IDL 4; only the C++
      backend maps them);
    - ``"named"`` with ``node``: a typedef, struct, union, enum,
      exception, interface or native definition.
    """

    def __init__(self, kind, **kw):
        self.kind = kind
        self.bound = kw.get("bound", 0)
        self.content = kw.get("content")
        self.length = kw.get("length", 0)
        self.digits = kw.get("digits", 0)
        self.scale = kw.get("scale", 0)
        self.node = kw.get("node")

    def __repr__(self):
        if self.kind == "named":
            return "Type(named %s)" % "::".join(scope_path(self.node))
        return "Type(%s)" % self.kind

    def resolved(self):
        """This type with typedefs followed."""
        t = self
        while t.kind == "named" and is_typedef(t.node):
            t = type_of(t.node.type, t.node)
        return t


def type_of(t, where=None):
    """The :class:`Type` of an idl_parser type node ``t``."""
    if isinstance(t, idl_type.IDLBasicType):
        obj = t.obj
        if obj is None:
            raise GeneratorError("Can not find the type %s" % t.ref_name, where)
        return type_of(obj, where)
    if isinstance(t, idl_type.IDLVoid):
        return Type("void")
    if isinstance(t, idl_type.IDLSequence):
        return Type("sequence", content=type_of(t.inner_type, where), bound=t.bound or 0)
    if isinstance(t, idl_type.IDLArray):
        return Type("array", content=type_of(t.inner_type, where), length=t.size)
    if isinstance(t, idl_type.IDLFixed):
        return Type("fixed", digits=t.digits, scale=t.scale)
    if isinstance(t, idl_type.IDLMap):
        raise GeneratorError("map types have no form in GIOP and are not supported", where)
    if isinstance(t, idl_bitmask.IDLBitmask):
        return Type("bitmask", node=t)
    if isinstance(t, idl_bitset.IDLBitset):
        return Type("bitset", node=t)
    if isinstance(t, idl_type.IDLPrimitive):
        name = " ".join(t.name.split())
        if name.startswith("string") or name.startswith("wstring"):
            wide = name.startswith("w")
            return Type("wstring" if wide else "string", bound=t.bound or 0)
        if name in BASIC:
            return Type(BASIC[name])
        raise GeneratorError("the type %s is not supported yet" % name, where)
    if isinstance(
        t,
        (
            idl_typedef.IDLTypedef,
            idl_struct.IDLStruct,
            idl_union.IDLUnion,
            idl_enum.IDLEnum,
            idl_interface.IDLInterface,
            idl_native.IDLNative,
        ),
    ):
        if is_interface(t) and is_forward(t):
            full = full_definition(t)
            if full is not None:
                t = full
        return Type("named", node=t)
    raise GeneratorError("the type %s is not supported yet" % getattr(t, "name", t), where)


def full_definition(fwd):
    """The full definition of a forward-declared interface or valuetype,
    if there is one."""
    kind = is_valuetype if is_valuetype(fwd) else is_interface
    for d in fwd.parent.definitions:
        if kind(d) and d.name == fwd.name and not is_forward(d):
            return d
    return None


def value_bases(node):
    """The base valuetypes of a valuetype (abstract and concrete), as
    definition nodes."""
    return [b if is_valuetype(b) else b.obj for b in node.inheritances]


def concrete_base(node):
    """The concrete (stateful) base valuetype of a valuetype, or None."""
    concrete = [b for b in value_bases(node) if not b.is_abstract]
    if len(concrete) > 1:
        raise GeneratorError("a valuetype can inherit from one concrete valuetype only", node)
    return concrete[0] if concrete else None


def state_member_names(node):
    """The names of the state members of a valuetype, those of its
    concrete base valuetypes first."""
    base = concrete_base(node)
    names = state_member_names(base) if base is not None else []
    return names + [m.name for m in node.state_members]


def supported_interfaces(node):
    """The interfaces a valuetype supports, as definition nodes."""
    return [i if is_interface(i) else i.obj for i in node.supports]


def has_behaviour(node):
    """Whether a valuetype or one of its bases has operations, attributes
    or initializers, or supports an interface, which an implementation
    must provide."""
    if node.factories or node.supports or any(
        is_operation(d) or is_attribute(d) for d in node.methods + node.attributes
    ):
        return True
    return any(has_behaviour(b) for b in value_bases(node))


def repository_id(node):
    rid = node.repository_id
    if rid is None:
        raise GeneratorError("no repository ID for %s" % node.name, node)
    return rid


def raised_exceptions(op):
    """The exceptions an operation raises, as definition nodes."""
    return list(op.exceptions or [])


# ---------------------------------------------------------------------------
# IDL 4 annotations

# Annotations that change what is sent, which GIOP has no form for.
NOT_ON_GIOP = {
    "optional": "GIOP has no form for an absent member",
    "external": "GIOP has no form for an external member",
    "value": "GIOP sends an enumerator as its position, not as a value",
}


def annotation(node, name):
    """The annotation ``@name`` of a node (the last one), or None."""
    find = getattr(node, "annotation_by_name", None)
    return find(name) if find is not None else None


def check_annotations(root):
    """Refuses the annotations of :data:`NOT_ON_GIOP` anywhere in ``root``.
    The others (``@key``, ``@id``, ``@final`` and the like, which are for
    DDS) are left to the backends, which ignore what they do not map.
    Code for DDS only does not call this (see :func:`load`)."""

    def check(node):
        for name, why in NOT_ON_GIOP.items():
            if annotation(node, name) is not None:
                where = node if getattr(node, "filepath", None) else getattr(node, "parent", None)
                raise GeneratorError("@%s is not supported: %s" % (name, why), where)

    def walk(n):
        check(n)
        for attr in ("definitions", "members", "values"):
            for c in getattr(n, attr, None) or []:
                if c is not n:
                    walk(c)
        for c in getattr(n, "cases", None) or []:
            walk(c)

    walk(root)


# ---------------------------------------------------------------------------
# DDS-XTypes annotations (DDS-XTypes 1.3 7.3.1.2.1, IDL 4.2 8.3)

EXTENSIBILITY_KINDS = ("final", "appendable", "mutable")


def _flag(node, name):
    """Whether the boolean annotation ``@name`` (whose value defaults to
    TRUE when it is written) is on ``node`` and true."""
    a = annotation(node, name)
    if a is None:
        return False
    v = a.value
    if v is None or str(v).strip() == "":
        return True
    v = str(v).strip().upper()
    if v in ("TRUE", "1"):
        return True
    if v in ("FALSE", "0"):
        return False
    raise GeneratorError("@%s(%s) is not a boolean" % (name, a.value), node)


def extensibility(node, default="appendable"):
    """The extensibility kind of a struct or union: ``"final"``,
    ``"appendable"`` or ``"mutable"``, from ``@final``, ``@appendable``,
    ``@mutable`` or ``@extensibility(KIND)``, else ``default`` (appendable
    by DDS-XTypes 7.3.1.2.1.8)."""
    found = [k for k in EXTENSIBILITY_KINDS if annotation(node, k) is not None]
    a = annotation(node, "extensibility")
    if a is not None:
        v = str(a.value or "").strip().lower()
        if v not in EXTENSIBILITY_KINDS:
            raise GeneratorError("@extensibility(%s) is not FINAL, APPENDABLE or MUTABLE" % a.value, node)
        found.append(v)
    if len(set(found)) > 1:
        raise GeneratorError("%s has more than one extensibility kind" % node.name, node)
    return found[0] if found else default


def is_key(member):
    return _flag(member, "key")


def is_optional(member):
    return _flag(member, "optional")


def is_external(member):
    return _flag(member, "external")


def must_understand(member):
    """``@must_understand``; key members must always be understood
    (DDS-XTypes 7.2.2.4.4.4.6)."""
    return _flag(member, "must_understand") or is_key(member)


def _string_arg(a):
    v = a.value
    if v is None:
        return ""
    v = str(v).strip()
    if len(v) >= 2 and v[0] == v[-1] == '"':
        v = v[1:-1]
    return v


def hashed_id(name):
    """A member ID computed from a string (DDS-XTypes 7.3.1.2.1.1): the
    first 4 octets of the MD5 of its UTF-8, as a little endian integer,
    with the top 4 bits cleared."""
    import hashlib

    d = hashlib.md5(name.encode("utf-8")).digest()
    return int.from_bytes(d[:4], "little") & 0x0FFFFFFF


def autoid(node):
    """``"sequential"`` or ``"hash"``: the ``@autoid`` of a struct or union,
    else of the innermost module around it that has one, else sequential
    (DDS-XTypes 7.3.1.2.1.1). ``@autoid`` without a value is HASH (IDL 4.2
    8.3.1.2)."""
    n = node
    while n is not None:
        a = annotation(n, "autoid")
        if a is not None:
            v = str(a.value or "HASH").strip().upper()
            if v not in ("SEQUENTIAL", "HASH"):
                raise GeneratorError("@autoid(%s) is not SEQUENTIAL or HASH" % a.value, n)
            return v.lower()
        n = getattr(n, "parent", None)
    return "sequential"


MAX_MEMBER_ID = 0x0FFFFFFF


def member_ids(node, members):
    """The member IDs of the ``members`` (nodes) of a struct or union
    ``node`` (DDS-XTypes 7.3.1.2.1.1): ``@id``, ``@hashid``, else by its
    ``@autoid``: the hash of the name, or the previous ID plus one (0 for
    the first member)."""
    mode = autoid(node)
    ids = []
    prev = None
    for m in members:
        a_id = annotation(m, "id")
        a_hash = annotation(m, "hashid")
        if a_id is not None and a_hash is not None:
            raise GeneratorError("%s has both @id and @hashid" % m.name, m)
        if a_id is not None:
            try:
                mid = int(str(a_id.value).strip(), 0)
            except (TypeError, ValueError):
                raise GeneratorError("@id(%s) of %s is not an integer" % (a_id.value, m.name), m)
        elif a_hash is not None:
            mid = hashed_id(_string_arg(a_hash) or m.name)
        elif mode == "hash":
            mid = hashed_id(m.name)
        else:
            mid = 0 if prev is None else prev + 1
        if not 0 <= mid <= MAX_MEMBER_ID:
            raise GeneratorError("the member ID %#x of %s is out of range" % (mid, m.name), m)
        ids.append(mid)
        prev = mid
    seen = {}
    for m, mid in zip(members, ids):
        if mid in seen:
            raise GeneratorError(
                "%s and %s of %s have the same member ID %#x" % (seen[mid], m.name, node.name, mid),
                node,
            )
        seen[mid] = m.name
    return ids


def is_nested(node):
    """Whether a struct or union is a nested type, which is not a topic
    type: ``@topic`` says no, else ``@nested``, else the ``@default_nested``
    of the innermost module that has one, else no (DDS-XTypes 7.3.1.2.1.7,
    7.3.1.2.1.16)."""
    if annotation(node, "topic") is not None:
        return False
    if annotation(node, "nested") is not None:
        return _flag(node, "nested")
    n = getattr(node, "parent", None)
    while n is not None:
        if annotation(n, "default_nested") is not None:
            return _flag(n, "default_nested")
        n = getattr(n, "parent", None)
    return False


def bit_bound(node, default, lo, hi):
    """The ``@bit_bound`` of an enum or bitmask, checked to be in
    ``lo..hi``."""
    a = annotation(node, "bit_bound")
    if a is None:
        return default
    try:
        v = int(str(a.value).strip(), 0)
    except (TypeError, ValueError):
        v = None
    if v is None or not lo <= v <= hi:
        raise GeneratorError("@bit_bound(%s) of %s is not in %d..%d" % (a.value, node.name, lo, hi), node)
    return v


# ---------------------------------------------------------------------------
# AMI: the implied IDL of the callback model (docs/ami.md of rustorb)

_AMI_PREFIX = "AMI_"

#: The standard IDL files that come with rustorb-idl (``rustorb-idl
#: --idl-dir``).
IDL_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "idl")
#: ``Messaging.idl`` of :data:`IDL_DIR`, whose definitions the runtimes
#: provide (the Python ``rustorb.Messaging``).
MESSAGING_IDL = os.path.join(IDL_DIR, "Messaging.idl")


def ami_interfaces(root):
    """The interfaces that get an AMI handler: every interface of ``root``
    (all files) but local, abstract and forward ones, in the order they
    are written in each file."""
    found = []

    def walk(scope):
        for d in scope.definitions:
            if is_module(d):
                walk(d)
            elif is_interface(d) and not is_forward(d) and not d.is_local and not d.is_abstract:
                found.append(d)

    walk(root)
    found.sort(key=lambda n: (n.line_number or 0))
    return found


def handler_name(iface):
    """The name of the AMI handler of ``iface``: ``AMI_<I>Handler``, with
    more ``AMI_`` while it clashes with a name of the enclosing scope."""
    taken = {d.name for d in iface.parent.definitions}
    name = _AMI_PREFIX + iface.name + "Handler"
    while name in taken:
        name = _AMI_PREFIX + name
    return name


def handler_of(iface):
    """The AMI handler interface added for ``iface`` by :func:`add_ami`,
    or None."""
    return getattr(iface, "_rustorb_ami_handler", None)


def ami_source(iface):
    """The interface ``iface`` an AMI handler was made for, or None for any
    other definition."""
    return getattr(iface, "_rustorb_ami_source", None)


def idl_type_text(t):
    """The IDL text of the idl_parser type node ``t``, with names fully
    scoped, so that it means the same type anywhere."""
    if isinstance(t, idl_type.IDLBasicType):
        obj = t.obj
        if obj is None:
            raise GeneratorError("Can not find the type %s" % t.ref_name)
        return idl_type_text(obj)
    if isinstance(t, idl_type.IDLVoid):
        return "void"
    if isinstance(t, idl_type.IDLSequence):
        inner = idl_type_text(t.inner_type)
        return "sequence<%s, %d>" % (inner, t.bound) if t.bound else "sequence<%s>" % inner
    if isinstance(t, idl_type.IDLFixed):
        return "fixed<%d, %d>" % (t.digits, t.scale)
    if isinstance(t, idl_type.IDLPrimitive):
        return " ".join(t.name.split())
    if getattr(t, "parent", None) is not None and getattr(t, "name", None):
        if (is_interface(t) or is_valuetype(t)) and is_forward(t):
            t = full_definition(t) or t
        return "::" + "::".join(scope_path(t))
    raise GeneratorError("the type %s cannot be used with -Wbami" % getattr(t, "name", t))


def _all_operations(iface):
    """The operations and attributes ``iface`` declares itself (not those
    of its bases), in the order they are written."""
    members = list(iface.methods) + list(iface.attributes)
    members.sort(key=lambda n: n.line_number or 0)
    return members


def _interface_bases(iface):
    """The interfaces ``iface`` inherits directly, as full definitions."""
    out = []
    for b in iface.inheritances:
        b = b if is_interface(b) else getattr(b, "obj", b)
        if is_interface(b) and is_forward(b):
            b = full_definition(b) or b
        if is_interface(b):
            out.append(b)
    return out


def ami_operations(iface):
    """``[(member, declaring interface)]``: the two-way operations and the
    attributes of ``iface`` that get ``sendc_`` operations and handler
    operations, those it declares and those of its abstract bases (which
    have no handler of their own), in order."""
    out = []
    seen = set()

    # Abstract interfaces a concrete base already brings (with its handler).
    def reach(i):
        for b in _interface_bases(i):
            if id(b) not in seen:
                seen.add(id(b))
                reach(b)

    for b in _interface_bases(iface):
        if not b.is_abstract:
            seen.add(id(b))
            reach(b)

    def add(i):
        for b in _interface_bases(i):
            if b.is_abstract and id(b) not in seen:
                seen.add(id(b))
                add(b)
        for m in _all_operations(i):
            if is_operation(m) and m.oneway:
                continue
            out.append((m, i))

    seen.add(id(iface))
    for b in _interface_bases(iface):
        if b.is_abstract and id(b) not in seen:
            seen.add(id(b))
            add(b)
    for m in _all_operations(iface):
        if is_operation(m) and m.oneway:
            continue
        out.append((m, iface))
    return out


def _member_names(iface, names=None):
    """The names of the operations and attributes of ``iface`` and its
    bases."""
    if names is None:
        names = set()
    for m in _all_operations(iface):
        names.add(m.name)
    for b in _interface_bases(iface):
        _member_names(b, names)
    return names


def sendc_name(iface, name):
    """The name of the ``sendc_`` operation of the operation (or ``get_`` /
    ``set_`` attribute accessor) ``name`` of ``iface``: ``sendc_<name>``,
    with ``ami_`` after ``sendc_`` while it clashes with a name of the
    interface or its bases."""
    taken = _member_names(iface)
    prefix = "sendc_"
    while prefix + name in taken:
        prefix += "ami_"
    return prefix + name


def _handler_body(iface):
    """The IDL of the operations of the AMI handler of ``iface``."""
    lines = []
    excep = "(in ::Messaging::ExceptionHolder excep_holder)"

    def op(name, params):
        lines.append("    void %s(%s);" % (name, ", ".join(params)))
        lines.append("    void %s_excep%s;" % (name, excep))

    for m, _ in ami_operations(iface):
        if is_operation(m):
            params = []
            if not isinstance(m.returns, idl_type.IDLVoid):
                params.append("in %s ami_return_val" % idl_type_text(m.returns))
            for a in m.arguments:
                if a.direction in ("out", "inout"):
                    params.append("in %s %s" % (idl_type_text(a.type), a.name))
            op(m.name, params)
        else:
            op("get_" + m.name, ["in %s ami_return_val" % idl_type_text(m.type)])
            if not m.readonly:
                op("set_" + m.name, [])
    return lines


def add_ami(parser, root, path):
    """Adds the implied IDL of callback AMI to ``root``: an interface
    ``AMI_<I>Handler`` for every interface of :func:`ami_interfaces`, in
    the same module and the same file as it, after the file's own
    definitions. ``Messaging.idl`` (``Messaging::ReplyHandler`` and
    ``Messaging::ExceptionHolder``) is included by the main file if no file
    has it. The ``sendc_`` operations are not added to the AST: the
    backends write them in the stubs, from :func:`handler_of`.

    Each handler remembers its interface (:func:`ami_source`) and each
    interface its handler (:func:`handler_of`)."""
    ifaces = ami_interfaces(root)
    messaging = None
    for d in root.definitions:
        if is_module(d) and d.name == "Messaging":
            messaging = d
    has_reply_handler = messaging is not None and any(
        is_interface(d) and d.name == "ReplyHandler" for d in messaging.definitions
    )
    if not has_reply_handler:
        try:
            parser.load("#include <Messaging.idl>\n", filepath=path)
        except idl_exception.IDLParserException as e:
            raise GeneratorError(str(e)) from e
    # Interfaces by file: the included files first, in the order they are
    # first seen, so that a base's handler is made before its derived ones.
    order = Spec(root, path).included_files() + [path]
    by_file = {}
    for f in order:
        group = [i for i in ifaces if i.filepath == f]
        if group:
            by_file[f] = group
    names = {}
    for i in ifaces:
        names[id(i)] = handler_name(i)
    for filepath, group in by_file.items():
        try:
            with open(filepath, "rb") as f:
                count = f.read().count(b"\n") + 1
        except OSError:
            count = max((i.line_number or 0) for i in group) + 1
        # After the file's own lines, so that the handlers come after the
        # definitions they use when the backends sort by line.
        text = ["" for _ in range(count)]
        for i in group:
            modules = enclosing_modules(i)
            bases = []
            for b in i.inheritances:
                b = b if is_interface(b) else getattr(b, "obj", b)
                if is_interface(b) and is_forward(b):
                    b = full_definition(b) or b
                if b.is_abstract or b.is_local:
                    continue
                bases.append("::" + "::".join(enclosing_modules(b) + (names[id(b)],)))
            if not bases:
                bases = ["::Messaging::ReplyHandler"]
            open_ = " ".join("module %s {" % m for m in modules)
            close = " ".join("};" for _ in modules)
            text.append(open_)
            text.append("  interface %s : %s {" % (names[id(i)], ", ".join(bases)))
            text.extend(_handler_body(i))
            text.append("  };")
            text.append(close)
        try:
            parser.load("\n".join(text) + "\n", filepath=filepath)
        except idl_exception.IDLParserException as e:
            raise GeneratorError("-Wbami: %s" % e) from e
        for i in group:
            handler = None
            for d in i.parent.definitions:
                if is_interface(d) and d.name == names[id(i)]:
                    handler = d
            if handler is None:
                raise GeneratorError("-Wbami: the handler of %s was not made" % i.name, i)
            handler._rustorb_ami_source = i
            i._rustorb_ami_handler = handler
            rid = i.repository_id or ""
            head, sep, version = rid.rpartition(":")
            if rid.startswith("IDL:") and sep and (head.endswith("/" + i.name) or head == "IDL:" + i.name):
                handler._repo_id = "%s%s:%s" % (head[: len(head) - len(i.name)], names[id(i)], version)
