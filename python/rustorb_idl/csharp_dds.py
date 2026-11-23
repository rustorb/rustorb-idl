"""DDS types in the C# backend: ``-bcsharp -Wbdds`` / ``-Wbdds_only``.

For each struct, union, enum, bitmask and typedef of an IDL file it writes
the class ``<Name>Codec`` into ``<name>_dds.cs``: the DDS type support for
rustorb-dds's .NET binding (``Rustorb.Dds``, ``Omg.Dds``).
``<Name>Codec.DdsType()`` builds the DDS-XTypes type
(``Rustorb.Dds.StructBuilder``...), and for structs, unions and enums
``<Name>Codec.Instance`` is a ``Rustorb.Dds.ICodec<T>`` that writes and
reads the values in the order of the type. A module initializer registers
the codecs of the structs and unions with ``Rustorb.Dds.TypeSupport``, which
``DomainParticipant.CreateTopic<T>`` asks::

    Topic<M.Greeting> topic = participant.CreateTopic<M.Greeting>("Greetings");

The types are described as the other generators of rustorb-idl describe
them (java_dds.py), so that their TypeObjects match those of other
implementations for the same IDL.

``-Wbdds`` writes the codecs as well as the CORBA code of ``-bcsharp``
(csharp_backend.py), and the classes of the types are those of the IDL4 to
C# mapping that the CORBA code uses. ``-Wbdds_only`` writes the classes of
the types without CORBA (no Helper classes; interfaces, exceptions,
valuetypes and bitsets are left out), in the same form, and allows the
annotations GIOP has no form for and the types only DDS has:

- an ``enum`` has the values of its enumerators (``@value``); a new value
  is its ``@default_literal``, else its first enumerator;
- an ``@optional`` member is nullable (``int?``, ``string?``...) and
  ``null`` when it is absent; ``@external`` is a plain member;
- ``int8`` is ``sbyte``.

The generated code of both needs the Rustorb.Dds assembly; the classes of
the types use ``Omg.Types.ISequence<T>`` for sequences (IDL4 to C#
7.2.4.2.1). Bounded strings and sequences are checked when a sample is
written.
"""

import os
import re

from . import cxx_backend
from . import frontend as fe
from .csharp_backend import (
    BASIC,
    HEADER,
    ISEQ,
    SEQ,
    CSharpBackend,
    Writer,
)
from .cxx_dds import NOT_YET
from .java_dds import TYPE_KIND, OptionalType, array_dims, default_literal

#: Must match Rustorb.Dds.Types.GENERATED_CODE_VERSION.
GENERATED_CODE_VERSION = 1

RD = "global::Rustorb.Dds"
TYPES = RD + ".Types"

TK = {
    "TK_BOOLEAN": "Boolean", "TK_BYTE": "Byte", "TK_INT8": "Int8", "TK_INT16": "Int16",
    "TK_UINT16": "Uint16", "TK_INT32": "Int32", "TK_UINT32": "Uint32", "TK_INT64": "Int64",
    "TK_UINT64": "Uint64", "TK_FLOAT32": "Float32", "TK_FLOAT64": "Float64",
    "TK_FLOAT128": "Float128", "TK_CHAR8": "Char8", "TK_CHAR16": "Char16",
}

#: IDL type -> the suffix of the Write / Read methods of Out and In.
STREAM = {
    "boolean": "Boolean",
    "octet": "Octet",
    "int8": "Int8",
    "short": "Int16",
    "ushort": "Uint16",
    "long": "Int32",
    "ulong": "Uint32",
    "longlong": "Int64",
    "ulonglong": "Uint64",
    "float": "Float32",
    "double": "Float64",
    "longdouble": "Float128",
    "char": "Char8",
    "wchar": "Char16",
}

#: The types whose arrays and sequences Out and In write and read at once.
BULK = set(STREAM) - {"longdouble"}

EXTENSIBILITY = {
    "final": RD + ".Extensibility.Final",
    "appendable": RD + ".Extensibility.Appendable",
    "mutable": RD + ".Extensibility.Mutable",
}

