"""DDS types in the C++ backend: ``-bc++11 -Wbdds`` / ``-Wbdds_only``.

For ``Foo.idl`` it writes ``Foo_dds.hh``, the DDS type support of the
structs, unions, enums, bitmasks and typedefs of the file for rustorb-dds's
C++ binding (the ISO/IEC C++ PSM for DDS, ``<dds/dds.hpp>``): for each of
them, a specialization of ``rustorb::dds::codec<T>`` that builds its
DDS-XTypes type and writes and reads its values (rustorb-dds's
``rustorb/dds/types.hpp``), and for topic types (structs that are not
``@nested``) ``dds::topic::is_topic_type<T>`` and
``dds::topic::topic_type_name<T>``. The types are described as the other
generators of rustorb-idl describe them, so that their TypeObjects match
those of other implementations for the same IDL::

    #include "Foo_dds.hh"
    #include <dds/dds.hpp>

    dds::topic::Topic<M::Greeting> topic(participant, "Greetings");

The C++ classes of the types are those of ``Foo.hh``. ``-Wbdds`` writes
``Foo_dds.hh`` as well as the CORBA code (``Foo.hh`` and ``Foo.cc``, on
rustorb's C++ runtime); ``-Wbdds_only`` writes ``Foo.hh`` with the types and
constants only, which needs nothing but the standard library, and then
allows the annotations GIOP has no form for and the types only DDS has:
``@optional`` (``std::optional``), ``@external`` (a plain member),
``@value``, ``int8`` and ``bitmask``. Bounded strings and sequences are
then ``std::string`` and ``std::vector``; the bound is checked when a
sample is written.

The annotations read are the ones of the Rust and Python backends (see
python_dds.py).
"""

import os
import re

from . import frontend as fe
from .cxx_backend import (
    BASIC,
    HEADER,
    CxxBackend,
    Options,
    Writer,
    cxx_name,
    file_base,
)

#: Must match rustorb::dds::generated_code_version in rustorb/dds/types.hpp.
GENERATED_CODE_VERSION = 1

#: IDL type -> DDS-XTypes TypeKind (rustorb/dds.h).
TYPE_KIND = {
    "boolean": "RDDS_TK_BOOLEAN",
    "octet": "RDDS_TK_BYTE",
    "int8": "RDDS_TK_INT8",
    "short": "RDDS_TK_INT16",
    "ushort": "RDDS_TK_UINT16",
    "long": "RDDS_TK_INT32",
    "ulong": "RDDS_TK_UINT32",
    "longlong": "RDDS_TK_INT64",
    "ulonglong": "RDDS_TK_UINT64",
    "float": "RDDS_TK_FLOAT32",
    "double": "RDDS_TK_FLOAT64",
    "longdouble": "RDDS_TK_FLOAT128",
    "char": "RDDS_TK_CHAR8",
    "wchar": "RDDS_TK_CHAR16",
}

EXTENSIBILITY = {"final": "RDDS_FINAL", "appendable": "RDDS_APPENDABLE", "mutable": "RDDS_MUTABLE"}

# Member annotations that change what is written or read, which rustorb-dds
# does not implement: refused rather than ignored.
NOT_YET = ("non_serialized", "default", "try_construct")

RD = "::rustorb::dds"
SHAPE = RD + "::shape"
#: The namespace of the functions that build the types.
IDL_NS = ("rustorb", "dds", "idl")


def dds_header_of_file(path):
    """``Foo.idl`` -> ``Foo_dds.hh``."""
    return file_base(path) + "_dds.hh"


class OptionalType(object):
    """The type of an ``@optional`` member: ``std::optional`` of its
    type."""

    kind = "optional"

    def __init__(self, content):
        self.content = content

    def resolved(self):
        return self


