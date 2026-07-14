# Changelog

All notable integrity-contract changes are documented here. Dataset releases
and schema versions are independently versioned.

## Unreleased

### Added

- Additive `dataset-manifest-v2` support for hash-bound external replay
  archives while preserving the exact local managed-root and `SHA256SUMS`
  inventories.
- Trusted `universal-census-summary-v1` schema for compact finite-scope census
  provenance, run receipts, count totals, limitations, and replay bindings.
- Optional, offline `--external-file NAME=PATH` byte verification with no
  implicit network access.
- Standard-library replay-archive inspection with deterministic gzip/USTAR
  metadata, exact safe-member inventory, strict embedded toolkit parsing,
  recomputed run fingerprints, provenance checks, and full hash/count-chain
  validation.
- Explicit unsharded v1 release profile, unrestricted `geng -q ORDER`
  invocation, `scope.require_high_degree: true`, exactly one `finite_bound`
  claim over every run order, canonical derived finite-scope language, exact
  paired limitations, and nonvacuous `verified_in_finite_scope` gates. Other
  claim types are reserved and rejected by v1.
- Byte-exact archive framing: one level-9 gzip member through raw EOF with
  header `1f8b08000000000002ff`, valid CRC32/ISIZE, no suffix or concatenated
  member, and receipt-derived deterministic USTAR headers, padding, end blocks,
  10240-byte record alignment, and decompressed length.
- Defensive parser bounds of 4 MiB for embedded metadata members and 16 MiB
  including LF for JSONL physical lines, plus strict JSON document, nesting,
  and integer-literal limits.
- Fail-closed lone-surrogate and malformed-URI handling, bounded UTF-8 checksum
  parsing, bounded diagnostics, positive order invariants, a 256-run ceiling,
  and exact nonboolean transcript index and color-count cross-bindings.
- Canonical, linear-time SemVer release-string validation without build
  metadata, canonical lowercase unescaped HTTPS external URLs, and fail-closed
  operational use of only the exact `["reports", "results"]` managed-root
  array.
- Independent trusted-code-repository policy with an explicit CLI reuse
  override, coordinated-substitution regressions, literal RFC 3986 path
  component validation, explicitly typed shard constants, and bounded
  validation of oversized summary arrays.
- Adversarial v2 regression coverage for schema substitution, path and
  namespace collisions, ordering, duplicates, missing or modified external
  bytes, provenance mismatches, and count-conservation failures.
- Byte-exact order-2 fixtures produced by public toolkit commit
  `61c576fba28a03a91f6a7695e21d130cd7e76f22`.

### Compatibility

- Manifest v1 and `result-v1` remain accepted without migration.
- The active development manifest remains on v1; this change publishes only
  release infrastructure and no scientific result artifact.
