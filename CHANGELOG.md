# Changelog

All notable integrity-contract changes are documented here. Dataset releases
and schema versions are independently versioned.

## Unreleased

## [0.1.0] - 2026-07-14

### Added

- First public finite universal auxiliary-extension census for graph orders
  1 through 8: 13,598 graph records, 12,987 verified in scope, 611 filtered,
  530,027 canonical partitions, and 1,590,081 configured witness checks, with
  no candidate-negative, unknown, error, or backend-disagreement outcome.
- Compact machine-readable summary and human-readable release report in Git,
  plus a deterministic 114,485,197-byte external replay archive with SHA-256
  `63b704c4035a06d617b000462d0a7ddd208b4024e219329f617fc464b2b53115`.

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
- Explicit universal-order ceiling 16 enforced by schema and before replay
  archive layout/decompression, plus exact finite-witness descriptions for the
  three canonical checks.
- Adversarial v2 regression coverage for schema substitution, path and
  namespace collisions, ordering, duplicates, missing or modified external
  bytes, provenance mismatches, and count-conservation failures.
- Byte-exact order-2 fixtures produced by public toolkit commit
  `61c576fba28a03a91f6a7695e21d130cd7e76f22`.

### Compatibility

- Manifest v1 and `result-v1` remain accepted without migration.
- The published v0.1.0 manifest uses v2; the standalone verifier can validate
  the Git-resident envelope without downloading the external archive, or
  validate supplied archive bytes entirely offline.

[Unreleased]: https://github.com/chenle02/total-coloring-data/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/chenle02/total-coloring-data/releases/tag/v0.1.0
