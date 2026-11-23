"""DDS types in the Ruby backend: ``-bruby -Wbdds`` / ``-Wbdds_only``.

For ``<name>.idl`` it writes ``<name>_dds.rb``: the DDS type support for
rustorb-dds's Ruby binding (gem ``rustorb-dds``, ``require "rustorb/dds"``).
Every struct, union, enum, bitmask and typedef gets ``self._dds_type``,
which describes its DDS-XTypes type with ``::DDS::Types`` (built when first
asked for); the runtime writes and reads the values by that description,
and a topic is made from the class::

    topic = DDS::Topic::Topic.new(participant, "Greetings", M::Greeting)

The types are described as the other generators of rustorb-idl describe
them (java_dds.py, csharp_dds.py), so that their TypeObjects match those
of other implementations for the same IDL.

``-Wbdds`` adds ``_dds_type`` to the classes and modules of ``-bruby``
(ruby_backend.py) in ``<name>C.rb``, which ``<name>_dds.rb`` requires: the
values are those of the OMG Ruby mapping (``CORBA::Portable::Struct``...).
``-Wbdds_only`` writes the classes and modules themselves, in the same
form as ``-bruby`` (the names, a struct's ``attr_accessor`` members and
positional ``new``, a union's ``_disc`` / ``_value`` and accessors, an
enum's Integer constants, a bitmask's ``1 << position`` constants), on the
base classes of the gem (``DDS::Struct``, ``DDS::Union``) and without the
CORBA runtime. It allows the annotations GIOP has no form for:

- an ``enum``'s constants are the values of its enumerators (``@value``);
- an ``@optional`` member is ``nil`` when it is absent; ``@external`` is
  a plain member;
- a member that ``new`` is not given is the zero value of its type (0,
  ``""``, ``[]``, the ``@default_literal`` or first enumerator, a new
  struct...), or ``nil`` when it is optional.

Recursive types and bitsets are not supported for DDS yet (as in the C#
backend).
"""

import os

from . import frontend as fe
from .cxx_dds import NOT_YET
from .java_dds import TYPE_KIND, OptionalType, array_dims, default_literal
from .ruby_backend import (
    HEADER,
    RubyBackend,
    Writer,
    cli_idl_dir,
    const_name,
    file_base,
    method_name,
    ruby_string,
)

#: Must match DDS::Types::GENERATED_CODE_VERSION (rustorb-dds's gem).
GENERATED_CODE_VERSION = 1

T = "::DDS::Types"

TK = {
    "TK_BOOLEAN": "BOOLEAN", "TK_BYTE": "BYTE", "TK_INT8": "INT8", "TK_INT16": "INT16",
    "TK_UINT16": "UINT16", "TK_INT32": "INT32", "TK_UINT32": "UINT32", "TK_INT64": "INT64",
    "TK_UINT64": "UINT64", "TK_FLOAT32": "FLOAT32", "TK_FLOAT64": "FLOAT64",
    "TK_FLOAT128": "FLOAT128", "TK_CHAR8": "CHAR8", "TK_CHAR16": "CHAR16",
}

DISCRIMINATORS = ("short", "long", "ushort", "ulong", "longlong", "ulonglong", "octet", "int8",
                  "boolean", "char", "wchar")


