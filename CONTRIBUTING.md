# Contributing

Thank you for helping make computational total-coloring research inspectable
and reproducible. Contributions may improve the verifier, schemas, tests,
documentation, release reports, or reviewed data artifacts.

## Start with the trust boundary

This repository's dependency-free verifier checks a release's integrity
envelope. It does not independently prove the mathematical meaning of an
artifact. Scientific claims need separate receipts from the exact toolkit
commit named by the release manifest, including certificate replay, generator
and count checks, and independent-backend comparisons where applicable.

Never describe a successful integrity check as proof of a theorem. A finite
search is evidence only for its declared generator, filters, shards, software,
configuration, and limits. Solver exhaustion without an independently checked
negative proof remains `candidate_unsat`.

## Before opening a change

For a substantial schema or data-release proposal, open an issue first so that
scope, versioning, licenses, and review evidence can be agreed before large
artifacts are produced. Use the private process in [SECURITY.md](SECURITY.md)
for vulnerabilities.

Do not contribute credentials, private filesystem paths, source PDFs,
unpublished manuscript text, personal data, raw scheduler logs, transient
checkpoints, or unreviewed scratch output. Large raw computations belong in the
private working repository; reviewed compact artifacts belong here.

## Development workflow

1. Fork the repository and create a focused branch.
2. Preserve deterministic ordering and dependency-free verifier operation on
   every supported Python version.
3. Add regression tests for every behavior change. Schema and verifier changes
   need malformed-input and trust-bypass tests as well as a happy path.
4. Run the local release checks:

   ```bash
   python3 scripts/verify_release.py --root .
   python3 -m unittest discover -s tests -v
   python3 -m compileall -q scripts tests
   ruff check scripts tests
   ruff format --check scripts tests
   mypy scripts tests
   ```

5. Open a pull request explaining the scientific or engineering purpose, the
   trust assumptions, tests performed, and any compatibility or migration
   impact.

Keep changes reviewable and avoid mixing generated data with unrelated code or
documentation edits. Pull requests must pass continuous integration and human
review before merge.

## Adding or changing release artifacts

A proposed artifact must be schema-valid and appear exactly once in the
manifest and checksum inventory. Its release report must identify:

- the generating repository and exact nonzero Git commit;
- commands, configuration, environment or container identity, and resource
  limits;
- generator, filters, shard boundaries, and counts for every terminal status;
- input, output, and receipt hashes;
- independent witness replay and other scientific review gates performed; and
- known limitations, timeouts, skips, or unresolved candidate negatives.

Use the dry-run-first promotion workflow in `total-coloring-toolkit`; do not
hand-copy partially reviewed runs into this repository. Published paths are
immutable. Corrections require a new dataset version and an explicit
supersession notice.

Result `producer.repository` and `producer.commit` must match the release
manifest. Record identifiers must be unique across result artifacts. A witness
requires a nonempty certificate; nonwitness statuses require a null certificate.

Large replay material may use manifest v2 instead of entering Git. External
artifact names and HTTPS URLs must be sorted and unique, and their byte length
and SHA-256 digest are immutable release metadata. Do not add an external file
to `SHA256SUMS` or the managed-root inventory. Bind it from the compact result
summary and test already-fetched bytes with `--external-file NAME=PATH`; the
normal verifier intentionally performs no download.

Use canonical release versions only: SemVer core and numeric prerelease
identifiers cannot have leading zeros, prerelease identifiers cannot be empty,
and this profile does not accept build metadata. `managed_roots` must remain the
exact JSON array `["reports", "results"]`. External URLs must use literal
lowercase `https://`, a lowercase DNS host, and a nonempty normalized path;
path components are restricted to literal RFC 3986 `pchar` characters. Percent
escapes, queries, fragments, user information, ports, double quotes, braces,
brackets, DEL/control characters, whitespace, backslashes, and non-ASCII text
are forbidden. The verifier independently trusts the public toolkit repository;
reuse with another trust anchor requires `--expected-code-repository URL`.

An already-downloaded universal replay archive is content-verified, not merely
hashed. It must contain exactly one level-9 gzip member through raw EOF, with
mtime zero, OS 255, the exact header `1f8b08000000000002ff`, and a valid CRC32
and ISIZE trailer. Raw suffixes (including zero suffixes), concatenated gzip
members, and in-gzip post-USTAR data are forbidden. The decompressed USTAR must
use receipt-derived deterministic headers, zero member padding, exactly two
zero end blocks followed only by zeros through the next 10240-byte boundary,
and the exact canonical decompressed length. It contains only the three
declared regular toolkit outputs per order. Metadata JSON members are at most
4 MiB; physical JSONL lines are at most 16 MiB including LF. Strict JSON
documents also obey the 16 MiB document, 128-level nesting, and 128-digit
integer limits. Paths, types, modes, ownership, timestamps, ordering, sizes,
hashes, canonical serialization, fingerprints, provenance, and conserved
counts are all release-contract data. Use the producer profile in
`docs/universal-census-release-v1.md`; do not create archives with a generic
recursive `tar` command.

Summary v1 must set `scope.require_high_degree` to `true` and contain exactly
one claim, with `claim_type: finite_bound`, status
`verified_in_finite_scope`, and orders exactly equal to every run order. Its
checks are exactly `dsatur-delta-plus-2`, `dsatur-delta-plus-3`, and
`static-delta-plus-2`. The publisher must derive, rather than accept caller
overrides for, the canonical finite-scope sentence and the exact two claim and
global limitations specified in the producer profile. Other claim types are
reserved and forbidden in v1. The external replay archive must retain the
manifests, completion markers, and record streams named and hashed by those
receipts.

## Schema changes

Schemas are versioned trust anchors. An incompatible representation change
requires a new schema version. Any accepted schema edit also requires:

- review of compatibility and migration behavior;
- an updated trusted digest in this verifier and in the toolkit publisher;
- positive and adversarial fixtures in both repositories; and
- a cross-repository contract test proving both sides accept and reject the
  same bundle.

A manifest cannot authorize a replacement schema merely by referring to it.

## Licensing and conduct

By contributing, you agree that data and documentation contributions are
provided under `CC-BY-4.0`, and code and test contributions under MIT, according
to the path-level declaration in [README.md](README.md). Confirm that you have
the right to submit all material and record third-party provenance where
needed.

Participation is governed by [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).