#: The holder TypeKind of a bitmask's bits.
VALUE_KINDS = set(BASIC) - {"longdouble"} | {"longdouble"}


class CSharpDdsTypes(CSharpBackend):
    """The classes of ``-Wbdds_only``: the structs, unions, enums and
    bitmasks of the file and its constants, with no CORBA in them."""

    dds_only = True

    def cstype(self, t, where=None):
        k = t.kind
        if k == "optional":
            return CSharpBackend.cstype(self, t.content, where).rstrip("?") + "?"
        if k in ("any", "TypeCode", "Object", "fixed"):
            raise fe.GeneratorError("%s has no form in DDS" % k, where)
        if k == "bitset":
            raise fe.GeneratorError("bitsets are not supported for DDS yet", where)
        if k == "named":
            n = self.full(t.node)
            if fe.is_interface(n) or fe.is_valuetype(n) or fe.is_exception(n) or fe.is_native(n):
                raise fe.GeneratorError("the %s %s has no form in DDS" % (fe.kind_name(n), n.name), where)
        return CSharpBackend.cstype(self, t, where)

    def members(self, node):
        if getattr(node, "base", None) is not None:
            raise fe.GeneratorError("struct inheritance is not supported", node)
        out = []
        for m in node.members:
            t = fe.type_of(m.type, m)
            if fe.is_optional(m):
                t = OptionalType(t)
            out.append((m.name, t))
        return out

    def default(self, t, where=None):
        if t.kind == "optional":
            return None
        r = t.resolved()
        if r.kind == "named" and fe.is_enum(r.node):
            return "%s.%s" % (self.scoped(r.node), self.enum_value(default_literal(r.node).name))
        if r.kind == "array":
            inner = self.default(r.content, where)
            if inner is None:
                return self.new_array(r.content, r.length)
            return "%s.Values.Array<%s>(%d, () => %s)" % (RD, self.cstype(r.content, where), r.length, inner)
        return CSharpBackend.default(self, t, where)

    def equal(self, t, a, b):
        if t.kind == "optional":
            return "global::System.Object.Equals(%s, %s)" % (a, b)
        r = t.resolved()
        if r.kind in ("sequence", "array"):
            return "%s.Values.Equal(%s, %s)" % (RD, a, b)
        return CSharpBackend.equal(self, t, a, b)

    def hash(self, t, expr):
        if t.kind == "optional":
            return expr
        r = t.resolved()
        if r.kind in ("sequence", "array"):
            return "%s.Values.Hash(%s)" % (RD, expr)
        return expr

    def literal(self, value, t):
        if t.resolved().kind == "int8":
            v = int(value)
            if not -128 <= v <= 127:
                raise fe.GeneratorError("constant %d out of range for int8" % v)
            return "(sbyte)%d" % v
        return CSharpBackend.literal(self, value, t)

    # No Helper classes, so no TypeCodes either.

    def tc_expr(self, t, where=None):
        return "null"

    # No Helper classes.

    def helper_class(self, *args, **kwargs):
        pass

    def nested(self, w, scope):
        # Types defined in a struct or a union are refused (CSharpDds).
        pass

    def definition(self, w, node):
        if fe.is_const(node):
            if fe.is_module(node.parent) or node.parent.parent is None:
                self.module_const(w, node)
        elif fe.is_enum(node):
            self.enum(w, node)
        elif fe.is_bitmask(node):
            self.bitmask(w, node)
        elif fe.is_struct(node) and not fe.is_exception(node):
            if fe.is_forward(node):
                raise fe.GeneratorError(
                    "forward declarations (of %s) are not supported for DDS" % node.name, node)
            self.struct(w, node)
        elif fe.is_union(node):
            if fe.is_forward(node):
                raise fe.GeneratorError(
                    "forward declarations (of %s) are not supported for DDS" % node.name, node)
            self.union(w, node)
        # Typedefs have no class in C#. Interfaces, exceptions, valuetypes,
        # natives and bitsets have no DDS form; -Wbdds_only leaves them out.

    def enum(self, w, node):
        name = self.type_name(node)
        w("public enum %s" % name)
        w("{")
        for v in node.values:
            w("    %s = %d," % (self.enum_value(v.name), v.value))
        w("}")
        w()

    def generate(self):
        text = CSharpBackend.generate(self)
        # The classes use the Rustorb.Dds helpers, not rustorb's.
        return text


