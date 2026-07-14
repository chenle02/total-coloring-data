# Universal auxiliary-extension census, orders 1--8

This report documents the `total-coloring-data` v0.1.0 finite census for the
universal auxiliary-extension search associated with the total-coloring
project of Le Chen and Songling Shan. The machine-readable release summary is
`results/order-1-8-universal-census-summary-v1.json`.

## Scientific boundary

The release is exhaustive only for the complete unrestricted `nauty-geng`
streams of simple unlabeled graphs on orders 1 through 8, filtered by
`2*Delta(G) >= n`. For every retained graph, every canonical equitable
`(Delta(G)+1)`-class partition was subjected to the three declared positive
witness checks. The finite census is computational evidence; it does not prove
an unbounded total-coloring theorem. Generator completeness is assumed for the
hash-pinned `geng` executable.

## Census receipts

| Order | All graphs | Verified in scope | Skipped by filter | Partitions | Witness checks |
|---:|---:|---:|---:|---:|---:|
| 1 | 1 | 0 | 1 | 0 | 0 |
| 2 | 2 | 1 | 1 | 1 | 3 |
| 3 | 4 | 2 | 2 | 2 | 6 |
| 4 | 11 | 8 | 3 | 16 | 48 |
| 5 | 34 | 23 | 11 | 69 | 207 |
| 6 | 156 | 137 | 19 | 1,106 | 3,318 |
| 7 | 1,044 | 894 | 150 | 14,783 | 44,349 |
| 8 | 12,346 | 11,922 | 424 | 514,050 | 1,542,150 |
| **Total** | **13,598** | **12,987** | **611** | **530,027** | **1,590,081** |

There were zero `candidate_unsat`, `unknown`, `error`, or cross-backend
disagreement outcomes. For order 8, the retained partition counts by maximum
degree 4, 5, 6, and 7 were respectively 199,970; 266,083; 46,953; and 1,044.

The replay archive contains 24 regular members. Its eight `records.jsonl`
members total 697,839,562 bytes, and all archived members total 697,853,659
uncompressed bytes.

## Immutable provenance

- Scientific generating commit:
  `61c576fba28a03a91f6a7695e21d130cd7e76f22`.
- Generating source-tree digest:
  `61c154914c407b8f6de1d3c0f0f374c9f478fe3bcc083890031a788c4afdb337`.
- Generating lockfile digest:
  `d10f31c873f4a0afd1cb9d4f4eaa563e3e6323b978851ed803da22426d27f92f`.
- Public toolkit release: [`v0.1.0`](https://github.com/chenle02/total-coloring-toolkit/releases/tag/v0.1.0),
  publisher commit `7dd92cb8ae5ef1f9714ad99fff88597c556031fa`.
- Toolkit wheel SHA-256:
  `15b5ab482706a9ffa88ae79050fcabc9ae4eb9b4cddf23eefcc0a149b9287a91`.
- Toolkit source-distribution SHA-256:
  `f2c7d9c44e4a79f9d13709b43f92f8261a0ca45b8cf3bb39b6239b94c02d29ed`.
- Toolkit `SHA256SUMS` SHA-256:
  `402544d0774470e604b636c0fcb494fbbec69ecdbe32eb95914f46c93a540a80`.
- Generator: nauty 2.9.3 `geng`, SHA-256
  `1b760fca10c525f983a8e576d5e4bbdc8c740dca38ca163f48ebe421032adf3e`.
- Export environment: CPython 3.13.7 on Linux, `uv` 0.8.13, AMD Ryzen
  7 3700X, 16 logical CPUs, and 64 GiB RAM.
- Candidate creation time: `2026-07-14T17:12:49Z`.

The software release was built from a fresh clone. Its gate built the wheel
from the audited source distribution, checked exact archive membership and
source-byte parity, ran Twine, installed the wheel into a clean environment,
and passed installed schema and CLI semantic smokes. The downloaded public
release assets reproduced the audited bytes without GitHub authentication.

## Release artifacts

- Compact summary: `results/order-1-8-universal-census-summary-v1.json`,
  8,867 bytes, SHA-256
  `d1f9f6062e19c321cbd64810119ad3a62a29c98c966fc5913f52b08c7bede225`.
- External replay archive:
  [`universal-census-orders-01-08-v1.tar.gz`](https://github.com/chenle02/total-coloring-data/releases/download/v0.1.0/universal-census-orders-01-08-v1.tar.gz),
  114,485,197 bytes, SHA-256
  `63b704c4035a06d617b000462d0a7ddd208b4024e219329f617fc464b2b53115`.

The archive is deterministic gzip-wrapped USTAR. It carries every per-order
manifest, completion marker, and record stream needed for exact replay. The
large archive is a GitHub release asset rather than a Git object.

## Verification performed

The release exporter was installed from the publicly downloaded toolkit wheel.
It first captured a private immutable snapshot of all completed runs, replayed
every stored witness, regenerated every exact `geng` stream through EOF, built
the deterministic archive and compact bundle, and then semantically replayed
the serialized archive before installing either output.

An independent Python-standard-library audit separately parsed all 13,598
records, reconstructed every complement-matching partition, checked all
1,590,081 witnesses against the encoded auxiliary graphs, and matched every
count and fingerprint. That audit program is not presented as a supported
public verifier; its source SHA-256 was
`7ab07c5815562837af3f4e8f7139622635f322e5339e48c02e7b7029f400f5a8`.
The supported verifier is the tagged toolkit release.

The toolkit release also passed 922 tests with three expected skips and at
least 90% measured coverage, strict formatting and typing gates, package
audits, exact installed-`geng` integration, Python 3.11--3.14 hosted CI, and
CodeQL. The data contract passed its Python 3.11 and 3.13 hosted verifier
matrix.

## Public replay commands

Download and authenticate the public assets:

```bash
gh release download v0.1.0 \
  --repo chenle02/total-coloring-data \
  --pattern universal-census-orders-01-08-v1.tar.gz
sha256sum universal-census-orders-01-08-v1.tar.gz
```

From a clone of `total-coloring-data` at tag `v0.1.0`, validate the release
envelope without network access:

```bash
python3 scripts/verify_release.py \
  --root . \
  --expected-code-repository https://github.com/chenle02/total-coloring-toolkit \
  --external-file \
  archives/universal-census-orders-01-08-v1.tar.gz=universal-census-orders-01-08-v1.tar.gz
```

Then install the tagged toolkit wheel and perform the scientific replay:

```bash
python3 - <<'PY'
import json
from pathlib import Path
from total_coloring.universal_release import validate_replay_archive

summary = json.loads(
    Path("results/order-1-8-universal-census-summary-v1.json").read_text()
)
validate_replay_archive(
    "universal-census-orders-01-08-v1.tar.gz",
    summary,
    executable="/usr/bin/geng",
)
print("OK: exact order-1--8 archive replay")
PY
```

The expected archive digest is the SHA-256 recorded above. Any byte change,
member omission, malformed record, witness failure, generator-stream mismatch,
or missing EOF causes verification to fail closed.
