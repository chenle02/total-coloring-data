# Total Coloring Data

Curated, machine-verifiable research artifacts produced by
[`total-coloring-toolkit`](https://github.com/chenle02/total-coloring-toolkit).
This repository is the public data layer for computational work on total
coloring; it is not a live mirror of cluster scratch space.

Version `0.1.0` publishes the finite universal auxiliary-extension census for
orders 1 through 8. The compact summary and human-readable audit report live in
Git; the complete 114,485,197-byte deterministic replay archive is attached to
the [GitHub release](https://github.com/chenle02/total-coloring-data/releases/tag/v0.1.0).
See the
[release report](reports/universal-census-orders-01-08-v1.md) for the exact
scope, counts, provenance, hashes, limitations, and public replay procedure.
This bounded computation is evidence, not an unbounded theorem.

## Integrity contract

Every repository-resident release artifact must:

1. live under `results/` or `reports/`;
2. appear exactly once in `manifests/dataset-manifest.json`;
3. have its byte length and SHA-256 digest recorded in that manifest;
4. appear in `SHA256SUMS`; and
5. pass the dependency-free verifier and test suite.

Manifest v1 remains supported for releases whose complete payload fits in the
Git repository. Manifest v2 adds a separate `external_artifacts` inventory for
large immutable replay archives. Each external entry binds a safe logical name,
HTTPS URL, media type, byte length, SHA-256 digest, and description. External
entries are deliberately excluded from the managed-root and `SHA256SUMS`
inventories: those two inventories continue to describe local files exactly.
Local paths, external names, and external URLs are ordered and unique, and a
local path cannot also be declared as an external name.

`managed_roots` is operational only when it is the exact JSON array
`["reports", "results"]`; invalid values are never traversed. External URLs use
a deliberately narrow canonical profile: literal lowercase `https://`, a
lowercase DNS hostname with no user information or port, a nonempty normalized
path, and no query, fragment, backslash, whitespace, non-ASCII character, DEL,
control character, or percent escape. Each literal path component uses only
RFC 3986 `pchar` characters: ASCII letters and digits, `-._~`, `!$&'()*+,;=`,
`:`, and `@`. Thus double quotes, braces, brackets, backticks, carets, and pipes
are rejected; apostrophe is retained as an RFC 3986 sub-delimiter.

Run the same checks used by continuous integration:

```bash
python3 scripts/verify_release.py --root .
python3 -m unittest discover -s tests -v
```

Normal verification never accesses the network. If a replay archive has
already been downloaded, verify its exact bytes against the manifest with:

```bash
python3 scripts/verify_release.py --root . \
  --external-file \
  archives/universal-census-orders-01-08-v1.tar.gz=/path/to/universal-census-orders-01-08-v1.tar.gz
```

`--external-file NAME=PATH` is repeatable. Supplied names must be declared,
unique, and safe; supplied paths must be regular non-symlink files. Omitting the
option validates the external metadata and its summary binding without claiming
that the remote bytes were fetched or checked.

The standalone verifier trusts
`https://github.com/chenle02/total-coloring-toolkit` as the generating code
repository by default. Both `release.code_repository` and result/summary
producer provenance must equal that independently configured value, so a
manifest cannot authorize a coordinated repository substitution. Reusers must
select another trusted repository explicitly with
`--expected-code-repository URL`; no manifest field or environment variable can
change the default trust anchor.

For a universal-census replay archive, supplying the file performs more than a
top-level hash check. The verifier requires exactly one level-9 gzip member
through raw-file EOF, with mtime zero, exact header
`1f8b08000000000002ff`, OS 255, and valid CRC32 and ISIZE. Raw suffix bytes
(including zeros), concatenated members, and in-gzip post-USTAR data are
rejected. It requires receipt-derived canonical USTAR headers, zero member
padding, exactly two zero end blocks followed by zeros only through the next
10240-byte boundary, and the exact decompressed length. It then strictly parses
every embedded manifest, completion marker, and JSONL record and recomputes run
fingerprints, checking the complete
completion-to-manifest-to-record hash, provenance, status-count, partition, and
configured-check chain. It does not execute `geng` or independently replay the
graph-coloring witnesses; those remain scientific checks in the pinned toolkit.

The verifier fails on untrusted or modified schemas, path traversal, symlinks,
hidden or unlisted managed artifacts, byte-count mismatches, digest mismatches,
duplicate paths, noncanonical ordering, inconsistent checksum files, and
status/certificate or producer/release provenance contradictions. For bounded
universal-census summaries it also checks producer provenance, configured-check
uniqueness, per-run and aggregate count conservation, exact replay-archive
metadata binding, archive-member identity, and finite-scope claim ordering and
limitations. JSON input is
strict: duplicate object keys and the nonstandard constants `NaN`, `Infinity`,
and `-Infinity` are rejected. JSON documents are limited to 16 MiB, nesting to
128 levels, and integer literals to 128 decimal digits; lone UTF-16 surrogates
are rejected recursively. `SHA256SUMS` must be valid UTF-8, is limited to 4 MiB,
and has a 4096-byte physical-line limit including LF. Archive metadata JSON
members are limited to 4 MiB before extraction or hashing, and each physical
JSONL record line is limited to 16 MiB including LF. Candidate and published
releases must use
canonical UTC timestamps ending in `Z`, identify a nonzero generating Git
commit, and contain no `.gitkeep` placeholders.

The standalone verifier checks the **release integrity envelope**: trusted
schemas, strict parsing, paths, inventory, hashes, declared record counts,
unique result record IDs, and the cross-field rules above. It does not
reconstruct graph instances, replay total-coloring certificates, prove shard
count conservation, or establish agreement between solver backends. Those are
separate scientific release-review gates performed by the pinned toolkit
commit; their commands, inputs, outputs, and hashes must be retained as receipts
in the release report before publication.

JSON object-member order and whitespace are not prescribed. SHA-256 binds the
exact published bytes; "canonical ordering" here refers to manifest artifact
paths and checksum entries, not a canonical JSON byte serialization.

The verifier contains SHA-256 pins for the canonical JSON content of every
schema it trusts. Formatting and object-member order do not affect a schema
pin; any semantic content change does. Updating a schema is therefore a
deliberate verifier release: review the schema change, update its pinned digest
in `scripts/verify_release.py`, and add a regression test. A dataset checkout
cannot authorize a weakened replacement schema merely by pointing its manifest
at that file.

For result records, `producer.repository` and the manifest's
`release.code_repository` must both equal the verifier's independently trusted
expected repository. `producer.commit` must equal `release.code_commit`. The
producer `version` is descriptive package metadata and is schema-validated,
but it is not required to equal the independently versioned dataset release.

## Layout

```text
results/     immutable machine-readable scientific results
reports/     human-readable or machine-readable audit reports
manifests/   release inventory and provenance
schemas/     versioned JSON schemas
scripts/     standalone standard-library verification
tests/       verifier regression tests
```

Large immutable artifacts should be attached to a GitHub Release and archived
with a DOI-bearing research repository such as Zenodo. The Git repository
should retain their manifest, checksums, schema, and a compact verification
fixture rather than accumulating raw compute shards.

The trusted `universal-census-summary-v1` representation is intentionally
finite-scope. It records the exact code commit and source digest, generator
executable digest and invocations, configured backend checks, per-order run
receipts, conserved totals, claim IDs with explicitly bounded statuses, and
limitations. A `verified_in_finite_scope` status is never an unbounded result;
scientific replay remains a separate gate performed by the pinned toolkit.

Summary v1 has exactly one claim: `claim_type: finite_bound` and
`status: verified_in_finite_scope`. The claim orders must be exactly every run
order; orders are integers from 1 through 16 and a summary contains at most 256
runs.
`scope.require_high_degree` must be `true`, and the configured checks are
exactly `dsatur-delta-plus-2`, `dsatur-delta-plus-3`, and
`static-delta-plus-2`. Other claim types are reserved and are not permitted in
v1. The publisher derives the canonical finite-scope sentence and exact
limitations from the completed runs; callers cannot override either. The
required language is specified in
[`docs/universal-census-release-v1.md`](docs/universal-census-release-v1.md).
Each check's backend, palette offset, and finite replayable-witness description
are also exact contract fields; descriptions suggesting an unbounded theorem
are rejected.

The v1 universal release profile is deliberately unsharded. Each order has one
run with generator arguments exactly `-q ORDER`, shard index zero and shard
count one. Its archive contains exactly these members, with no directory
entries: `order-NN/manifest.json`, `order-NN/completion.json`, and
`order-NN/records.jsonl`. See
[`docs/universal-census-release-v1.md`](docs/universal-census-release-v1.md) for
the complete producer contract.

## Versioning and immutability

Manifest and record schemas use semantic versions independently of the dataset
release. Published artifacts are immutable: corrections receive a new dataset
version and a documented supersession relationship. Filenames are never reused
for different bytes within a published version. Dataset release versions use
canonical SemVer core and prerelease syntax: core and numeric prerelease
identifiers have no leading zeros, prerelease identifiers are nonempty, and
build metadata is not accepted by this release profile.

## Citation and licenses

Citation metadata is in `CITATION.cff`; collection details and limitations are
in `DATASHEET.md`.

Contributions are described in `CONTRIBUTING.md`. Report security issues through
the private process in `SECURITY.md`; community participation is governed by
`CODE_OF_CONDUCT.md`.

The following table is the authoritative path-level license declaration for
this repository. A more specific license notice inside a future artifact takes
precedence and must also be recorded in its release report.

| Paths | License |
| --- | --- |
| `results/**`, `reports/**` | Creative Commons Attribution 4.0 International (`CC-BY-4.0`) |
| `manifests/**`, `schemas/**`, `SHA256SUMS` | `CC-BY-4.0` |
| `README.md`, `DATASHEET.md`, `CITATION.cff`, `CONTRIBUTING.md`, `SECURITY.md`, `CODE_OF_CONDUCT.md` | `CC-BY-4.0` |
| `scripts/**`, `tests/**`, `.github/**`, `.gitignore` | MIT |
| `LICENSE` | CC BY 4.0 license notice and authoritative legal-code link |
| `LICENSE-CODE` | MIT license text |

The development-only `.gitkeep` placeholders contain no substantive work and
are removed from candidate and published releases.
