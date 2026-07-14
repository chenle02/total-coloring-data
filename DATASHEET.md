# Datasheet: Total Coloring Data

## Status

- Dataset version: `0.1.0-dev`
- Active manifest schema: `1.0.0` (the empty development scaffold)
- Supported manifest schemas: `1.0.0`, `2.0.0`
- Scientific records: none released yet
- Maintainers: Le Chen and Songling Shan
- Last reviewed: 2026-07-14

This datasheet must be updated whenever a release changes the composition,
collection process, intended use, or known limitations of the dataset.

## Motivation

The dataset is intended to make finite searches and verification experiments
for total graph coloring inspectable and reproducible. It separates reviewed,
citable artifacts from private article drafts and transient high-performance
computing output.

The dataset is not intended to replace a mathematical proof. A finite search
can test a bounded statement, identify counterexamples, or verify a finite
case. Its scope must be stated in each release manifest and associated report.

## Composition

No scientific records are present in the development scaffold. Future releases
may contain:

- canonical encodings of finite simple graphs;
- total-coloring witness certificates;
- independently checkable solver proof artifacts;
- bounded-search summaries and complete status counts;
- audit reports describing hypotheses, pruning rules, and verification; and
- compact fixtures needed to reproduce published claims.

Raw scheduler logs, temporary checkpoints, credentials, personal information,
and unreviewed scratch output are excluded.

Manifest v2 permits a compact local result to bind a large replay archive held
outside Git. The external inventory records the archive's logical name, HTTPS
URL, media type, exact byte length, SHA-256 digest, and description. The
verifier does not download it; reviewers can supply already-fetched bytes for
offline verification with `--external-file NAME=PATH`.
External URLs use lowercase HTTPS, a lowercase DNS host, and nonempty literal
RFC 3986 path components. Percent escapes, queries, fragments, authority
decorations, double quotes, braces, brackets, DEL/control characters,
whitespace, backslashes, and non-ASCII text are rejected.

## Collection and computation

Every release must record the generating code repository and exact commit,
configuration, supported schema version, creation time in UTC, and artifact
hashes. Release timestamps use canonical second-precision UTC form ending in
`Z`, and release and producer commits must be nonzero full 40-hex Git object
IDs. Search reports should additionally record the graph generator and
version, solver backend and version, operating environment or container digest,
resource limits, shard identifiers, and counts for every terminal status.
By default the standalone verifier independently trusts
`https://github.com/chenle02/total-coloring-toolkit`. The manifest release and
every result or summary producer must name that exact repository; coordinated
substitution of both fields is rejected. Reuse with another trust anchor
requires the explicit `--expected-code-repository URL` option. Producer commits
must equal the release envelope. The producer version is descriptive package
metadata; it is not the dataset version and need not equal it.

Production solvers should emit positive witnesses. Negative claims require an
independently checked proof artifact when the backend supports one; otherwise
they must be labeled as candidate negative results rather than proved facts.

## Preprocessing and quality control

Promotion into this repository is review-gated and dry-run by default. The
standalone verifier checks the release integrity envelope for:

- schema conformance, canonical-content schema digest pins, and canonical path
  ordering;
- strict JSON without duplicate keys or `NaN`/infinite constants;
- cryptographic hash and byte-length agreement;
- path safety and absence of symlinks or hidden payloads;
- complete inventory of the managed directories;
- duplicate result record identifiers; and
- declared record counts and status/certificate/provenance consistency.

For `universal-census-summary-v1`, the envelope verifier additionally checks
that run status counts and aggregate totals are conserved, the configured check
matrix is deterministic and unique, generator calls and archive members are
present, `scope.require_high_degree` is `true`, producer provenance and the
release envelope match the independently trusted repository, and replay metadata
exactly matches a declared external artifact.

Summary v1 permits exactly one claim. It has `claim_type: finite_bound`, status
`verified_in_finite_scope`, and an order list equal to every run order. Orders
are integers from 1 through 16, and v1 is capped at 256 runs. Its
required checks are exactly `dsatur-delta-plus-2`,
`dsatur-delta-plus-3`, and `static-delta-plus-2`. Its finite scope is derived
canonically from the comma-space order list, not supplied by a caller:

