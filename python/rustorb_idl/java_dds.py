"""DDS types in the Java backend: ``-bjava -Wbdds`` / ``-Wbdds_only``.

For each struct, union, enum, bitmask and typedef of an IDL file it writes
the class ``<Name>Codec`` next to the class of the type: the DDS type
support for rustorb-dds's Java binding (the DDS Java 5 PSM,
``org.omg.dds``). ``<Name>Codec.type()`` builds the DDS-XTypes type
(``org.rustorb.dds.Types``), and for structs, unions and enums
``<Name>Codec.INSTANCE`` is an ``org.rustorb.dds.Codec`` that writes and
reads the values in the order of the type. ``TypeSupport.newTypeSupport``
finds it from the class of the type::

    Topic<M.Greeting> topic = participant.createTopic("Greetings", M.Greeting.class);

The types are described as the other generators of rustorb-idl describe
them, so that their TypeObjects match those of other implementations for
the same IDL.

``-Wbdds`` writes the codecs as well as the CORBA code, and the classes of
the types are those of the IDL to Java mapping. ``-Wbdds_only`` writes the
classes of the types without CORBA (and no Helper and Holder classes),
mostly as the IDL4 to Java mapping (formal/2023-03-01) has them, and
allows the annotations GIOP has no form for and the types only DDS has:

- an ``enum`` is a Java enum with ``getValue()`` and ``valueOf(int)``
  (and ``@value``);
- an ``@optional`` member is the boxed type (``Integer``...), or the
  class, and ``null`` when it is absent; ``@external`` is a plain member;
- a ``bitmask`` is a ``java.util.BitSet`` and an enum ``<Name>Flags``
  whose ``getPosition()`` is the index of the bit of a flag;
- ``int8`` is a ``byte``;
- the members of a new struct are not null: strings are empty,
  sequences have no elements, arrays have their length, and unions have
  their first member.

Structs, unions and arrays are otherwise as in the IDL to Java mapping
(public fields, Java arrays for sequences, ``discriminator()``...).
Bounded strings and sequences are ``String`` and Java arrays; the bound
is checked when a sample is written.

The annotations read are the ones of the Rust, Python and C++ backends
(see python_dds.py).
"""

from . import frontend as fe
from .cxx_dds import EXTENSIBILITY as _EXT
from .cxx_dds import NOT_YET
from .java_backend import BASIC, JavaBackend, Options, Writer, java_name
from .java_backend import write_outputs as _write_classes

#: Must match org.rustorb.dds.Types.GENERATED_CODE_VERSION.
GENERATED_CODE_VERSION = 1

RD = "org.rustorb.dds"
TYPES = RD + ".Types"

#: IDL type -> DDS-XTypes TypeKind (org.rustorb.dds.Types).
TYPE_KIND = {
    "boolean": "TK_BOOLEAN",
    "octet": "TK_BYTE",
    "int8": "TK_INT8",
    "short": "TK_INT16",
    "ushort": "TK_UINT16",
    "long": "TK_INT32",
    "ulong": "TK_UINT32",
    "longlong": "TK_INT64",
    "ulonglong": "TK_UINT64",
    "float": "TK_FLOAT32",
    "double": "TK_FLOAT64",
    "longdouble": "TK_FLOAT128",
    "char": "TK_CHAR8",
    "wchar": "TK_CHAR16",
}

#: IDL type -> the suffix of the write / read methods of Out and In.
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

JBASIC = dict(BASIC, int8="byte")

BOX = {
    "boolean": "Boolean",
    "byte": "Byte",
    "char": "Character",
    "short": "Short",
    "int": "Integer",
    "long": "Long",
    "float": "Float",
    "double": "Double",
}

ZERO = {
    "boolean": "false",
    "byte": "(byte) 0",
    "char": "'\\0'",
    "short": "(short) 0",
    "int": "0",
    "long": "0L",
    "float": "0.0f",
    "double": "0.0",
}

EXTENSIBILITY = {k: TYPES + "." + v[len("RDDS_"):] for k, v in _EXT.items()}


class OptionalType(object):
    """The type of an ``@optional`` member."""

    kind = "optional"

    def __init__(self, content):
        self.content = content

    def resolved(self):
        return self


def array_dims(t):
    """The dimensions of an anonymous (multi-dimensional) array and the
    type of its elements."""
    dims = [t.length]
    content = t.content
    while content.kind == "array":
        dims.append(content.length)
        content = content.content
    return dims, content