class CxxDdsTypes(CxxBackend):
    """``Foo.hh`` of ``-Wbdds_only``: the C++ classes of the structs,
    unions, enums and bitmasks, the typedefs and the constants of the
    file, with no CORBA in them."""

    def ctype(self, t, where=None):
        k = t.kind
        if k == "optional":
            return "std::optional<%s>" % self.ctype(t.content, where)
        if k == "string" and t.bound:
            return "std::string"
        if k == "wstring" and t.bound:
            return "std::wstring"
        if k == "sequence" and t.bound:
            return "std::vector<%s>" % self.ctype(t.content, where)
        if k in ("any", "TypeCode", "Object", "fixed"):
            raise fe.GeneratorError("%s has no form in DDS" % k, where)
        return CxxBackend.ctype(self, t, where)

    def bad_param(self):
        return 'throw ::std::invalid_argument("the union member is not selected");'

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

    def member_default(self, m, t):
        if t.kind == "optional":
            return "{}"
        return CxxBackend.member_default(self, m, t)

    def enum(self, w, node):
        names = ", ".join("%s = %d" % (cxx_name(v.name), v.value) for v in node.values)
        w("enum class %s : int32_t { %s };" % (cxx_name(node.name), names))
        w()

    def bitmask(self, w, node):
        CxxBackend.bitmask(self, w, node)
        self.codecs.pop()

    def struct(self, w, node, exception=False):
        CxxBackend.struct(self, w, node, exception)
        self.codecs.pop()

    def union(self, w, node):
        CxxBackend.union(self, w, node)
        self.codecs.pop()

    def definition(self, w, node, in_class):
        if fe.is_const(node):
            self.const(w, node, in_class)
        elif fe.is_enum(node):
            self.enum(w, node)
        elif fe.is_typedef(node):
            t = fe.type_of(node.type, node)
            w("using %s = %s;" % (cxx_name(node.name), self.ctype(t, node)))
            w()
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
        elif fe.is_bitmask(node):
            self.bitmask(w, node)
        # Interfaces, exceptions, valuetypes, natives and bitsets have no
        # DDS form; -Wbdds_only leaves them out.

    def nested(self, w, scope):
        for d in fe.members_of(scope):
            if fe.is_struct(d) or fe.is_union(d) or fe.is_enum(d) or fe.is_typedef(d) or fe.is_const(d):
                self.definition(w, d, in_class=True)

    def generate_header(self):
        w = Writer()
        guard = "RUSTORB_IDL_%s_HH" % re.sub(r"[^0-9A-Za-z]", "_", self.base).upper()
        w(HEADER % self.idl_name)
        w("#ifndef %s" % guard)
        w("#define %s" % guard)
        w()
        for h in ("array", "cstdint", "limits", "optional", "stdexcept", "string", "utility",
                  "vector"):
            w("#include <%s>" % h)
        w()
        included = self.spec.included_files()
        for f in included:
            w('#include "%s%s"' % (file_base(f), self.opt.header_suffix))
        if included:
            w()
        for it in fe.definitions(self.spec):
            n = it.node
            if fe.is_module(n) or fe.is_operation(n) or fe.is_attribute(n):
                continue
            self.open_ns(w, fe.enclosing_modules(n))
            self.definition(w, n, in_class=False)
        self.open_ns(w, ())
        w("#endif")
        return w.text()


