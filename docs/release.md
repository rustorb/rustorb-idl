# リリース

rustorb-idl は rustorb のランタイムとは別の版でリリースする（rustorb/rustorb#118）。0.2.0 までは rustorb のリポジトリから rustorb と同じ版で出した。

| パッケージ | 公開先 |
| --- | --- |
| `rustorb-idl`（`python/`） | PyPI |
| `rustorb-codegen`（`rust/`） | crates.io |

## 手順

1. `tools/set-version.py 0.3.0` で版を書き換え、`CHANGELOG.md` に日付を入れて PR でマージする
2. main のそのコミットにタグ `v0.3.0` を付けて push する。`.github/workflows/release.yml` が wheel・sdist・crate を作り、GitHub Release の下書きに付け、crates.io と PyPI に公開してから Release を公開する
3. rustorb と rustorb-dds で、固定している生成器の版を上げる

## 最初のリリースの前に（管理者）

- PyPI の `rustorb-idl` に trusted publisher を追加する：リポジトリ `rustorb/rustorb-idl`、ワークフロー `release.yml`、環境 `release`（または `PYPI_API_TOKEN` を secret に置く）
- `CARGO_REGISTRY_TOKEN` を secret に置く（`rustorb-codegen` の publish-update の権限）
- GitHub の環境 `release` を作る（承認を必須にするならここで）

## 版の対応

生成コードとランタイムの組み合わせは「生成コードの版」で確かめる（README.md の Versions）。古いランタイムが使えない生成コードに変えるときは、その版をランタイムと一緒に上げ、生成器はマイナー版を上げる。