def default_literal(node):
    """The enumerator of a new value of an enum: the @default_literal one,
    else the first."""
    default = [v for v in node.values if fe.annotation(v, "default_literal") is not None]
    return default[-1] if default else node.values[0]


class JavaDdsTypes(JavaBackend):
    """The classes of ``-Wbdds_only``: the structs, unions, enums and
    bitmasks of the file and its constants, with no CORBA in them."""

    dds_only = True

    def jtype(self, t, where=None):
        k = t.kind
        if k == "optional":
            j = self.jtype(t.content, where)
            return BOX.get(j, j)
        if k == "int8":
            return "byte"
        if k == "bitmask":
            return "java.util.BitSet"
        if k in ("any", "TypeCode", "Object", "fixed"):
            raise fe.GeneratorError("%s has no form in DDS" % k, where)
        if k == "named":
            n = self.full(t.node)
            if fe.is_bitmask(n):
                return "java.util.BitSet"
        return JavaBackend.jtype(self, t, where)

    def literal(self, value, t):
        if t.resolved().kind == "int8":
            v = int(value)
            if not -128 <= v <= 127:
                raise fe.GeneratorError("constant %d out of range for int8" % v)
            return "(byte) %d" % v
        return JavaBackend.literal(self, value, t)

    def class_head(self, name):
        return "public final class %s implements java.io.Serializable {" % name

    def bad_operation(self):
        return 'new IllegalStateException("the union member is not selected")'

    def disc_equals(self, rdisc, a, b):
        return "%s == %s" % (a, b)

    # No Helper and Holder classes.

    def helper(self, *args, **kwargs):
        pass

    def holder_class(self, *args, **kwargs):
        pass

    def nested(self, scope):
        # Types defined in a struct or a union are refused (JavaDds).
        pass

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

    def definition(self, node):
        if fe.is_const(node):
            self.module_const(node)
        elif fe.is_enum(node):
            self.enum(node)
        elif fe.is_bitmask(node):
            self.bitmask(node)
        elif fe.is_struct(node) and not fe.is_exception(node):
            if fe.is_forward(node):
                raise fe.GeneratorError(
                    "forward declarations (of %s) are not supported for DDS" % node.name, node)
            self.struct(node)
        elif fe.is_union(node):
            if fe.is_forward(node):
                raise fe.GeneratorError(
                    "forward declarations (of %s) are not supported for DDS" % node.name, node)
            self.union(node)
        # Typedefs have no class in Java. Interfaces, exceptions,
        # valuetypes, natives and bitsets have no DDS form; -Wbdds_only
        # leaves them out.

    def enum(self, node):
        name = java_name(node.name)
        w = Writer()
        w("public enum %s {" % name)
        w.indent()
        for i, v in enumerate(node.values):
            end = ";" if i == len(node.values) - 1 else ","
            w("%s(%d)%s" % (java_name(v.name), v.value, end))
        w()
        w("private final int value;")
        w()
        w("private %s(int value) {" % name)
        w("    this.value = value;")
        w("}")
        w()
        w("/** The value of the enumerator (its @value). */")
        w("public int getValue() {")
        w("    return value;")
        w("}")
        w()
        w("/** The enumerator of a value; IllegalArgumentException if there is none. */")
        w("public static %s valueOf(int value) {" % name)
        w("    switch (value) {")
        for v in node.values:
            w("        case %d:" % v.value)
            w("            return %s;" % java_name(v.name))
        w("        default:")
        w('            throw new IllegalArgumentException("no enumerator of %s has the value " + value);'
          % node.name)
        w("    }")
        w("}")
        w.dedent()
        w("}")
        self.add(node, name, w.text())

    def bitmask(self, node):
        name = java_name(node.name) + "Flags"
        w = Writer()
        w("/** The flags of the bitmask %s, a java.util.BitSet. */" % node.name)
        w("public enum %s {" % name)
        w.indent()
        for i, v in enumerate(node.values):
            end = ";" if i == len(node.values) - 1 else ","
            w("%s(%d)%s" % (java_name(v.name), v.position, end))
        w()
        w("private final int position;")
        w()
        w("private %s(int position) {" % name)
        w("    this.position = position;")
        w("}")
        w()
        w("/** The index of the bit of the flag in the BitSet. */")
        w("public int getPosition() {")
        w("    return position;")
        w("}")
        w.dedent()
        w("}")
        self.add(node, name, w.text())

    def struct(self, node, exception=False):
        name = java_name(node.name)
        members = self.members(node)
        w = Writer()
        w(self.class_head(name))
        w.indent()
        w("private static final long serialVersionUID = 1L;")
        w()
        for m, t in members:
            w("public %s %s;" % (self.jtype(t, node), java_name(m)))
        if members:
            w()
        w("/** A value whose members are not null. */")
        w("public %s() {" % name)
        w.indent()
        for i, (m, t) in enumerate(members):
            init_value(self, w, t, "this." + java_name(m), "%d" % i, zero=False, standalone=True,
                       where=node)
        w.dedent()
        w("}")
        if members:
            params = ", ".join("%s %s" % (self.jtype(t, node), java_name(m)) for m, t in members)
            w()
            w("public %s(%s) {" % (name, params))
            for m, _ in members:
                w("    this.%s = %s;" % (java_name(m), java_name(m)))
            w("}")
        w.dedent()
        w("}")
        self.add(node, name, w.text())


