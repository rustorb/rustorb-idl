# rustorb-idl

IDLパースとコード生成器

The IDL compiler of [rustorb](https://github.com/rustorb/rustorb) (CORBA) and
[rustorb-dds](https://github.com/rustorb/rustorb-dds) (DDS). It reads IDL with
[idl_parser](https://github.com/sugarsweetrobotics/idl_parser) and writes
code for Rust (`-brust`, with the DDS type support of `-Wbdds` /
`-Wbdds_only`), Python (`-bpython`, with the DDS types for rustorb-dds's
`rustorb_dds` package of `-Wbdds` / `-Wbdds_only`), C++11 (`-bc++11`) and
Java (`-bjava`).

| Directory | Package | Published as |
| --- | --- | --- |
| `python/` | the generator, the `rustorb-idl` command ([python/README.md](python/README.md), [docs/python-codegen.md](docs/python-codegen.md)) | `rustorb-idl` on PyPI |
| `rust/` | `rustorb_codegen::Config`, to run `rustorb-idl -brust` from `build.rs` ([rust/README.md](rust/README.md)) | `rustorb-codegen` on crates.io |
| `tests/` | the test IDL and the golden output (`tests/golden/`) | |

This repository was split out of rustorb/rustorb (rustorb/rustorb#118); the
history of `crates/rustorb-codegen` came with it. The mapping documents
(Rust, C++, Java, valuetypes) stay in the rustorb repository, next to the
runtimes they describe.

## Tests

```sh
PYTHONPATH=path/to/idl_parser python3 -m unittest discover -s python/tests
```

- The golden test (`python/tests/test_golden.py`) compares the output for
  the IDL of `tests/idl/` with `tests/golden/`. After a change that changes
  the output on purpose, run
  `IDL_PARSER_DIR=path/to/idl_parser tools/update-golden.py` and commit the
  new files with the change. The Rust output goes through rustfmt.
- The tests that compile or run the generated code need the rustorb
  runtime: set `RUSTORB_SRC` to a checkout of rustorb/rustorb. Without it
  they are skipped. CI runs them against rustorb's main branch, and rustorb's
  own CI runs its runtime tests with the version of the generator it pins.
- `tests/idl/interop/` and `tests/idl/cpp/` are copies of rustorb's
  `interop/idl/` and `cpp/tests/idl/`.

## Versions

Generated code checks that the runtime understands it: Rust code refers to
`rustorb_core::idl::GENERATED_CODE_VERSION_1` (DDS code to
`rustorb_typesupport::GENERATED_CODE_VERSION_1`) and does not compile
against a runtime without it, Python code calls `rustorb._rt.check_version`
on import, and C++ code has a `static_assert` on
`rustorb::generated_code_version`. A change to the
generated code that an older runtime cannot use bumps that version, here and
in the runtime together. The generator is released on its own, with its own
version (`tools/set-version.py`, `docs/release.md`).

## License

GPL-3.0-or-later ([LICENSE](LICENSE)), because the generator builds on
idl_parser. Code produced by the generator is not covered by this license,
and a build dependency on `rustorb-codegen` does not make the crate that
uses it GPL. rustorb and rustorb-dds themselves are MIT OR Apache-2.0.
