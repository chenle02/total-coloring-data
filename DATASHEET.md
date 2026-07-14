# Datasheet: Total Coloring Data

## Status

- Dataset version: `0.1.0-dev`
- Manifest schema: `1.0.0`
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

## Collection and computation

Every release must record the generating code repository and exact commit,
configuration, supported schema version, creation time in UTC, and artifact
hashes. Release timestamps use canonical second-precision UTC form ending in
`Z`, and release and producer commits must be nonzero full 40-hex Git object
IDs. Search reports should additionally record the graph generator and
version, solver backend and version, operating environment or container digest,
resource limits, shard identifiers, and counts for every terminal status.
Each result record's producer repository and commit must equal the release
envelope. The producer version is descriptive package metadata; it is not the
dataset version and need not equal it.

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