def init_value(types, w, t, target, tag, zero, standalone, where=None):
    """Statements that set ``target`` to a new value of type ``t`` whose
    members are not null. ``zero``: also set the basic types (else a field
    is left at its Java default). ``standalone``: in the classes of the
    types (-Wbdds_only), which cannot use the codecs. ``tag`` makes local
    names unique."""
    k = t.kind
    if k == "optional":
        if zero:
            w("%s = null;" % target)
        return
    if k in TYPE_KIND:
        if zero:
            w("%s = %s;" % (target, ZERO[JBASIC[k]]))
        return
    if k in ("string", "wstring"):
        w('%s = "";' % target)
        return
    if k == "sequence":
        w("%s = %s;" % (target, types.new_array(t.content, 0)))
        return
    if k == "array":
        dims, content = array_dims(t)
        if content.kind in TYPE_KIND:
            w("%s = new %s%s;" % (target, JBASIC[content.kind], "".join("[%d]" % d for d in dims)))
            return
        i = "$i" + tag
        w("%s = %s;" % (target, types.new_array(t.content, t.length)))
        w("for (int %s = 0; %s < %d; %s++) {" % (i, i, t.length, i))
        w.indent()
        init_value(types, w, t.content, "%s[%s]" % (target, i), tag + "_", True, standalone, where)
        w.dedent()
        w("}")
        return
    if k == "bitmask":
        w("%s = new java.util.BitSet();" % target)
        return
    if k == "named":
        n = types.full(t.node)
        if fe.is_typedef(n):
            init_value(types, w, fe.type_of(n.type, n), target, tag, zero, standalone, where)
            return
        if fe.is_bitmask(n):
            w("%s = new java.util.BitSet();" % target)
            return
        if not standalone:
            w("%s = %s.INSTANCE.newValue();" % (target, types.scoped(n, "Codec")))
            return
        if fe.is_enum(n):
            w("%s = %s.%s;" % (target, types.scoped(n), java_name(default_literal(n).name)))
        elif fe.is_struct(n):
            w("%s = new %s();" % (target, types.scoped(n)))
        elif fe.is_union(n):
            init_union(types, w, n, target, tag, standalone, where)
        else:
            raise fe.GeneratorError("the %s %s has no form in DDS" % (fe.kind_name(n), n.name), where)
        return
    raise fe.GeneratorError("%s has no form in DDS" % k, where)


def init_union(types, w, node, target, tag, standalone, where=None):
    """``target`` = a union with its first member, of a new value."""
    m = node.members[0]
    t = fe.type_of(m.type, m)
    x = "$u" + tag
    w("%s = new %s();" % (target, types.scoped(node)))
    w("{")
    w.indent()
    w("%s %s;" % (types.jtype(t, where), x))
    init_value(types, w, t, x, tag + "_", True, standalone, where)
    w("%s.%s(%s);" % (target, java_name(m.name), x))
    w.dedent()
    w("}")


