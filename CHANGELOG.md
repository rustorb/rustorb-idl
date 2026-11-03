# Changelog

The versions of rustorb-idl (the `rustorb-idl` Python package and the
`rustorb-codegen` crate). Versions up to 0.2.0 were released from
rustorb/rustorb; see its CHANGELOG.md for them.

## [Unreleased]

### Added

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
  error (Rust has the `op_async` methods).

### Changed

- The generator moved from `crates/rustorb-codegen` of rustorb/rustorb to this
  repository, with its history (rustorb/rustorb#118). Its tests check the
  output against `tests/golden/`; the tests that compile and run the
  generated code need a rustorb checkout (`RUSTORB_SRC`)

## [0.2.0] - 2026-11-02

Released from rustorb/rustorb (tag v0.2.0).