class CSharpDds(object):
    """Writes ``<Name>Codec`` for the types of ``types``, the backend that
    names the C# types (:class:`CSharpBackend`, or :class:`CSharpDdsTypes`
    for ``-Wbdds_only``)."""

    def __init__(self, spec, types, extensibility="appendable"):
        self.spec = spec
        self.types = types
        self.extensibility = extensibility
        self.idl_name = types.idl_name
        self.dds_only = isinstance(types, CSharpDdsTypes)
        self.registrations = []

    # -- names -----------------------------------------------------------

    def check_scope(self, node):
        if fe.inner_scope(node):
            raise fe.GeneratorError(
                "%s is defined inside %s, which DDS types cannot be"
                % (node.name, "::".join(fe.inner_scope(node))),
                node,
            )

    def cs_class(self, node):
        self.check_scope(node)
        return self.types.scoped(node)

    def codec_name(self, node):
        return self.types.type_name(node).lstrip("@") + "Codec"

    def codec_class(self, node):
        self.check_scope(node)
        n = self.types.full(node)
        return self.types.qualify(n, self.codec_name(n))

    def type_name(self, node):
        return "::".join(fe.scope_path(node))

    def cstype(self, t, where):
        return self.types.cstype(t, where)

    # -- types -----------------------------------------------------------

    def check_named(self, n, where):
        if not (fe.is_typedef(n) or fe.is_struct(n) or fe.is_union(n) or fe.is_enum(n)
                or fe.is_bitmask(n)) or fe.is_exception(n):
            raise fe.GeneratorError("the %s %s has no form in DDS" % (fe.kind_name(n), n.name), where)
        if fe.is_forward(n):
            raise fe.GeneratorError(
                "%s is only declared: recursive types are not supported for DDS" % n.name, where)

    def type_expr(self, t, where):
        """A C# expression for the TypeRef of a type."""
        k = t.kind
        if k in TYPE_KIND:
            return "%s.Primitive(%s.TypeKind.%s)" % (TYPES, RD, TK[TYPE_KIND[k]])
        if k == "string":
            return "%s.String(%d)" % (TYPES, t.bound or 0)
        if k == "wstring":
            return "%s.WString(%d)" % (TYPES, t.bound or 0)
        if k == "sequence":
            return "%s.Sequence(%s, %d)" % (TYPES, self.type_expr(t.content, where), t.bound or 0)
        if k == "array":
            dims, content = array_dims(t)
            return "%s.Array(%s, %s)" % (TYPES, self.type_expr(content, where),
                                         ", ".join(str(d) for d in dims))
        if k == "bitmask":
            return self.codec_class(t.node) + ".DdsType()"
        if k == "bitset":
            raise fe.GeneratorError("bitsets are not supported for DDS yet", where)
        if k == "named":
            n = self.types.full(t.node)
            self.check_named(n, where)
            return self.codec_class(n) + ".DdsType()"
        raise fe.GeneratorError("%s has no form in DDS" % k, where)

    def resolve(self, t, where):
        """t with typedefs followed (the values are those of the type)."""
        while t.kind == "named":
            n = self.types.full(t.node)
            self.check_named(n, where)
            if not fe.is_typedef(n):
                break
            t = fe.type_of(n.type, n)
        return t

    def is_bitmask(self, t):
        return t.kind == "bitmask" or (t.kind == "named" and fe.is_bitmask(self.types.full(t.node)))

    def is_value_type(self, t, where):
        """Whether the C# type of t is a value type (Nullable<T> when @optional)."""
        t = self.resolve(t, where)
        if t.kind in BASIC or self.is_bitmask(t):
            return True
        return t.kind == "named" and fe.is_enum(self.types.full(t.node))

    # -- values ------------------------------------------------------------

    def write(self, w, t, expr, depth, where):
        """Statements that write ``expr`` of type ``t`` to ``__out``."""
        k = t.kind
        if k == "optional":
            w("if (%s is null)" % expr)
            w("{")
            w("    __out.WritePresent(false);")
            w("}")
            w("else")
            w("{")
            w.indent()
            w("__out.WritePresent(true);")
            value = expr + ".Value" if self.is_value_type(t.content, where) else expr
            self.write(w, t.content, value, depth, where)
            w.dedent()
            w("}")
            return
        t = self.resolve(t, where)
        k = t.kind
        if k in STREAM:
            w("__out.Write%s(%s);" % (STREAM[k], expr))
        elif k == "string":
            w("__out.WriteString(%s);" % expr)
        elif k == "wstring":
            w("__out.WriteWstring(%s);" % expr)
        elif k == "sequence":
            s = "__s%d" % depth
            c = t.content
            w("{")
            w.indent()
            w("var %s = %s;" % (s, expr))
            w("%s.Out.NotNull(%s);" % (RD, s))
            w("__out.WriteLength(%s.Count);" % s)
            if c.kind in BULK:
                w("__out.Write%sArray(%s);" % (STREAM[c.kind], s))
            else:
                e = "__e%d" % depth
                w("foreach (var %s in %s)" % (e, s))
                w("{")
                w.indent()
                self.write(w, c, e, depth + 1, where)
                w.dedent()
                w("}")
            w.dedent()
            w("}")
        elif k == "array":
            dims, content = array_dims(t)
            if content.kind in BULK:
                if len(dims) == 1:
                    w("%s.Out.CheckLength(%s, %d);" % (RD, expr, dims[0]))
                    w("__out.Write%sArray(%s);" % (STREAM[content.kind], expr))
                else:
                    w("__out.Write%sArray(%s.Out.Flatten<%s>(%s, %s));" % (
                        STREAM[content.kind], RD, BASIC[content.kind], expr,
                        ", ".join(str(d) for d in dims)))
            else:
                a, e = "__a%d" % depth, "__e%d" % depth
                w("{")
                w.indent()
                w("var %s = %s;" % (a, expr))
                w("%s.Out.CheckLength(%s, %d);" % (RD, a, t.length))
                w("foreach (var %s in %s)" % (e, a))
                w("{")
                w.indent()
                self.write(w, t.content, e, depth + 1, where)
                w.dedent()
                w("}")
                w.dedent()
                w("}")
        elif self.is_bitmask(t):
            w("__out.WriteBitmask((ulong)%s);" % expr)
        elif k == "named":
            w("%s.Instance.Write(__out, %s);" % (self.codec_class(t.node), expr))
        else:
            raise fe.GeneratorError("%s has no form in DDS" % k, where)

    def read(self, w, t, target, depth, where):
        """Statements that read a value of type ``t`` from ``__in`` into
        ``target``."""
        k = t.kind
        if k == "optional":
            w("if (__in.ReadPresent())")
            w("{")
            w.indent()
            x = "__o%d" % depth
            w("%s %s;" % (self.cstype(t.content, where), x))
            self.read(w, t.content, x, depth + 1, where)
            w("%s = %s;" % (target, x))
            w.dedent()
            w("}")
            w("else")
            w("{")
            w("    %s = null;" % target)
            w("}")
            return
        t = self.resolve(t, where)
        k = t.kind
        if k in STREAM:
            w("%s = __in.Read%s();" % (target, STREAM[k]))
        elif k == "string":
            w("%s = __in.ReadString();" % target)
        elif k == "wstring":
            w("%s = __in.ReadWstring();" % target)
        elif k == "sequence":
            c = t.content
            ctype = self.cstype(c, where)
            n, s = "__n%d" % depth, "__s%d" % depth
            w("{")
            w.indent()
            w("int %s = __in.ReadLength();" % n)
            if c.kind in BULK:
                w("var %s = new %s<%s>(__in.Read%sArray(%s));" % (s, SEQ, ctype, STREAM[c.kind], n))
            else:
                i, e = "__i%d" % depth, "__e%d" % depth
                w("var %s = new %s<%s>(%s);" % (s, SEQ, ctype, n))
                w("for (int %s = 0; %s < %s; %s++)" % (i, i, n, i))
                w("{")
                w.indent()
                w("%s %s;" % (ctype, e))
                self.read(w, c, e, depth + 1, where)
                w("%s.Add(%s);" % (s, e))
                w.dedent()
                w("}")
            w("%s = %s;" % (target, s))
            w.dedent()
            w("}")
        elif k == "array":
            dims, content = array_dims(t)
            if content.kind in BULK:
                if len(dims) == 1:
                    w("%s = __in.Read%sArray(%d);" % (target, STREAM[content.kind], dims[0]))
                else:
                    total = 1
                    for d in dims:
                        total *= d
                    w("%s = (%s)%s.In.Unflatten(__in.Read%sArray(%d), %s);" % (
                        target, self.cstype(t, where), RD, STREAM[content.kind], total,
                        ", ".join(str(d) for d in dims)))
            else:
                a, i = "__a%d" % depth, "__i%d" % depth
                w("{")
                w.indent()
                w("var %s = %s;" % (a, self.types.new_array(t.content, t.length)))
                w("for (int %s = 0; %s < %d; %s++)" % (i, i, t.length, i))
                w("{")
                w.indent()
                self.read(w, t.content, "%s[%s]" % (a, i), depth + 1, where)
                w.dedent()
                w("}")
                w("%s = %s;" % (target, a))
                w.dedent()
                w("}")
        elif self.is_bitmask(t):
            w("%s = (%s)__in.ReadBitmask();" % (target, self.cstype(t, where)))
        elif k == "named":
            w("%s = %s.Instance.Read(__in);" % (target, self.codec_class(t.node)))
        else:
            raise fe.GeneratorError("%s has no form in DDS" % k, where)

    def label_value(self, label, disc):
        """The integer of a union label."""
        r = disc.resolved()
        if r.kind == "named" and fe.is_enum(r.node):
            return label.value
        if r.kind == "boolean":
            return 1 if label else 0
        if r.kind in ("char", "wchar"):
            return ord(label) if isinstance(label, str) else int(label)
        return int(label)

    # -- the classes -------------------------------------------------------

    def generate(self):
        """The text of ``<name>_dds.cs``."""
        out = Writer()
        out(HEADER % self.idl_name)
        out("#nullable enable")
        out("#pragma warning disable CS1591, CS8981, CA2255")
        for it in fe.definitions(self.spec):
            n = it.node
            if fe.is_module(n) or fe.is_const(n):
                continue
            w = Writer()
            if fe.is_enum(n):
                self.enum(w, n)
            elif fe.is_bitmask(n):
                self.bitmask(w, n)
            elif fe.is_typedef(n):
                self.typedef(w, n)
            elif fe.is_struct(n) and not fe.is_exception(n):
                if fe.is_forward(n):
                    if self.dds_only:
                        raise fe.GeneratorError(
                            "forward declarations (of %s) are not supported for DDS" % n.name, n)
                    continue
                self.struct(w, n)
            elif fe.is_union(n):
                if fe.is_forward(n):
                    if self.dds_only:
                        raise fe.GeneratorError(
                            "forward declarations (of %s) are not supported for DDS" % n.name, n)
                    continue
                self.union(w, n)
            # Interfaces, exceptions, valuetypes, natives and bitsets have
            # no DDS form; they are left to the CORBA code.
            if not w.lines:
                continue
            ns = self.types.namespace_of(n)
            out()
            if ns:
                out("namespace %s" % ns)
                out("{")
                out.indent()
            for line in w.lines:
                out(line) if line else out()
            if ns:
                out.dedent()
                out("}")
        if self.registrations:
            name = re.sub(r"\W", "_", os.path.splitext(self.idl_name)[0])
            out()
            out("internal static class __RustorbDds_%s" % name)
            out("{")
            out("    [global::System.Runtime.CompilerServices.ModuleInitializer]")
            out("    internal static void Register()")
            out("    {")
            for line in self.registrations:
                out("        " + line)
            out("    }")
            out("}")
        return out.text()

    def codec(self, w, node, build, cstype=None, body=None):
        """The class ``<Name>Codec``: ``build(w)`` writes the statements
        that return the TypeRef; with ``cstype``, the class is the ICodec of
        that C# type and ``body(w)`` writes its members."""
        self.check_scope(node)
        name = self.codec_name(node)
        what = "%s %s" % (fe.kind_name(node), self.type_name(node))
        w("/// <summary>The DDS type support of the %s (rustorb-dds).</summary>" % what)
        if cstype:
            w("public sealed class %s : %s.ICodec<%s>" % (name, RD, cstype))
        else:
            w("public static class %s" % name)
        w("{")
        w.indent()
        w("private static %s.TypeRef? __type;" % RD)
        w("private static readonly object __lock = new object();")
        w()
        w("static %s()" % name)
        w("{")
        w('    %s.CheckGeneratedCode(%d, "%s");' % (TYPES, GENERATED_CODE_VERSION, self.idl_name))
        w("}")
        w()
        if cstype:
            w("public static readonly %s Instance = new %s();" % (name, name))
            w()
            w("private %s()" % name)
            w("{")
            w("}")
            w()
        w("/// <summary>The DDS-XTypes type of the %s (built once).</summary>" % what)
        w("public static %s.TypeRef DdsType()" % RD)
        w("{")
        w.indent()
        w("var __t = __type;")
        w("if (__t != null) return __t;")
        w("lock (__lock)")
        w("{")
        w("    return __type ??= Build();")
        w("}")
        w.dedent()
        w("}")
        w()
        w("private static %s.TypeRef Build()" % RD)
        w("{")
        w.indent()
        build(w)
        w.dedent()
        w("}")
        if cstype:
            w()
            w("public %s.TypeRef Type => DdsType();" % RD)
            w()
            w('public string TypeName => "%s";' % self.type_name(node))
        if body:
            w()
            body(w)
        w.dedent()
        w("}")
        w()

    def register(self, node, cstype):
        self.registrations.append("%s.TypeSupport.Register<%s>(%s.Instance);" % (
            RD, cstype, self.codec_class(node)))

    def enum(self, w, node):
        bits = fe.bit_bound(node, 32, 1, 32)
        ext = fe.extensibility(node, "final")
        default = default_literal(node)
        c = self.cs_class(node)

        def build(w):
            w('return new %s.EnumBuilder("%s", %d, %s)' % (RD, self.type_name(node), bits, EXTENSIBILITY[ext]))
            for v in node.values:
                if fe.annotation(v, "default_literal") is not None and v is default:
                    w('    .Literal("%s", %d, true)' % (v.name, v.value))
                else:
                    w('    .Literal("%s", %d)' % (v.name, v.value))
            w("    .Build();")

        def body(w):
            w("public %s NewValue() => %s.%s;" % (c, c, self.types.enum_value(default.name)))
            w()
            w("public void Write(%s.Out __out, %s __v) => __out.WriteEnum((int)__v);" % (RD, c))
            w()
            w("public %s Read(%s.In __in) => (%s)__in.ReadEnum();" % (c, RD, c))

        self.codec(w, node, build, c, body)

    def bitmask(self, w, node):
        bits = node.bit_bound
        for v in node.values:
            if v.position >= bits:
                raise fe.GeneratorError(
                    "the position %d of %s is not below @bit_bound(%d)" % (v.position, v.name, bits),
                    node)
        ext = fe.extensibility(node, "final")

        def build(w):
            w('return new %s.BitmaskBuilder("%s", %d, %s)' % (RD, self.type_name(node), bits,
                                                             EXTENSIBILITY[ext]))
            for v in node.values:
                w('    .Flag("%s", %d)' % (v.name, v.position))
            w("    .Build();")

        self.codec(w, node, build)

    def typedef(self, w, node):
        self.check_scope(node)
        t = fe.type_of(node.type, node)
        self.codec(w, node, lambda w: w('return %s.Alias("%s", %s);' % (
            TYPES, self.type_name(node), self.type_expr(t, node))))

    def type_flags(self, node):
        flags = []
        if fe.is_nested(node):
            flags.append(RD + ".TypeFlags.Nested")
        if fe.autoid(node) == "hash":
            flags.append(RD + ".TypeFlags.AutoidHash")
        return " | ".join(flags) or RD + ".TypeFlags.None"

    def check_member(self, m):
        for a in NOT_YET:
            if fe.annotation(m, a) is not None:
                raise fe.GeneratorError(
                    "@%s (on %s) is not supported for DDS yet" % (a, m.name), m)
        if fe.annotation(m, "value") is not None:
            raise fe.GeneratorError("@value applies to enumerators, not to %s" % m.name, m)

    def hash_id(self, m):
        a = fe.annotation(m, "hashid")
        if a is None:
            return "null"
        return '"%s"' % fe._string_arg(a)

    def struct(self, w, node):
        if getattr(node, "base", None) or getattr(node, "_base", None):
            raise fe.GeneratorError(
                "struct inheritance (of %s) is not supported for DDS yet" % node.name, node)
        ext = fe.extensibility(node, self.extensibility)
        members = list(node.members)
        ids = fe.member_ids(node, members)
        c = self.cs_class(node)
        bare = self.types.type_name(node).lstrip("@")
        info = []
        for m in members:
            self.check_member(m)
            t = fe.type_of(m.type, m)
            key, opt = fe.is_key(m), fe.is_optional(m)
            if key and opt:
                raise fe.GeneratorError("%s cannot be both @key and @optional" % m.name, m)
            mu = fe.annotation(m, "must_understand") is not None and fe.must_understand(m) and not key
            flags = []
            for flag, on in (("Key", key), ("Optional", opt), ("MustUnderstand", mu),
                             ("External", fe.is_external(m))):
                if on:
                    flags.append(RD + ".MemberFlags." + flag)
            vt = OptionalType(t) if opt else t
            info.append((m, t, " | ".join(flags) or RD + ".MemberFlags.None", vt,
                         self.types.member_name(m.name, bare)))

        def build(w):
            w('return new %s.StructBuilder("%s", %s, %s)' % (
                RD, self.type_name(node), EXTENSIBILITY[ext], self.type_flags(node)))
            for (m, t, flags, _, _), mid in zip(info, ids):
                w('    .Member("%s", %d, %s, %s, %s)' % (
                    m.name, mid, self.type_expr(t, m), flags, self.hash_id(m)))
            w("    .Build();")

        def body(w):
            w("public %s NewValue() => new %s();" % (c, c))
            w()
            w("public void Write(%s.Out __out, %s __v)" % (RD, c))
            w("{")
            w.indent()
            w("%s.Out.NotNull(__v);" % RD)
            for i, (m, _, _, vt, p) in enumerate(info):
                self.write(w, vt, "__v." + p, 0, m)
            w.dedent()
            w("}")
            w()
            w("public %s Read(%s.In __in)" % (c, RD))
            w("{")
            w.indent()
            if not info:
                w("return new %s();" % c)
            else:
                for i, (m, _, _, vt, p) in enumerate(info):
                    v = "__m%d" % i
                    w("%s %s;" % (self.cstype(vt, m), v))
                    self.read(w, vt, v, 0, m)
                w("return new %s(%s);" % (c, ", ".join("__m%d" % i for i in range(len(info)))))
            w.dedent()
            w("}")

        self.codec(w, node, build, c, body)
        self.register(node, c)

    def union(self, w, node):
        ext = fe.extensibility(node, self.extensibility)
        if ext == "mutable":
            raise fe.GeneratorError(
                "mutable unions are not supported for DDS yet (union %s)" % node.name, node)
        disc = fe.type_of(node.discriminator_type, node)
        rdisc = disc.resolved()
        dt = self.cstype(disc, node)
        c = self.cs_class(node)
        members = list(node.members)
        ids = fe.member_ids(node, members)
        info = []
        for m in members:
            self.check_member(m)
            if fe.is_optional(m) or fe.is_external(m) or fe.is_key(m):
                raise fe.GeneratorError(
                    "@optional, @external and @key are not supported on union members (%s)" % m.name,
                    m)
            t = fe.type_of(m.type, m)
            labels = [self.label_value(l, disc) for l in m.labels]
            flags = RD + ".MemberFlags.DefaultLabel" if m.is_default else RD + ".MemberFlags.None"
            info.append((m, t, labels, flags))

        def build(w):
            w('return new %s.UnionBuilder("%s", %s, %s, %s)' % (
                RD, self.type_name(node), EXTENSIBILITY[ext], self.type_flags(node),
                self.type_expr(disc, node)))
            for (m, t, labels, flags), mid in zip(info, ids):
                ls = ("new int[] { %s }" % ", ".join(str(l) for l in labels)) if labels \
                    else "global::System.Array.Empty<int>()"
                w('    .Member("%s", %d, %s, %s, %s, %s)' % (
                    m.name, mid, self.type_expr(t, m), ls, flags, self.hash_id(m)))
            w("    .Build();")

        k = rdisc.kind
        if k == "named" and fe.is_enum(rdisc.node):
            to_long, from_long = "(long)(int)__d", "(%s)(int)__l" % dt
        elif k == "boolean":
            to_long, from_long = "__d ? 1L : 0L", "__l != 0"
        elif k in ("char", "wchar"):
            to_long, from_long = "(long)__d", "(char)__l"
        elif k in ("longlong",):
            to_long, from_long = "__d", "__l"
        elif k == "ulonglong":
            to_long, from_long = "unchecked((long)__d)", "unchecked((ulong)__l)"
        else:
            to_long, from_long = "(long)__d", "unchecked((%s)__l)" % dt

        def body(w):
            w("public %s NewValue() => new %s();" % (c, c))
            w()
            w("public void Write(%s.Out __out, %s __v)" % (RD, c))
            w("{")
            w.indent()
            w("%s.Out.NotNull(__v);" % RD)
            w("var __d = __v.__d;")
            w("__out.WriteDiscriminator(%s);" % to_long)
            for i, (m, t, _, _) in enumerate(info):
                w("%sif (%s.__selects_%s(__d))" % ("" if i == 0 else "else ", c, m.name))
                w("{")
                w.indent()
                self.write(w, t, "__v.__m_" + m.name, 0, m)
                w.dedent()
                w("}")
            w.dedent()
            w("}")
            w()
            w("public %s Read(%s.In __in)" % (c, RD))
            w("{")
            w.indent()
            w("long __l = __in.ReadDiscriminator();")
            w("%s __d = %s;" % (dt, from_long))
            w("var __r = new %s();" % c)
            for i, (m, t, _, _) in enumerate(info):
                w("%sif (%s.__selects_%s(__d))" % ("" if i == 0 else "else ", c, m.name))
                w("{")
                w.indent()
                w("%s __x;" % self.cstype(t, m))
                self.read(w, t, "__x", 0, m)
                w("__r.__m_%s = __x;" % m.name)
                w.dedent()
                w("}")
            w("__r.__d = __d;")
            w("return __r;")
            w.dedent()
            w("}")

        self.codec(w, node, build, c, body)
        self.register(node, c)


def write_outputs(spec, outdir, options):
    """Writes ``<name>_dds.cs`` (and with ``options.dds_only``, ``<name>.cs``
    with the classes of the types) into ``outdir``; returns the paths."""
    base = os.path.splitext(os.path.basename(spec.path))[0]
    os.makedirs(outdir, exist_ok=True)
    paths = []
    if options.dds_only:
        types = CSharpDdsTypes(spec, options)
        text = types.generate()
        path = os.path.join(outdir, base + ".cs")
        with open(path, "w", newline="\n") as f:
            f.write(text)
        paths.append(path)
    else:
        types = CSharpBackend(spec, options)
    text = CSharpDds(spec, types, options.extensibility).generate()
    path = os.path.join(outdir, base + "_dds.cs")
    with open(path, "w", newline="\n") as f:
        f.write(text)
    paths.append(path)
    return paths


__all__ = ["CSharpDds", "CSharpDdsTypes", "write_outputs"]
