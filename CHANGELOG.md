# Changelog

The versions of rustorb-idl (the `rustorb-idl` Python package and the
`rustorb-codegen` crate). Versions up to 0.2.0 were released from
rustorb/rustorb; see its CHANGELOG.md for them.

## [Unreleased]

### Added

- Python: `-Wbdds` / `-Wbdds_only` write `Foo_dds.py`, the DDS types of the
  file (structs, unions, enums, bitmasks, typedefs, constants) declared for
  rustorb-dds's Python package `rustorb_dds`, whose TypeObjects match those
  of other implementations for the same IDL (rustorb/rustorb-dds#35).
  `-Wbextensibility` applies to them too.
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

- Rust: members of type `string`, `sequence`, `@optional` and `@external`,
  and object references, name the standard types by their full path
  (`::std::string::String`, `::std::vec::Vec`, `::std::option::Option`,
  `::std::boxed::Box`). An IDL type that maps to one of those names, such
  as ROS 2's `std_msgs::msg::dds_::String_` (Rust `String`), shadowed the
  standard type in its module, and the generated code did not compile.

## [0.2.0] - 2026-11-02

Released from rustorb/rustorb (tag v0.2.0).