class JavaDds(object):
    """Adds ``<Name>Codec`` to the classes of ``types``, the backend that
    names the Java types (:class:`JavaBackend`, or :class:`JavaDdsTypes`
    for ``-Wbdds_only``)."""

    def __init__(self, spec, types, extensibility="appendable"):
        self.spec = spec
        self.types = types
        self.extensibility = extensibility
        self.idl_name = types.idl_name
        self.dds_only = isinstance(types, JavaDdsTypes)

    # -- names -----------------------------------------------------------

    def check_scope(self, node):
        if fe.inner_scope(node):
            raise fe.GeneratorError(
                "%s is defined inside %s, which DDS types cannot be"
                % (node.name, "::".join(fe.inner_scope(node))),
                node,
            )

    def jclass(self, node):
        self.check_scope(node)
        return self.types.scoped(node)

    def codec_class(self, node):
        self.check_scope(node)
        return self.types.scoped(node, "Codec")

    def type_name(self, node):
        return "::".join(fe.scope_path(node))

    def jtype(self, t, where):
        return self.types.jtype(t, where)

    # -- types -----------------------------------------------------------

    def check_named(self, n, where):
        if not (fe.is_typedef(n) or fe.is_struct(n) or fe.is_union(n) or fe.is_enum(n)
                or fe.is_bitmask(n)) or fe.is_exception(n):
            raise fe.GeneratorError("the %s %s has no form in DDS" % (fe.kind_name(n), n.name), where)
        if fe.is_forward(n):
            raise fe.GeneratorError(
                "%s is only declared: recursive types are not supported for DDS" % n.name, where)

    def type_expr(self, t, where):
        """A Java expression for the TypeRef of a type."""
        k = t.kind
        if k in TYPE_KIND:
            return "%s.primitive(%s.%s)" % (TYPES, TYPES, TYPE_KIND[k])
        if k in ("string", "wstring"):
            return "%s.%s(%d)" % (TYPES, k, t.bound or 0)
        if k == "sequence":
            return "%s.sequence(%s, %d)" % (TYPES, self.type_expr(t.content, where), t.bound or 0)
        if k == "array":
            dims, content = array_dims(t)
            return "%s.array(%s, %s)" % (TYPES, self.type_expr(content, where),
                                         ", ".join(str(d) for d in dims))
        if k == "bitmask":
            return self.codec_class(t.node) + ".type()"
        if k == "named":
            n = self.types.full(t.node)
            self.check_named(n, where)
            return self.codec_class(n) + ".type()"
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

    # -- values ------------------------------------------------------------

    def write(self, w, t, expr, tag, where):
        """Statements that write ``expr`` of type ``t`` to ``$out``."""
        t = self.resolve(t, where)
        k = t.kind
        if k == "optional":
            w("if (%s == null) {" % expr)
            w("    $out.writePresent(false);")
            w("} else {")
            w.indent()
            w("$out.writePresent(true);")
            self.write(w, t.content, expr, tag, where)
            w.dedent()
            w("}")
        elif k in STREAM:
            w("$out.write%s(%s);" % (STREAM[k], expr))
        elif k == "string":
            w("$out.writeString(%s);" % expr)
        elif k == "wstring":
            w("$out.writeWstring(%s);" % expr)
        elif k == "sequence":
            w("$out.writeLength(%s.length);" % expr)
            c = t.content
            if c.kind in BULK:
                w("$out.write%sArray(%s);" % (STREAM[c.kind], expr))
            else:
                e = "$e" + tag
                w("for (%s %s : %s) {" % (self.jtype(c, where), e, expr))
                w.indent()
                self.write(w, c, e, tag + "_", where)
                w.dedent()
                w("}")
        elif k == "array":
            dims, content = array_dims(t)
            if content.kind in BULK:
                if len(dims) == 1:
                    w("%s.Out.checkLength(%s, %d);" % (RD, expr, dims[0]))
                    w("$out.write%sArray(%s);" % (STREAM[content.kind], expr))
                else:
                    w("$out.write%sArray((%s[]) %s.Out.flatten(%s, %s));" % (
                        STREAM[content.kind], JBASIC[content.kind], RD, expr,
                        ", ".join(str(d) for d in dims)))
            else:
                e = "$e" + tag
                w("%s.Out.checkLength(%s, %d);" % (RD, expr, t.length))
                w("for (%s %s : %s) {" % (self.jtype(t.content, where), e, expr))
                w.indent()
                self.write(w, t.content, e, tag + "_", where)
                w.dedent()
                w("}")
        elif self.is_bitmask(t):
            w("$out.writeBitmask(%s.bits(%s));" % (self.codec_class(t.node), expr))
        elif k == "named":
            w("%s.INSTANCE.write($out, %s);" % (self.codec_class(t.node), expr))
        else:
            raise fe.GeneratorError("%s has no form in DDS" % k, where)

    def read(self, w, t, target, tag, where):
        """Statements that read a value of type ``t`` from ``$in`` into
        ``target``."""
        t = self.resolve(t, where)
        k = t.kind
        if k == "optional":
            w("if ($in.readPresent()) {")
            w.indent()
            self.read(w, t.content, target, tag, where)
            w.dedent()
            w("} else {")
            w("    %s = null;" % target)
            w("}")
        elif k in STREAM:
            w("%s = $in.read%s();" % (target, STREAM[k]))
        elif k == "string":
            w("%s = $in.readString();" % target)
        elif k == "wstring":
            w("%s = $in.readWstring();" % target)
        elif k == "sequence":
            c = t.content
            if c.kind in BULK:
                w("%s = $in.read%sArray($in.readLength());" % (target, STREAM[c.kind]))
            else:
                n, s, i = "$n" + tag, "$s" + tag, "$i" + tag
                w("{")
                w.indent()
                w("int %s = $in.readLength();" % n)
                w("%s[] %s = %s;" % (self.jtype(c, where), s, self.types.new_array(c, n)))
                w("for (int %s = 0; %s < %s; %s++) {" % (i, i, n, i))
                w.indent()
                self.read(w, c, "%s[%s]" % (s, i), tag + "_", where)
                w.dedent()
                w("}")
                w("%s = %s;" % (target, s))
                w.dedent()
                w("}")
        elif k == "array":
            dims, content = array_dims(t)
            if content.kind in BULK:
                if len(dims) == 1:
                    w("%s = $in.read%sArray(%d);" % (target, STREAM[content.kind], dims[0]))
                else:
                    total = 1
                    for d in dims:
                        total *= d
                    w("%s = (%s) %s.In.unflatten($in.read%sArray(%d), %s);" % (
                        target, self.jtype(t, where), RD, STREAM[content.kind], total,
                        ", ".join(str(d) for d in dims)))
            else:
                s, i = "$s" + tag, "$i" + tag
                w("{")
                w.indent()
                w("%s %s = %s;" % (self.jtype(t, where), s, self.types.new_array(t.content, t.length)))
                w("for (int %s = 0; %s < %d; %s++) {" % (i, i, t.length, i))
                w.indent()
                self.read(w, t.content, "%s[%s]" % (s, i), tag + "_", where)
                w.dedent()
                w("}")
                w("%s = %s;" % (target, s))
                w.dedent()
                w("}")
        elif self.is_bitmask(t):
            w("%s = %s.of($in.readBitmask());" % (target, self.codec_class(t.node)))
        elif k == "named":
            w("%s = %s.INSTANCE.read($in);" % (target, self.codec_class(t.node)))
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
        """Adds the codecs to the classes of ``self.types``."""
        for it in fe.definitions(self.spec):
            n = it.node
            if fe.is_module(n) or fe.is_const(n):
                continue
            if fe.is_enum(n):
                self.enum(n)
            elif fe.is_bitmask(n):
                self.bitmask(n)
            elif fe.is_typedef(n):
                self.typedef(n)
            elif fe.is_struct(n) and not fe.is_exception(n):
                if fe.is_forward(n):
                    if self.dds_only:
                        raise fe.GeneratorError(
                            "forward declarations (of %s) are not supported for DDS" % n.name, n)
                    continue
                self.struct(n)
            elif fe.is_union(n):
                if fe.is_forward(n):
                    if self.dds_only:
                        raise fe.GeneratorError(
                            "forward declarations (of %s) are not supported for DDS" % n.name, n)
                    continue
                self.union(n)
            # Interfaces, exceptions, valuetypes, natives and bitsets have
            # no DDS form; they are left to the CORBA code.
        return self.types.files

    def codec(self, node, build, jtype=None, body=None):
        """The class ``<Name>Codec``: ``build(w)`` writes the statements
        that return the TypeRef; with ``jtype``, the class is the Codec of
        that Java type and ``body(w)`` writes its methods."""
        name = java_name(node.name) + "Codec"
        w = Writer()
        what = "%s %s" % (fe.kind_name(node), self.type_name(node))
        w("/** The DDS type support of the %s (rustorb-dds). */" % what)
        if jtype:
            w("public final class %s implements %s.Codec<%s> {" % (name, RD, jtype))
        else:
            w("public final class %s {" % name)
        w.indent()
        w("static {")
        w('    %s.checkGeneratedCode(%d, "%s");' % (TYPES, GENERATED_CODE_VERSION, self.idl_name))
        w("}")
        w()
        if jtype:
            w("public static final %s INSTANCE = new %s();" % (name, name))
            w()
        w("private static volatile %s.TypeRef type;" % RD)
        w()
        w("private %s() {}" % name)
        w()
        w("/** The DDS-XTypes type of the %s (built once). */" % what)
        w("public static %s.TypeRef type() {" % RD)
        w("    %s.TypeRef t = type;" % RD)
        w("    if (t == null) {")
        w("        synchronized (%s.class) {" % name)
        w("            t = type;")
        w("            if (t == null) {")
        w("                t = build();")
        w("                type = t;")
        w("            }")
        w("        }")
        w("    }")
        w("    return t;")
        w("}")
        w()
        w("private static %s.TypeRef build() {" % RD)
        w.indent()
        build(w)
        w.dedent()
        w("}")
        if jtype:
            w()
            w("@Override")
            w("public %s.TypeRef getType() {" % RD)
            w("    return type();")
            w("}")
            w()
            w("@Override")
            w("public String getTypeName() {")
            w('    return "%s";' % self.type_name(node))
            w("}")
            w()
            w("@Override")
            w("public Class<%s> getJavaClass() {" % jtype)
            w("    return %s.class;" % jtype)
            w("}")
        if body:
            w()
            body(w)
        w.dedent()
        w("}")
        self.check_scope(node)
        self.types.add(node, name, w.text())

    def enum(self, node):
        bits = fe.bit_bound(node, 32, 1, 32)
        ext = fe.extensibility(node, "final")
        default = default_literal(node)
        c = self.jclass(node)

        def build(w):
            w('return new %s.EnumBuilder("%s", %d, %s)' % (TYPES, self.type_name(node), bits,
                                                          EXTENSIBILITY[ext]))
            for v in node.values:
                if fe.annotation(v, "default_literal") is not None and v is default:
                    w('        .literal("%s", %d, true)' % (v.name, v.value))
                else:
                    w('        .literal("%s", %d)' % (v.name, v.value))
            w("        .build();")

        if self.dds_only:
            new, value, of = "%s.%s" % (c, java_name(default.name)), "v.getValue()", "%s.valueOf" % c
        else:
            new, value, of = "%s.from_int(0)" % c, "v.value()", "%s.from_int" % c

        def body(w):
            w("@Override")
            w("public %s newValue() {" % c)
            w("    return %s;" % new)
            w("}")
            w()
            w("@Override")
            w("public void write(%s.Out $out, %s v) {" % (RD, c))
            w("    $out.writeEnum(%s);" % value)
            w("}")
            w()
            w("@Override")
            w("public %s read(%s.In $in) {" % (c, RD))
            w("    return %s($in.readEnum());" % of)
            w("}")

        self.codec(node, build, c, body)

    def bitmask(self, node):
        bits = node.bit_bound
        for v in node.values:
            if v.position >= bits:
                raise fe.GeneratorError(
                    "the position %d of %s is not below @bit_bound(%d)" % (v.position, v.name, bits),
                    node)
        ext = fe.extensibility(node, "final")

        def build(w):
            w('return new %s.BitmaskBuilder("%s", %d, %s)' % (TYPES, self.type_name(node), bits,
                                                             EXTENSIBILITY[ext]))
            for v in node.values:
                w('        .flag("%s", %d)' % (v.name, v.position))
            w("        .build();")

        def body(w):
            w("/** The bits of a value; IndexOutOfBoundsException for a bit not")
            w(" * below the bit bound (%d). */" % bits)
            w("public static long bits(java.util.BitSet v) {")
            w("    if (v.length() > %d) {" % bits)
            w('        throw new IndexOutOfBoundsException("bit " + (v.length() - 1)'
              ' + " of a %s with @bit_bound(%d)");' % (node.name, bits))
            w("    }")
            w("    long[] words = v.toLongArray();")
            w("    return words.length == 0 ? 0 : words[0];")
            w("}")
            w()
            w("/** The value of some bits. */")
            w("public static java.util.BitSet of(long bits) {")
            w("    return java.util.BitSet.valueOf(new long[] {bits});")
            w("}")

        self.codec(node, build, None, body)

    def typedef(self, node):
        self.check_scope(node)
        t = fe.type_of(node.type, node)
        self.codec(node, lambda w: w('return %s.alias("%s", %s);' % (
            TYPES, self.type_name(node), self.type_expr(t, node))))

    def type_flags(self, node):
        flags = []
        if fe.is_nested(node):
            flags.append(TYPES + ".TYPE_NESTED")
        if fe.autoid(node) == "hash":
            flags.append(TYPES + ".TYPE_AUTOID_HASH")
        return " | ".join(flags) or "0"

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

    def struct(self, node):
        if getattr(node, "base", None) or getattr(node, "_base", None):
            raise fe.GeneratorError(
                "struct inheritance (of %s) is not supported for DDS yet" % node.name, node)
        ext = fe.extensibility(node, self.extensibility)
        members = list(node.members)
        ids = fe.member_ids(node, members)
        c = self.jclass(node)
        info = []
        for m in members:
            self.check_member(m)
            t = fe.type_of(m.type, m)
            key, opt = fe.is_key(m), fe.is_optional(m)
            if key and opt:
                raise fe.GeneratorError("%s cannot be both @key and @optional" % m.name, m)
            mu = fe.annotation(m, "must_understand") is not None and fe.must_understand(m) and not key
            flags = []
            for flag, on in (("KEY", key), ("OPTIONAL", opt), ("MUST_UNDERSTAND", mu),
                             ("EXTERNAL", fe.is_external(m))):
                if on:
                    flags.append(TYPES + ".MEMBER_" + flag)
            info.append((m, t, " | ".join(flags) or "0", OptionalType(t) if opt else t))

        def build(w):
            w('return new %s.StructBuilder("%s", %s, %s, null)' % (
                TYPES, self.type_name(node), EXTENSIBILITY[ext], self.type_flags(node)))
            for (m, t, flags, _), mid in zip(info, ids):
                w('        .member("%s", %d, %s, %s, %s)' % (
                    m.name, mid, self.type_expr(t, m), flags, self.hash_id(m)))
            w("        .build();")

        def body(w):
            w("@Override")
            w("public %s newValue() {" % c)
            w.indent()
            if self.dds_only:
                w("return new %s();" % c)
            else:
                w("%s v = new %s();" % (c, c))
                for i, (m, _, _, vt) in enumerate(info):
                    init_value(self.types, w, vt, "v." + java_name(m.name), "%d" % i, False, False, m)
                w("return v;")
            w.dedent()
            w("}")
            w()
            w("@Override")
            w("public void write(%s.Out $out, %s v) {" % (RD, c))
            w.indent()
            for i, (m, _, _, vt) in enumerate(info):
                self.write(w, vt, "v." + java_name(m.name), "%d" % i, m)
            w.dedent()
            w("}")
            w()
            w("@Override")
            w("public %s read(%s.In $in) {" % (c, RD))
            w.indent()
            w("%s v = new %s();" % (c, c))
            for i, (m, _, _, vt) in enumerate(info):
                self.read(w, vt, "v." + java_name(m.name), "%d" % i, m)
            w("return v;")
            w.dedent()
            w("}")

        self.codec(node, build, c, body)

    def union(self, node):
        ext = fe.extensibility(node, self.extensibility)
        if ext == "mutable":
            raise fe.GeneratorError(
                "mutable unions are not supported for DDS yet (union %s)" % node.name, node)
        disc = fe.type_of(node.discriminator_type, node)
        rdisc = disc.resolved()
        dt = self.jtype(disc, node)
        c = self.jclass(node)
        members = list(node.members)
        ids = fe.member_ids(node, members)
        labels_all = [l for m in members for l in m.labels]
        info = []
        for m in members:
            self.check_member(m)
            if fe.is_optional(m) or fe.is_external(m) or fe.is_key(m):
                raise fe.GeneratorError(
                    "@optional, @external and @key are not supported on union members (%s)" % m.name,
                    m)
            t = fe.type_of(m.type, m)
            labels = [self.label_value(l, disc) for l in m.labels]
            flags = TYPES + ".MEMBER_DEFAULT_LABEL" if m.is_default else "0"
            info.append((m, t, labels, flags))

        def build(w):
            w('return new %s.UnionBuilder("%s", %s, %s, %s, 0)' % (
                TYPES, self.type_name(node), EXTENSIBILITY[ext], self.type_flags(node),
                self.type_expr(disc, node)))
            for (m, t, labels, flags), mid in zip(info, ids):
                w('        .member("%s", %d, %s, new int[] {%s}, %s, %s)' % (
                    m.name, mid, self.type_expr(t, m), ", ".join(str(l) for l in labels), flags,
                    self.hash_id(m)))
            w("        .build();")

        k = rdisc.kind
        if k == "named" and fe.is_enum(rdisc.node):
            if self.dds_only:
                to_long, from_long = "(long) $d.getValue()", "%s.valueOf((int) $l)" % dt
            else:
                to_long, from_long = "(long) $d.value()", "%s.from_int((int) $l)" % dt
        elif k == "boolean":
            to_long, from_long = "$d ? 1L : 0L", "$l != 0"
        elif k == "octet":
            to_long, from_long = "(long) ($d & 0xff)", "(byte) $l"
        elif k == "ushort":
            to_long, from_long = "(long) ($d & 0xffff)", "(short) $l"
        elif k == "ulong":
            to_long, from_long = "$d & 0xffffffffL", "(int) $l"
        elif k in ("char", "wchar"):
            to_long, from_long = "(long) $d", "(char) $l"
        elif k in ("longlong", "ulonglong"):
            to_long, from_long = "$d", "$l"
        else:
            to_long, from_long = "(long) $d", "(%s) $l" % dt
        default = [i for i, (m, _, _, _) in enumerate(info) if m.is_default]
        # The setter with an explicit discriminator exists for members
        # with several labels and the default member (java_backend.py).
        explicit = [len(m.labels) > 1 or m.is_default for m, _, _, _ in info]
        # Without a default member: __default(d) unless every value of the
        # discriminator has a member.
        from .cxx_backend import CxxBackend, _NONE

        implicit = CxxBackend.default_discriminator(self.types, rdisc, labels_all)

        def branches(w, each, otherwise):
            first = True
            for i, (m, t, labels, _) in enumerate(info):
                if not labels:
                    continue
                cond = " || ".join("$l == %dL" % l for l in labels)
                w("%s (%s) {" % ("if" if first else "} else if", cond))
                w.indent()
                each(w, i, m, t)
                w.dedent()
                first = False
            if default:
                i = default[0]
                m, t = info[i][0], info[i][1]
                w("{" if first else "} else {")
                w.indent()
                each(w, i, m, t)
                w.dedent()
                w("}")
            elif otherwise:
                w("{" if first else "} else {")
                w.indent()
                otherwise(w)
                w.dedent()
                w("}")
            elif not first:
                w("}")

        def body(w):
            w("@Override")
            w("public %s newValue() {" % c)
            w.indent()
            w("%s v;" % c)
            init_union(self.types, w, node, "v", "", self.dds_only, node)
            w("return v;")
            w.dedent()
            w("}")
            w()
            w("@Override")
            w("public void write(%s.Out $out, %s v) {" % (RD, c))
            w.indent()
            w("%s $d = v.discriminator();" % dt)
            w("long $l = %s;" % to_long)
            w("$out.writeDiscriminator($l);")
            branches(w, lambda w, i, m, t: self.write(w, t, "v.%s()" % java_name(m.name), "%d" % i, m),
                     None)
            w.dedent()
            w("}")
            w()
            w("@Override")
            w("public %s read(%s.In $in) {" % (c, RD))
            w.indent()
            w("long $l = $in.readDiscriminator();")
            w("%s $d = %s;" % (dt, from_long))
            w("%s v = new %s();" % (c, c))

            def each(w, i, m, t):
                x = "$m%d" % i
                w("%s %s;" % (self.jtype(t, m), x))
                self.read(w, t, x, "%d" % i, m)
                if explicit[i]:
                    w("v.%s($d, %s);" % (java_name(m.name), x))
                else:
                    w("v.%s(%s);" % (java_name(m.name), x))

            if implicit is _NONE:
                otherwise = None
            else:
                def otherwise(w):
                    w("v.__default($d);")
            branches(w, each, otherwise)
            w("return v;")
            w.dedent()
            w("}")

        self.codec(node, build, c, body)


def generate(spec, options):
    """The classes of ``spec``: ``{(package, class): text}``. With
    ``options.dds_only``, the types and their codecs; else the codecs
    only (the CORBA code is written by java_backend)."""
    if options.dds_only:
        types = JavaDdsTypes(spec, options)
        types.generate()
    else:
        types = JavaBackend(spec, options)
    JavaDds(spec, types, options.extensibility).generate()
    return types.files


class _Files(object):
    def __init__(self, files):
        self.files = files

    def generate(self):
        return self.files


def write_outputs(spec, outdir, options):
    """Writes the classes of :func:`generate` under ``outdir``; returns the
    paths written."""
    return _write_classes(_Files(generate(spec, options)), outdir)


__all__ = ["JavaDds", "JavaDdsTypes", "Options", "generate", "write_outputs"]
