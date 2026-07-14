# Total Coloring Data

Curated, machine-verifiable research artifacts produced by
[`total-coloring-toolkit`](https://github.com/chenle02/total-coloring-toolkit).
This repository is the public data layer for computational work on total
coloring; it is not a live mirror of cluster scratch space.

The repository is intentionally empty of scientific results at version
`0.1.0-dev`. Results will be added only after their theorem statement,
provenance, schema, and independent verification procedure are fixed.

## Integrity contract

Every released artifact must:

1. live under `results/` or `reports/`;
2. appear exactly once in `manifests/dataset-manifest.json`;
3. have its byte length and SHA-256 digest recorded in that manifest;
4. appear in `SHA256SUMS`; and
5. pass the dependency-free verifier and test suite.

Run the same checks used by continuous integration:

```bash
python3 scripts/verify_release.py --root .
python3 -m unittest discover -s tests -v
```

The verifier fails on untrusted or modified schemas, path traversal, symlinks,
hidden or unlisted managed artifacts, byte-count mismatches, digest mismatches,
duplicate paths, noncanonical ordering, inconsistent checksum files, and
status/certificate or producer/release provenance contradictions. JSON input is
strict: duplicate object keys and the nonstandard constants `NaN`, `Infinity`,
and `-Infinity` are rejected. Candidate and published releases must use
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

For result records, `producer.repository` and `producer.commit` must equal the
manifest's `release.code_repository` and `release.code_commit`. The producer
`version` is descriptive package metadata and is schema-validated, but it is
not required to equal the independently versioned dataset release.

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

## Versioning and immutability

Manifest and record schemas use semantic versions independently of the dataset
release. Published artifacts are immutable: corrections receive a new dataset
version and a documented supersession relationship. Filenames are never reused
for different bytes within a published version.

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