class RubyDds(object):
    """Writes ``<name>_dds.rb``: with ``dds_only``, the classes and modules
    of the types with their ``_dds_type``; else ``_dds_type`` added to
    those of ``-bruby``."""

    def __init__(self, spec, dds_only, extensibility="appendable"):
        self.spec = spec
        self.dds_only = dds_only
        self.extensibility = extensibility
        self.idl_name = os.path.basename(spec.path)
        self.base = file_base(spec.path)
        # For the names, constants and literals of -bruby.
        self.rb = RubyBackend(spec)

    # -- names -----------------------------------------------------------

    def full(self, node):
        return self.rb.full(node)

    def path(self, node):
        return self.rb.path(node)

    def type_name(self, node):
        return "::".join(fe.scope_path(node))

    def check_scope(self, node):
        if fe.inner_scope(node):
            raise fe.GeneratorError(
                "%s is defined inside %s, which DDS types cannot be"
                % (node.name, "::".join(fe.inner_scope(node))),
                node,
            )

    # -- types -----------------------------------------------------------

    def check_named(self, n, where):
        if not (fe.is_typedef(n) or fe.is_struct(n) or fe.is_union(n) or fe.is_enum(n)
                or fe.is_bitmask(n)) or fe.is_exception(n):
            raise fe.GeneratorError("the %s %s has no form in DDS" % (fe.kind_name(n), n.name), where)
        if fe.is_forward(n):
            raise fe.GeneratorError(
                "%s is only declared: recursive types are not supported for DDS" % n.name, where)

    def type_expr(self, t, where):
        """A Ruby expression for the DDS type of a type."""
        k = t.kind
        if k in TYPE_KIND:
            return "%s::%s" % (T, TK[TYPE_KIND[k]])
        if k == "string":
            return "%s.string(%d)" % (T, t.bound or 0)
        if k == "wstring":
            return "%s.wstring(%d)" % (T, t.bound or 0)
        if k == "sequence":
            return "%s.sequence(%s, %d)" % (T, self.type_expr(t.content, where), t.bound or 0)
        if k == "array":
            dims, content = array_dims(t)
            return "%s.array(%s, [%s])" % (T, self.type_expr(content, where),
                                          ", ".join(str(d) for d in dims))
        if k == "bitmask":
            return self.path(t.node) + "._dds_type"
        if k == "bitset":
            raise fe.GeneratorError("bitsets are not supported for DDS yet", where)
        if k == "named":
            n = self.full(t.node)
            self.check_named(n, where)
            self.check_scope(n)
            return self.path(n) + "._dds_type"
        raise fe.GeneratorError("%s has no form in DDS" % k, where)

    def resolve(self, t, where):
        while t.kind == "named":
            n = self.full(t.node)
            self.check_named(n, where)
            if not fe.is_typedef(n):
                break
            t = fe.type_of(n.type, n)
        return t

    # -- values ------------------------------------------------------------

    def zero(self, t, where):
        """The Ruby value of a new member of type t: a literal, or a lambda
        (``-> { ... }``) for values that are not shared."""
        if t.kind == "optional":
            return "nil"
        t = self.resolve(t, where)
        k = t.kind
        if k in ("short", "long", "ushort", "ulong", "longlong", "ulonglong", "octet", "int8", "wchar"):
            return "0"
        if k in ("float", "double"):
            return "0.0"
        if k == "longdouble":
            return "-> { ::DDS::LongDouble.new(0.0) }"
        if k == "boolean":
            return "false"
        if k == "char":
            return '"\\u0000"'
        if k == "string":
            return '-> { +"" }'
        if k in ("wstring", "sequence"):
            return "-> { [] }"
        if k == "array":
            inner = self.zero(t.content, where)
            if inner.startswith("-> { "):
                inner = inner[len("-> { "):-len(" }")]
                return "-> { Array.new(%d) { %s } }" % (t.length, inner)
            return "-> { Array.new(%d, %s) }" % (t.length, inner)
        if k == "bitmask":
            return "0"
        if k == "named":
            n = self.full(t.node)
            if fe.is_enum(n):
                return "%s::%s" % (self.path(n), const_name(default_literal(n).name))
            if fe.is_bitmask(n):
                return "0"
            return "-> { %s.new }" % self.path(n)
        raise fe.GeneratorError("%s has no form in DDS" % k, where)

    def literal(self, value, t, where):
        r = t.resolved()
        if r.kind == "longdouble":
            return "::DDS::LongDouble.new(%r)" % float(value)
        if r.kind == "fixed":
            raise fe.GeneratorError("fixed has no form in DDS", where)
        if r.kind == "int8":
            v = int(value)
            if not -128 <= v <= 127:
                raise fe.GeneratorError("constant %d out of range for int8" % v, where)
            return str(v)
        if r.kind == "named" and fe.is_enum(r.node):
            return "%s::%s" % (self.path(r.node), const_name(value.name))
        return self.rb.literal(value, t, where)

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

    # -- the file ------------------------------------------------------------

    def generate(self):
        body = Writer()
        self.w = body
        self.open_modules = ()
        for it in fe.definitions(self.spec):
            n = it.node
            if fe.is_module(n):
                continue
            if self.dds_only:
                self.enter(it.modules)
            self.definition(n)
        self.enter(())

        w = Writer()
        w(HEADER % self.idl_name)
        w('require "rustorb/dds"')
        if not self.dds_only:
            w('require_relative "%sC"' % self.base)
        for f in self.spec.included_files():
            if f == fe.MESSAGING_IDL:
                continue
            if os.path.dirname(os.path.abspath(f)) == os.path.abspath(cli_idl_dir()):
                continue
            w('require_relative "%s_dds"' % file_base(f))
        w()
        w('%s.check_generated_code(%d, "%s")' % (T, GENERATED_CODE_VERSION, self.idl_name))
        w()
        while body.lines and body.lines[-1] == "":
            body.lines.pop()
        w.lines.extend(body.lines)
        return w.text()

    def enter(self, modules):
        """Closes and opens Ruby modules so that the writer is inside
        ``modules`` (as RubyBackend.enter, without a blank line before
        ``end``)."""
        w = self.w
        keep = 0
        while (keep < len(self.open_modules) and keep < len(modules)
               and self.open_modules[keep] == modules[keep]):
            keep += 1
        for _ in range(len(self.open_modules) - keep):
            while w.lines and w.lines[-1] == "":
                w.lines.pop()
            w.dedent()
            w("end")
            w()
        for m in modules[keep:]:
            w("module %s" % const_name(m))
            w.indent()
        self.open_modules = tuple(modules)

    def open(self, node, kind, base=None):
        """Opens the class or module of node: in -Wbdds_only, defined here
        (inside its Ruby modules); in -Wbdds, the one of FooC.rb,
        reopened by its full path."""
        w = self.w
        if self.dds_only:
            name = const_name(node.name)
            w("%s %s%s" % (kind, name, " < " + base if base else ""))
        else:
            w("%s %s" % (kind, self.path(node)))
        w.indent()

    def close(self):
        self.w.dedent()
        self.w("end")
        self.w()

    def lazy(self, lines):
        """``def self._dds_type``, the type built from ``lines`` once."""
        w = self.w
        w("def self._dds_type")
        w.indent()
        w("%s.lazy(self) do" % T)
        w.indent()
        for line in lines:
            w(line)
        w.dedent()
        w("end")
        w.dedent()
        w("end")

    def definition(self, node):
        if fe.is_const(node):
            if self.dds_only:
                t = fe.type_of(node.type, node)
                self.w("%s = %s" % (const_name(node.name), self.literal(node.value, t, node)))
                self.w()
        elif fe.is_enum(node):
            self.enum(node)
        elif fe.is_bitmask(node):
            self.bitmask(node)
        elif fe.is_typedef(node):
            self.typedef(node)
        elif fe.is_struct(node) and not fe.is_exception(node):
            if fe.is_forward(node):
                if self.dds_only:
                    raise fe.GeneratorError(
                        "forward declarations (of %s) are not supported for DDS" % node.name, node)
                return
            self.struct(node)
        elif fe.is_union(node):
            if fe.is_forward(node):
                if self.dds_only:
                    raise fe.GeneratorError(
                        "forward declarations (of %s) are not supported for DDS" % node.name, node)
                return
            self.union(node)
        # Interfaces, exceptions, valuetypes, natives and bitsets have no
        # DDS form: -Wbdds leaves them to the CORBA code, -Wbdds_only out.

    def type_flags(self, node):
        flags = []
        if fe.is_nested(node):
            flags.append(T + "::NESTED")
        if fe.autoid(node) == "hash":
            flags.append(T + "::AUTOID_HASH")
        return " | ".join(flags) or "0"

    def hash_id(self, m):
        a = fe.annotation(m, "hashid")
        if a is None:
            return "nil"
        return ruby_string(fe._string_arg(a))

    def check_member(self, m):
        for a in NOT_YET:
            if fe.annotation(m, a) is not None:
                raise fe.GeneratorError(
                    "@%s (on %s) is not supported for DDS yet" % (a, m.name), m)
        if fe.annotation(m, "value") is not None:
            raise fe.GeneratorError("@value applies to enumerators, not to %s" % m.name, m)

    # enums and bitmasks

    def enum(self, node):
        self.check_scope(node)
        w = self.w
        bits = fe.bit_bound(node, 32, 1, 32)
        ext = fe.extensibility(node, "final")
        default = default_literal(node)
        self.open(node, "module")
        if self.dds_only:
            for v in node.values:
                w("%s = %d" % (const_name(v.name), v.value))
            w("ENUMERATORS = [%s].freeze" % ", ".join('"%s"' % v.name for v in node.values))
            w()
        literals = []
        for v in node.values:
            d = fe.annotation(v, "default_literal") is not None and v is default
            literals.append('["%s", %d%s]' % (v.name, v.value, ", true" if d else ""))
        self.lazy(['%s.enum_type("%s", %d, :%s, [%s])' % (
            T, self.type_name(node), bits, ext, ", ".join(literals))])
        self.w.dedent()
        self.w("end")
        if self.dds_only:
            for v in node.values:
                w("%s = %d" % (const_name(v.name), v.value))
        w()

    def bitmask(self, node):
        self.check_scope(node)
        w = self.w
        bits = node.bit_bound
        for v in node.values:
            if v.position >= bits:
                raise fe.GeneratorError(
                    "the position %d of %s is not below @bit_bound(%d)" % (v.position, v.name, bits),
                    node)
        ext = fe.extensibility(node, "final")
        self.open(node, "module")
        if self.dds_only:
            w("BIT_BOUND = %d" % bits)
            for v in node.values:
                w("%s = 1 << %d" % (const_name(v.name), v.position))
            w()
        self.lazy(['%s.bitmask_type("%s", %d, :%s, [%s])' % (
            T, self.type_name(node), bits, ext,
            ", ".join('["%s", %d]' % (v.name, v.position) for v in node.values))])
        self.close()

    # typedefs

    def typedef(self, node):
        self.check_scope(node)
        t = fe.type_of(node.type, node)
        target = self.full(t.node) if t.kind == "named" else None
        expr = self.type_expr(t, node)
        if self.dds_only and target is not None and (fe.is_struct(target) or fe.is_union(target)):
            self.open(node, "class", self.path(target))
        else:
            self.open(node, "class" if not self.dds_only and target is not None and (
                fe.is_struct(target) or fe.is_union(target)) else "module")
        self.lazy(['%s.alias_type("%s", %s)' % (T, self.type_name(node), expr)])
        self.close()

    # structs

    def struct(self, node):
        self.check_scope(node)
        if getattr(node, "base", None) is not None:
            raise fe.GeneratorError(
                "struct inheritance (of %s) is not supported for DDS yet" % node.name, node)
        w = self.w
        ext = fe.extensibility(node, self.extensibility)
        members = list(node.members)
        ids = fe.member_ids(node, members)
        info = []
        for m, mid in zip(members, ids):
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
                    flags.append(T + "::" + flag)
            info.append((m, mid, t, " | ".join(flags) or "0", OptionalType(t) if opt else t))
        self.open(node, "class", "::DDS::Struct")
        if self.dds_only:
            w("MEMBERS = [%s].freeze" % ", ".join('"%s"' % method_name(m.name) for m, _, _, _, _ in info))
            if info:
                w("attr_accessor %s" % ", ".join(":" + method_name(m.name) for m, _, _, _, _ in info))
                w("DEFAULTS = { %s }.freeze" % ", ".join(
                    '"%s" => %s' % (method_name(m.name), self.zero(vt, m)) for m, _, _, _, vt in info))
            w()
        lines = ['%s.struct_type(self, "%s", :%s, %s, [' % (
            T, self.type_name(node), ext, self.type_flags(node))]
        for m, mid, t, flags, _ in info:
            lines.append('  ["%s", %d, %s, %s, %s],' % (m.name, mid, self.type_expr(t, m), flags,
                                                        self.hash_id(m)))
        lines.append("])")
        self.lazy(lines)
        self.close()

    # unions

    def union(self, node):
        self.check_scope(node)
        w = self.w
        ext = fe.extensibility(node, self.extensibility)
        if ext == "mutable":
            raise fe.GeneratorError(
                "mutable unions are not supported for DDS yet (union %s)" % node.name, node)
        disc = fe.type_of(node.discriminator_type, node)
        rdisc = disc.resolved()
        if rdisc.kind not in DISCRIMINATORS and not (rdisc.kind == "named" and fe.is_enum(rdisc.node)):
            raise fe.GeneratorError("unsupported union discriminator type %r" % disc, node)
        members = list(node.members)
        ids = fe.member_ids(node, members)
        info = []
        for m, mid in zip(members, ids):
            self.check_member(m)
            if fe.is_optional(m) or fe.is_external(m) or fe.is_key(m):
                raise fe.GeneratorError(
                    "@optional, @external and @key are not supported on union members (%s)" % m.name,
                    m)
            t = fe.type_of(m.type, m)
            labels = [self.label_value(l, disc) for l in m.labels]
            flags = T + "::DEFAULT_LABEL" if m.is_default else "0"
            info.append((m, mid, t, labels, flags))
        self.open(node, "class", "::DDS::Union")
        if self.dds_only:
            w("DEFAULTS = { %s }.freeze" % ", ".join(
                '"%s" => %s' % (m.name, self.zero(t, m)) for m, _, t, _, _ in info))
            w()
            for m, _, _, _, _ in info:
                name = method_name(m.name)
                w('def %s = _get("%s")' % (name, m.name))
                w()
                w("def %s=(value)" % name)
                w.indent()
                w('_put("%s", value)' % m.name)
                w.dedent()
                w("end")
                w()
        lines = ['%s.union_type(self, "%s", :%s, %s, %s, [' % (
            T, self.type_name(node), ext, self.type_flags(node), self.type_expr(disc, node))]
        for m, mid, t, labels, flags in info:
            lines.append('  ["%s", %d, %s, [%s], %s, %s],' % (
                m.name, mid, self.type_expr(t, m), ", ".join(str(l) for l in labels), flags,
                self.hash_id(m)))
        lines.append("])")
        self.lazy(lines)
        self.close()


def write_outputs(spec, outdir, options):
    """Writes ``<name>_dds.rb`` into ``outdir``; returns its path."""
    text = RubyDds(spec, getattr(options, "dds_only", False),
                   getattr(options, "extensibility", "appendable")).generate()
    os.makedirs(outdir, exist_ok=True)
    path = os.path.join(outdir, file_base(spec.path) + "_dds.rb")
    tmp = path + ".tmp"
    with open(tmp, "w", newline="\n") as f:
        f.write(text)
    os.replace(tmp, path)
    return [path]


__all__ = ["RubyDds", "write_outputs"]