```text
Only the complete unrestricted nauty-geng streams for the declared orders {orders}, filtered by 2*Delta(G) >= n, with every canonical equitable (Delta(G)+1)-class partition subjected to the three declared positive-witness checks.
```

The claim and the top-level summary must repeat exactly these limitations, in
order:

1. `The finite census is computational evidence and does not establish an unbounded theorem.`
2. `Generator completeness is assumed for the hash-pinned nauty-geng executable.`

Other claim types are reserved for future schemas and are not permitted in v1.
The three configured checks also have exact canonical descriptions identifying
finite replayable witness checks. A description that claims an unbounded
theorem invalidates the release even when its check ID, backend, and palette
offset are otherwise correct.

When reviewers supply the bound replay archive, the verifier also checks its
single-member deterministic gzip and USTAR metadata, exact normalized member
inventory, member sizes and digests, strict canonical JSON and JSONL,
recomputed toolkit run fingerprints, unsharded generator configuration,
completion/hash chains, and record-derived counts. The release profile permits
only unrestricted `geng` calls of the form `-q ORDER`. A finite-scope verified
claim must cover the required DSATUR and independent static checks, contain at
least one verified graph and partition, and have no candidate-negative,
unknown, or error outcome in its supporting runs.

The gzip member extends through raw EOF and has the exact header
`1f8b08000000000002ff` (level 9, mtime zero, OS 255) plus a valid CRC32 and
ISIZE trailer. No suffix, zero suffix, concatenated member, or in-gzip
post-USTAR data is accepted. USTAR headers are derived from member receipts;
member padding is zero; exactly two zero blocks terminate the archive, followed
only by zeros through the next 10240-byte boundary; and the decompressed length
is exact. Metadata JSON members are limited to 4 MiB, and JSONL physical lines
to 16 MiB including LF. Strict JSON documents are limited to 16 MiB, nesting
depth 128, and 128 decimal digits per integer literal.
Lone surrogate strings are rejected recursively. Checksum input is bounded and
must be valid UTF-8, and verifier diagnostics are capped fail-closed rather than
growing without limit on adversarial input.

The following are separate **scientific release-review gates**, not capabilities
of the standalone envelope verifier:

- duplicate graph-encoding detection under the release's stated identity rule;
- internal count conservation;
- deterministic replay of positive certificates; and
- agreement between independent implementations on bounded fixtures.

Each scientific gate must be run from the exact toolkit commit named in the
manifest. The release report must retain the command, configuration, input and
output hashes, terminal counts, and pass/fail receipt. A release is not
scientifically review-complete merely because the standalone verifier exits
successfully.

Machine-readable result artifacts currently use JSON and must declare the
trusted versioned result schema. A `witness` record requires a nonempty witness
certificate; `candidate_unsat`, `unknown`, and `error` records require a null
certificate. Negative proof evidence is published as a separately inventoried
certificate artifact and does not turn `candidate_unsat` into a theorem.

JSON whitespace and object-member order are not canonicalized. Artifact hashes
bind exact bytes; ordering requirements apply to manifest artifact paths and
checksum entries.

Any lossy sampling or filtering must be declared in the release report. A
sample must never be presented as a complete census.

## Intended uses

Appropriate uses include reproducing reported finite computations, testing new
solver implementations, comparing encodings, studying small examples, and
auditing claims in the associated research project.

Inappropriate uses include inferring an unbounded theorem solely from the
absence of bounded counterexamples, treating a candidate negative result as a
proof, or combining versions without respecting their schemas and provenance.

## Limitations and risks

Computational completeness depends on generator completeness, encoded
hypotheses, pruning-rule correctness, solver correctness, and complete shard
coverage. Hardware faults, timeouts, dependency drift, or a mislabeled search
domain can invalidate a conclusion even when individual output files parse.

The data concerns abstract finite graphs and is not expected to contain human
subjects or sensitive attributes. Operational logs are nevertheless excluded
because they may contain usernames, hostnames, email addresses, or private
paths.

## Distribution, licensing, and maintenance

Data and reports are distributed under `CC-BY-4.0`. Code is distributed under
the MIT license. Published releases should receive immutable Git tags and, for
paper-cited versions, a DOI. Corrections are issued as new releases; old
versions remain available with a supersession notice.

Questions and defect reports should be filed in the public issue tracker. A
report concerning an unreleased mathematical claim should be coordinated with
the article authors before disclosure.
