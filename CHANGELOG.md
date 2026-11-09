# Changelog

The versions of rustorb-idl (the `rustorb-idl` Python package and the
`rustorb-codegen` crate). Versions up to 0.2.0 were released from
rustorb/rustorb; see its CHANGELOG.md for them.

## [Unreleased]

## [0.3.0] - 2026-11-09

### Added

- Java: `-Wbdds` / `-Wbdds_only` write a class `<Name>Codec` next to each
  struct, union, enum, bitmask and typedef, the DDS type support for
  rustorb-dds's Java binding (the DDS Java 5 PSM, `org.omg.dds`):
  `type()` builds the type through rustorb-dds's C ABI, and the
  `INSTANCE` of a struct, union or enum codec writes and reads its values
  (rustorb/rustorb-dds#46). Their TypeObjects are those of other
  implementations for the same IDL. `-Wbdds_only` writes the classes of
  the types without CORBA, mostly as the IDL4 to Java mapping has them:
  Java enums with `getValue()` and `valueOf(int)` (and `@value`),
  `@optional` as boxed types and `null`, `bitmask` as `java.util.BitSet`
  and an enum `<Name>Flags`, `int8` as `byte`, and members that are not
  null in a new struct. `-Wbdds` writes the codecs beside the CORBA code,
  for types used by both. `-Wbextensibility` applies to them too.
- C++: `-Wbdds` / `-Wbdds_only` write `Foo_dds.hh`, the DDS type support of
  the structs, unions, enums, bitmasks and typedefs of the file for
  rustorb-dds's C++ binding (the ISO/IEC C++ PSM, `<dds/dds.hpp>`):
  `rustorb::dds::codec<T>`, which builds each type through rustorb-dds's C
  ABI and writes and reads its values, and `dds::topic::is_topic_type` and
  `topic_type_name` for topic types (rustorb/rustorb-dds#45). Their
  TypeObjects are those of other implementations for the same IDL.
  `-Wbdds_only` writes `Foo.hh` with only the types and constants, which
  need nothing but the standard library, and allows `@optional`
  (`std::optional`), `@external`, `@value`, `int8` and `bitmask`; bounded
  strings and sequences are then `std::string` and `std::vector`.
  `-Wbdds` writes `Foo_dds.hh` beside the CORBA code, for types used by
  both. `-Wbextensibility` applies to them too.
- Python: `-Wbdds` / `-Wbdds_only` write `Foo_dds.py`, the DDS types of the
  file (structs, unions, enums, bitmasks, typedefs, constants) declared for
  rustorb-dds's Python package `rustorb_dds`, whose TypeObjects match those
  of other implementations for the same IDL (rustorb/rustorb-dds#35).
  `-Wbextensibility` applies to them too.
- `-Wbami` (python, c++11, java): the implied IDL of callback AMI
  (rustorb/rustorb#137, rustorb's docs/ami.md). Each interface but local and
  abstract ones gets an `AMI_<I>Handler` interface, inheriting the handlers of
  its bases or `Messaging::ReplyHandler`, in the same module and file, with
  `<op>(ami_return_val, out and inout arguments)` and
  `<op>_excep(Messaging::ExceptionHolder)` for each two-way operation and
  `get_` / `set_` ones for attributes; clashing names get more `AMI_`. The
  backends write the handlers as ordinary interfaces; the `sendc_` operations
  of the stubs and the runtime code of `Messaging` come with each language.
  `Messaging.idl` ships in `rustorb-idl --idl-dir`. `-brust -Wbami` is an
  error (Rust has the `op_async` methods). The handlers name the built-in
  types of module CORBA by their scoped name (`::CORBA::TypeCode`), so
  operations that use them get handlers too.
- Python `-Wbami` (rustorb/rustorb#138): the stubs get
  `sendc_<op>(ami_handler, in and inout arguments)`, `sendc_get_<attr>` and
  `sendc_set_<attr>`, which call the runtime's `CORBA.Object._sendc`
  (needs a rustorb with callback AMI in Python). The `Messaging` module is
  the runtime's `rustorb.Messaging`, not generated code. The handlers of
  interfaces with abstract bases have the operations of those bases too.
- C++ `-Wbami` (rustorb/rustorb#141): the stubs get virtual
  `sendc_<op>(ami_handler, in and inout arguments)`, `sendc_get_<attr>` and
  `sendc_set_<attr>`, which call the runtime's `rustorb::detail::sendc` with
  the operation's raises clause, and the generated source registers the
  file's user exceptions so that an `ExceptionHolder` from another process
  can raise them. `Messaging` is the runtime's `<rustorb/messaging.h>`
  (needs a rustorb with callback AMI in C++), not `Messaging.hh`.
- Java `-Wbami` (rustorb/rustorb#139): the stub classes `_<I>Stub` (not the
  interfaces, which servants implement) get `sendc_<op>(ami_handler, in and
  inout arguments)`, `sendc_get_<attr>` and `sendc_set_<attr>`, for the
  interface and its bases, which call the runtime's `org.rustorb.Stubs.sendc`
  with an `org.rustorb.SendcCall` (needs a rustorb with callback AMI in
  Java); a reference is cast to the stub class to use them. `Messaging` is
  the runtime's package `org.omg.Messaging`.
- Rust: `-Wbxtypes[=PATH]` describes the DDS types (structs, unions, enums,
  bitmasks, typedefs) for DDS-XTypes, with impls of
  `rustorb_xtypes::types::DescribeType` from which rustorb-dds builds their
  TypeObjects (rustorb/rustorb-dds#31). Types that depend on themselves are
  refused for now.

### Changed

- The generator moved from `crates/rustorb-codegen` of rustorb/rustorb to this
  repository, with its history (rustorb/rustorb#118). Its tests check the
  output against `tests/golden/`; the tests that compile and run the
  generated code need a rustorb checkout (`RUSTORB_SRC`)

### Fixed
- Java: the skeleton (`<I>POA`) of an interface without operations no longer
  has an unreachable `return` after its `switch`, which javac refused.

- Java: the Helper of a union with no default member whose labels use
  every value of the discriminator (an enum) called `__default`, which
  such a union does not have, and did not compile; it now throws
  `MARSHAL` for a discriminator with no member.
- Rust: members of type `string`, `sequence`, `@optional` and `@external`,
  and object references, name the standard types by their full path
  (`::std::string::String`, `::std::vec::Vec`, `::std::option::Option`,
  `::std::boxed::Box`). An IDL type that maps to one of those names, such
  as ROS 2's `std_msgs::msg::dds_::String_` (Rust `String`), shadowed the
  standard type in its module, and the generated code did not compile.

## [0.2.0] - 2026-11-02

Released from rustorb/rustorb (tag v0.2.0).
