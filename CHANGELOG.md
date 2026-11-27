# Changelog

The versions of rustorb-idl (the `rustorb-idl` Python package and the
`rustorb-codegen` crate). Versions up to 0.2.0 were released from
rustorb/rustorb; see its CHANGELOG.md for them.

## [Unreleased]

### Added

- Rust: `-Wbshared_octets` maps an unbounded `sequence<octet>` (typedefs
  and members too) to rustorb-core's shared `Octets` (descriptor
  `idl::SharedOctets`) instead of `Vec<u8>`, and its `in` arguments to
  `&Octets`: a large one is received without being copied out of the
  message and sent without being copied into it (rustorb/rustorb#211).
  Needs a rustorb-core with `idl::SharedOctets`; not with `-Wbdds` or
  `-Wbdds_only`. The default mapping is unchanged.
- C#: `-Wbdds` / `-Wbdds_only` write `Foo_dds.cs`, the DDS type support of
  the structs, unions, enums, bitmasks and typedefs of `Foo.idl` for
  rustorb-dds's .NET binding `Rustorb.Dds` (rustorb/rustorb-dds#93,
  #18): a class `<Name>Codec` per type, whose `DdsType()` builds the
  DDS-XTypes type as the other back ends describe it (so the TypeObjects
  match), and whose `Instance` (`Rustorb.Dds.ICodec<T>`) writes and reads
  the values; a `ModuleInitializer` registers the struct and union codecs
  with `Rustorb.Dds.TypeSupport`. `-Wbdds_only` writes `Foo.cs` with only
  the types and constants, in the shape of `-bcsharp`, and no CORBA:
  `@optional` members are nullable, `@external` members plain, enums take
  their `@value`s, `int8` is `sbyte`, bitmasks are `[Flags]` enums.
  `-Wbextensibility` sets the extensibility of types without an
  annotation. Struct inheritance, maps, recursive types, bitsets and
  forward declarations are refused.
- Ruby: `-Wbdds` / `-Wbdds_only` write `Foo_dds.rb`, the DDS type support
  of `Foo.idl` for rustorb-dds's Ruby binding, the `rustorb-dds` gem
  (rustorb/rustorb-dds#92, #17). Each struct, union, enum, bitmask and
  typedef gets `self._dds_type`, which describes the DDS-XTypes type to
  `DDS::Types` as the other back ends do (so the TypeObjects match).
  `-Wbdds_only` also writes the types and constants themselves, without
  CORBA: structs are `DDS::Struct` subclasses with `MEMBERS` and
  `DEFAULTS`, unions `DDS::Union` subclasses with an accessor per member,
  enums modules of their `@value`s, bitmasks modules of bit values;
  `-Wbdds` adds `_dds_type` to the classes of `-bruby`. `-Wbextensibility`
  sets the extensibility of types without an annotation. Struct
  inheritance, mutable unions, recursive types, bitsets and forward
  declarations are refused.

## [0.5.0] - 2026-11-22

Three new back ends: `-bcsharp` (IDL4 to C#), `-bc` (the C mapping) and
`-bruby` (the Ruby mapping), for the .NET, C and Ruby bindings of
rustorb 0.7.0 (rustorb/rustorb#176).

### Added

- C: IDL 4 `int8`, bitmask and bitset in `-bc` (rustorb/rustorb#187).
  `int8` is the runtime's `CORBA_int8`, sent and typed as an octet. A
  bitmask or a bitset is a typedef of the unsigned integer that holds its
  bits, whose descriptor and TypeCode it uses (as the C++ mapping sends
  them): the bitmask's values are constants `<Scope>_<VALUE>`, the
  bitset's fields macros `<Name>_<field>(v)` and `<Name>_set_<field>(p,
  x)` (signed fields are sign-extended). Bitset inheritance is an error;
  `@default` and `@range` are ignored.
- C: `-bc -Wbami`, callback AMI (rustorb/rustorb#187). The implied
  `AMI_<I>Handler` interfaces are generated as interfaces on
  `Messaging_ReplyHandler` (from rustorb's `<rustorb/messaging.h>`), and
  after each handler come the `sendc_` functions of its interface,
  `<I>_sendc_<op>(obj, ami_handler, <in and inout values>, ev)`, over the
  runtime's `rustorb_c_sendc`. `Messaging::ExceptionHolder` is the
  runtime's struct `Messaging_ExceptionHolder`, passed to the `_excep`
  operations as an in struct.
- C: local interfaces in `-bc` (rustorb/rustorb#187). A local interface has
  the stubs and the `POA_<Name>` structs of an interface; `POA_<Name>__init`
  makes a struct the implementation of local objects (it is not activated
  in a POA), `<Name>__create(impl, ev)` makes one, and its stubs call the
  implementation directly. Its TypeCode is `tk_local_interface`; sending
  one is `MARSHAL` (minor 4).
- C#: local interfaces and the IDL 4 bitmask, bitset, `@default` and
  `@range` / `@min` / `@max` in `-bcsharp` (rustorb/rustorb#186). A local
  interface is `I<Name>` and an abstract class `<Name>` on
  `Corba.LocalObject` with every operation and attribute abstract, to
  derive implementations from; its helper's `write` and `read` raise
  `MARSHAL` (minor 4). A bitmask is a `[Flags]` enum on the unsigned type
  of its `@bit_bound`, a bitset a struct of bitfield properties; both are
  sent, as in the C++ mapping, as the unsigned integer that holds their
  bits, with its TypeCode. `@default` sets a member's initial value;
  `@range` is checked when a struct is sent (`BAD_PARAM`) and read.
  `int8` now has the TypeCode of octet, as in the C++ mapping, instead of
  being an error where a TypeCode is needed. Test IDL:
  `tests/idl/LocalTest.idl`.

- C#: `-bcsharp -Wbami`, callback AMI (rustorb/rustorb#186): the
  `sendc_` operations on the stub class (not on `I<Name>`, which other
  classes may implement), over `Rustorb.Ami.Sendc`, with the implied
  `AMI_<Name>Handler` interfaces on the runtime's `Messaging`. Every user
  exception is registered with the runtime (`Rustorb.UserExceptions`),
  which raises those of `Messaging.ExceptionHolder`.

- C#: valuetypes, value boxes, custom valuetypes and abstract interfaces
  in `-bcsharp` (rustorb/rustorb#186). A valuetype is the abstract class
  of IDL4 to C# 7.6 (state members as properties, private ones protected;
  operations, those of supported interfaces and `[Omg.Types.Factory]`
  initializers abstract) on its concrete base or `Corba.ValueBase`, with
  its `_truncatable_ids`, `_write` and `_read`; one without operations
  also gets `OBV_<Module>.<Name>`, a concrete class with a constructor of
  every state member, which its default factory makes. An abstract
  valuetype is the interface `I<Name>`; a value box a class with the
  property `value`; a custom valuetype implements `Corba.ICustomMarshal`.
  An abstract interface is `I<Name>` and a stub class, read and written as
  a reference or a value. A module initializer registers the default
  factories and the TypeCodes of the valuetypes. Every interface also gets
  the tie `<Name>POATie`.

- Ruby: `-bruby` (also `-brb`) writes the OMG Ruby Language Mapping (RCLM
  1.2, formal/2013-04-05) for rustorb's Ruby binding (the `rustorb` gem,
  rustorb/rustorb#183, #184): `<File>C.rb` with the types (structs, unions
  and exceptions as classes on `CORBA::Portable::Struct`,
  `CORBA::Portable::Union` and `CORBA::UserException`, enums as modules of
  Integer constants, typedefs, constants, `_tc` on each, made when first
  used so that recursive types need nothing more) and the stubs (a module
  per interface with `_narrow`, a method per operation and `x` / `x=` per
  attribute, out and inout values returned after the result), and
  `<File>S.rb` with the skeletons (`POA::<Module>::<I>`). Names that must
  be Ruby constants start with a capital; keywords and the methods every
  object has get an `r_` prefix. IDL 4: `int8` (an Integer sent as an
  octet), bitmasks (modules of `1 << position` constants), bitsets
  (`Rustorb::Bitset` classes sent as their holder integer), `@default`
  (`DEFAULTS`) and `@range` / `@min` / `@max` (`RANGES`, checked when a
  struct is sent or received). A local interface is a module (with its
  `_tc`, a tk_local_interface, and nested definitions) that
  implementations on `CORBA::LocalObject` include, with no stub or
  skeleton. Valuetypes are classes on `CORBA::ValueBase` (abstract ones
  modules, custom ones with `CORBA::CustomMarshal`, ones that support an
  interface servants of it through `PortableServer::ServantMethods`),
  registered with `Rustorb::Values` (as their own factory when they have
  no behaviour); value boxes are the boxed values; abstract interfaces are
  modules with `Rustorb::AbstractInterfaceModule`. `-bruby -Wbami`
  (callback AMI, rustorb/rustorb#188): the `AMI_<I>Handler` interfaces on
  the runtime's `Messaging::ReplyHandler`, and `sendc_<op>(ami_handler,
  ...)` methods in the stubs, which call `CORBA::Object#_sendc`.

- C: `-bc` writes the OMG C Language Mapping 1.0 (formal/99-07-35) for
  rustorb's C binding (librustorb_c, rustorb/rustorb#180, #181): a
  `<File>.h` and a `<File>.c` per IDL file with the types (structs, unions
  as `_d` and `_u`, enums, sequences with `__alloc` and `_allocbuf`,
  arrays with their `_slice`, `CORBA_fixed_<d>_<s>`), constants as macros,
  `ex_` repository ids and `TC_` TypeCodes, the stubs (`<I>_<op>`,
  `<I>__get_<attr>`, `<I>__set_<attr>`), and the skeletons (`POA_<I>`,
  its epv and vepv, `POA_<I>__init` and `__fini`). The `.c` file holds a
  descriptor of each type that librustorb_c's generic marshalling, freeing
  and copying use. The headers also compile as C++. Valuetypes, abstract
  and local interfaces, bitmasks, bitsets and `-Wbami` are errors for now
  (rustorb/rustorb#187).

- C#: `-bcsharp` (also `-bcs`) writes the IDL4 to C# mapping (OMG
  formal/21-07-01) for rustorb's .NET binding (`Rustorb.Corba`,
  rustorb/rustorb#177): one `<File>.cs` per IDL file with the
  `I<Name>Operations` and `I<Name>` interfaces, the stub class, the
  `<Name>POA` skeleton and the Helper of each interface, classes for
  structs, unions and exceptions (`IEquatable`, the default, copy and
  all-values constructors), enums, constants in `Constants` and Helpers
  with the TypeCode, Any insertion and extraction, and the marshalling.
  `-Wbdotnet_naming` uses the .NET naming scheme (PascalCase, 7.1.1.2).
  Local interfaces, bitmasks, bitsets and `-Wbami` are errors for now
  (rustorb/rustorb#186, rustorb/rustorb#178).

- Rust: with `-Wbdds_only -Wbxtypes`, the interfaces marked `@DDSService`
  get the function-call style of DDS-RPC 1.0 for rustorb-dds: the implied
  IDL of the Enhanced Service Mapping (the In, Out and Result structs of
  each operation and attribute accessor, and the Request and Reply
  structs, `@mutable @autoid(HASH)` with optional members), a trait the
  service implements, `<I>Client` and `<I>Server<S>`. A server announces
  the topics of its bases as topic aliases, so a client of a base calls
  it. The structs marked `@RPCRequestType` and `@RPCReplyType` implement
  rustorb-dds's `BasicRequest` and `BasicReply`. `dds_rpc.idl` (the common
  types of DDS-RPC) comes with the generator, and `-Wbrustorb_dds=PATH`
  sets the path of rustorb-dds (docs/dds-rpc.md, rustorb/rustorb-dds#72).

## [0.4.0] - 2026-11-15

### Changed

- Python, C++ and Java: an operation with a context clause
  (`context ("a", "b*")`) is now an error, with the file and the line, as
  it already was for Rust: "the context clause of f is not supported by
  the Python backend". The clause was dropped without a word before, so
  the requests did not have the form a peer that follows the IDL reads
  (it reads a `CORBA::Context` after the arguments, which the runtimes
  cannot send). The same holds with `-Wbami` for the `sendc_` operations,
  also those of abstract bases in other files, and for the operations of
  valuetypes. The Python `Operation` of an interface no longer has the
  context names (rustorb/rustorb#151).

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
