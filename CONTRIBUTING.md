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