class CxxDds(object):
    """Writes ``Foo_dds.hh`` for a parsed IDL file; ``types`` is the
    backend that names the C++ types (:class:`CxxBackend`, or
    :class:`CxxDdsTypes` for ``-Wbdds_only``)."""

    def __init__(self, spec, types, extensibility="appendable"):
        self.spec = spec
        self.types = types
        self.extensibility = extensibility
        self.idl_name = os.path.basename(spec.path)
        self.base = file_base(spec.path)
        self.dds_only = isinstance(types, CxxDdsTypes)
        self.w = Writer()

    # -- names -----------------------------------------------------------

    def check_scope(self, node):
        if fe.inner_scope(node):
            raise fe.GeneratorError(
                "%s is defined inside %s, which DDS types cannot be"
                % (node.name, "::".join(fe.inner_scope(node))),
                node,
            )

    def cxx(self, node):
        """The C++ class of a definition: ``::M::S``."""
        self.check_scope(node)
        return self.types.scoped(node)

    def builder(self, node):
        """The function that builds the type of a definition:
        ``::rustorb::dds::idl::M::S``."""
        self.check_scope(node)
        return "::" + "::".join(IDL_NS + tuple(cxx_name(n) for n in fe.scope_path(node)))

    def type_name(self, node):
        return "::".join(fe.scope_path(node))

    # -- types -----------------------------------------------------------

    def check_named(self, n, where):
        if not (fe.is_typedef(n) or fe.is_struct(n) or fe.is_union(n) or fe.is_enum(n)
                or fe.is_bitmask(n)) or fe.is_exception(n):
            raise fe.GeneratorError("the %s %s has no form in DDS" % (fe.kind_name(n), n.name), where)
        if fe.is_forward(n):
            raise fe.GeneratorError(
                "%s is only declared: recursive types are not supported for DDS" % n.name, where)

    def type_expr(self, t, where):
        """A C++ expression for the ``const rdds_type*`` of a type, valid
        until the end of the full expression."""
        k = t.kind
        if k in TYPE_KIND:
            return "%s::primitive_type(%s).get()" % (RD, TYPE_KIND[k])
        if k in ("string", "wstring"):
            return "%s::string_type(%s, %d).get()" % (RD, "true" if k == "wstring" else "false",
                                                      t.bound or 0)
        if k == "sequence":
            return "%s::sequence_type(%s, %d).get()" % (RD, self.type_expr(t.content, where),
                                                        t.bound or 0)
        if k == "array":
            dims, content = self.array_dims(t)
            return "%s::array_type(%s, {%s}).get()" % (
                RD, self.type_expr(content, where), ", ".join("%du" % d for d in dims))
        if k == "bitmask":
            return self.builder(t.node) + "()"
        if k == "named":
            self.check_named(t.node, where)
            return self.builder(t.node) + "()"
        raise fe.GeneratorError("%s has no form in DDS" % k, where)

    def array_dims(self, t):
        dims = [t.length]
        content = t.content
        while content.kind == "array":
            dims.append(content.length)
            content = content.content
        return dims, content

    def shape(self, t, where):
        """The ``rustorb::dds::shape`` of the values of a type (typedefs
        followed)."""
        k = t.kind
        if k == "optional":
            return "%s::optional<%s>" % (SHAPE, self.shape(t.content, where))
        if k in TYPE_KIND:
            return "%s::prim<%s>" % (SHAPE, BASIC[k])
        if k in ("string", "wstring"):
            return "%s::%s" % (SHAPE, k)
        if k == "sequence":
            return "%s::sequence<%s>" % (SHAPE, self.shape(t.content, where))
        if k == "array":
            dims, content = self.array_dims(t)
            return "%s::array<%s, %d>" % (SHAPE, self.shape(content, where), len(dims))
        if k == "bitmask":
            return "%s::type<%s>" % (SHAPE, self.cxx(t.node))
        if k == "named":
            n = t.node
            self.check_named(n, where)
            if fe.is_typedef(n):
                return self.shape(fe.type_of(n.type, n), where)
            return "%s::type<%s>" % (SHAPE, self.cxx(n))
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

    # -- the file ----------------------------------------------------------

    def generate(self):
        body = Writer()
        self.w = body
        topics = []
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
                if not fe.is_nested(n):
                    topics.append(n)
            elif fe.is_union(n):
                if fe.is_forward(n):
                    if self.dds_only:
                        raise fe.GeneratorError(
                            "forward declarations (of %s) are not supported for DDS" % n.name, n)
                    continue
                self.union(n)
            # Interfaces, exceptions, valuetypes, natives and bitsets have
            # no DDS form; they are left to the CORBA code.

        w = Writer()
        guard = "RUSTORB_IDL_%s_DDS_HH" % re.sub(r"[^0-9A-Za-z]", "_", self.base).upper()
        w(HEADER % self.idl_name)
        w("#ifndef %s" % guard)
        w("#define %s" % guard)
        w()
        w('#include "%s%s"' % (self.base, self.types.opt.header_suffix))
        for f in self.spec.included_files():
            w('#include "%s"' % dds_header_of_file(f))
        w()
        w("#include <rustorb/dds/types.hpp>")
        w()
        w("static_assert(::rustorb::dds::generated_code_version == %d," % GENERATED_CODE_VERSION)
        w('              "%s was generated for another version of rustorb-dds");' % self.idl_name)
        w()
        w.lines.extend(body.lines)
        if topics:
            w("namespace dds {")
            w("namespace topic {")
            w()
            for n in topics:
                c = self.cxx(n)
                w("template <> struct is_topic_type<%s> {" % c)
                w("  enum { value = 1 };")
                w("};")
                w("template <> struct topic_type_name<%s> {" % c)
                w('  static std::string value() { return "%s"; }' % self.type_name(n))
                w("};")
                w()
            w("}  // namespace topic")
            w("}  // namespace dds")
            w()
        w("#endif")
        return w.text()

    def builder_fn(self, node, build):
        """The function that builds the type of ``node`` once; ``build``
        writes the body of the lambda that returns its type_ref."""
        w = self.w
        ns = IDL_NS + tuple(cxx_name(m) for m in fe.enclosing_modules(node))
        for n in ns:
            w("namespace %s {" % n)
        w("inline const rdds_type* %s() {" % cxx_name(node.name))
        w.indent()
        w("static const %s::type_ref t = [] {" % RD)
        w.indent()
        build()
        w.dedent()
        w("}();")
        w("return t.get();")
        w.dedent()
        w("}")
        for n in reversed(ns):
            w("}  // namespace %s" % n)
        w()

    def codec(self, node, write, read):
        """``rustorb::dds::codec<T>`` of a struct, union, enum or bitmask;
        ``write`` and ``read`` write the bodies of its functions."""
        w = self.w
        c = self.cxx(node)
        w("namespace rustorb {")
        w("namespace dds {")
        w("template <> struct codec<%s> {" % c)
        w.indent()
        w("static const rdds_type* type() { return %s(); }" % self.builder(node))
        w("static void write(rdds_out* s, const %s& v) {" % c)
        w.indent()
        write()
        w.dedent()
        w("}")
        w("static void read(rdds_in* s, %s& v) {" % c)
        w.indent()
        read()
        w.dedent()
        w("}")
        w.dedent()
        w("};")
        w("}  // namespace dds")
        w("}  // namespace rustorb")
        w()

    def enum(self, node):
        w = self.w
        bits = fe.bit_bound(node, 32, 1, 32)
        ext = fe.extensibility(node, "final")
        default = [v.name for v in node.values if fe.annotation(v, "default_literal") is not None]
        c = self.cxx(node)

        def build():
            w('%s::enum_builder b("%s", %d, %s);' % (RD, self.type_name(node), bits, EXTENSIBILITY[ext]))
            for v in node.values:
                if default and v.name == default[-1]:
                    w('b.literal("%s", %d, true);' % (v.name, v.value))
                else:
                    w('b.literal("%s", %d);' % (v.name, v.value))
            w("return b.build();")

        self.builder_fn(node, build)
        self.codec(
            node,
            lambda: w("rdds_out_enum(s, static_cast<int32_t>(v));"),
            lambda: w("v = static_cast<%s>(rdds_in_enum(s));" % c),
        )

    def bitmask(self, node):
        w = self.w
        bits = node.bit_bound
        for v in node.values:
            if v.position >= bits:
                raise fe.GeneratorError(
                    "the position %d of %s is not below @bit_bound(%d)" % (v.position, v.name, bits),
                    node)
        ext = fe.extensibility(node, "final")
        c = self.cxx(node)

        def build():
            w('%s::bitmask_builder b("%s", %d, %s);' % (RD, self.type_name(node), bits,
                                                        EXTENSIBILITY[ext]))
            for v in node.values:
                w('b.flag("%s", %d);' % (v.name, v.position))
            w("return b.build();")

        self.builder_fn(node, build)
        self.codec(
            node,
            lambda: w("rdds_out_bitmask(s, static_cast<uint64_t>(v));"),
            lambda: w("v = static_cast<%s>(rdds_in_bitmask(s));" % c),
        )

    def typedef(self, node):
        w = self.w
        self.check_scope(node)
        t = fe.type_of(node.type, node)
        self.builder_fn(node, lambda: w('return %s::alias_type("%s", %s);' % (
            RD, self.type_name(node), self.type_expr(t, node))))

    def type_flags(self, node):
        flags = []
        if fe.is_nested(node):
            flags.append("RDDS_TYPE_NESTED")
        if fe.autoid(node) == "hash":
            flags.append("RDDS_TYPE_AUTOID_HASH")
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
            return "nullptr"
        return '"%s"' % fe._string_arg(a)

    def struct(self, node):
        w = self.w
        if getattr(node, "base", None) or getattr(node, "_base", None):
            raise fe.GeneratorError(
                "struct inheritance (of %s) is not supported for DDS yet" % node.name, node)
        ext = fe.extensibility(node, self.extensibility)
        members = list(node.members)
        ids = fe.member_ids(node, members)
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
                    flags.append("RDDS_MEMBER_" + flag)
            shape = self.shape(OptionalType(t) if opt else t, m)
            info.append((m, t, " | ".join(flags) or "0", shape))

        def build():
            w('%s::struct_builder b("%s", %s, %s);' % (
                RD, self.type_name(node), EXTENSIBILITY[ext], self.type_flags(node)))
            for (m, t, flags, _), mid in zip(info, ids):
                w('b.member("%s", %du, %s, %s, %s);' % (
                    m.name, mid, self.type_expr(t, m), flags, self.hash_id(m)))
            w("return b.build();")

        self.builder_fn(node, build)

        def write():
            if not info:
                w("(void)s;")
                w("(void)v;")
            for m, _, _, shape in info:
                w("%s::write(s, v.%s());" % (shape, cxx_name(m.name)))

        def read():
            if not info:
                w("(void)s;")
                w("(void)v;")
            for m, _, _, shape in info:
                w("%s::read(s, v.%s());" % (shape, cxx_name(m.name)))

        self.codec(node, write, read)

    def union(self, node):
        w = self.w
        ext = fe.extensibility(node, self.extensibility)
        if ext == "mutable":
            raise fe.GeneratorError(
                "mutable unions are not supported for DDS yet (union %s)" % node.name, node)
        disc = fe.type_of(node.discriminator_type, node)
        rdisc = disc.resolved()
        dt = self.types.ctype(disc, node)
        c = self.cxx(node)
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
            flags = "RDDS_MEMBER_DEFAULT_LABEL" if m.is_default else "0"
            info.append((m, t, labels, flags, self.shape(t, m)))

        def build():
            w('%s::union_builder b("%s", %s, %s, %s);' % (
                RD, self.type_name(node), EXTENSIBILITY[ext], self.type_flags(node),
                self.type_expr(disc, node)))
            for (m, t, labels, flags, _), mid in zip(info, ids):
                w('b.member("%s", %du, %s, {%s}, %s, %s);' % (
                    m.name, mid, self.type_expr(t, m), ", ".join(str(l) for l in labels), flags,
                    self.hash_id(m)))
            w("return b.build();")

        self.builder_fn(node, build)
        if rdisc.kind == "char":
            to_int = "static_cast<int64_t>(static_cast<unsigned char>(v._d()))"
        elif rdisc.kind == "wchar":
            to_int = "static_cast<int64_t>(static_cast<uint16_t>(v._d()))"
        else:
            to_int = "static_cast<int64_t>(v._d())"

        def write():
            w("rdds_out_discriminator(s, %s);" % to_int)
            w("switch (%s::_rorb_member(v._d())) {" % c)
            for i, (m, _, _, _, shape) in enumerate(info):
                w("  case %d:" % i)
                w("    %s::write(s, v.%s());" % (shape, cxx_name(m.name)))
                w("    break;")
            w("  default:")
            w("    break;")
            w("}")

        def read():
            w("const %s d = static_cast<%s>(rdds_in_discriminator(s));" % (dt, dt))
            w("switch (%s::_rorb_member(d)) {" % c)
            for i, (m, t, _, _, shape) in enumerate(info):
                w("  case %d: {" % i)
                w("    %s x{};" % self.types.ctype(t, m))
                w("    %s::read(s, x);" % shape)
                w("    v.%s(std::move(x), d);" % cxx_name(m.name))
                w("    break;")
                w("  }")
            w("  default:")
            w("    v = %s();" % c)
            w("    v._d(d);")
            w("    break;")
            w("}")

        self.codec(node, write, read)


def write_outputs(spec, outdir, options):
    """Writes ``Foo_dds.hh`` (and, for ``options.dds_only``, ``Foo.hh``)
    for ``spec`` under ``outdir``; returns the paths written."""
    written = []
    if options.dds_only:
        types = CxxDdsTypes(spec, options)
        texts = [(types.base + options.header_suffix, types.generate_header())]
    else:
        types = CxxBackend(spec, options)
        texts = []
    gen = CxxDds(spec, types, options.extensibility)
    texts.append((dds_header_of_file(spec.path), gen.generate()))
    os.makedirs(outdir, exist_ok=True)
    for name, text in texts:
        path = os.path.join(outdir, name)
        tmp = path + ".tmp"
        with open(tmp, "w") as f:
            f.write(text)
        os.replace(tmp, path)
        written.append(path)
    return written


__all__ = ["CxxDds", "CxxDdsTypes", "Options", "write_outputs"]
