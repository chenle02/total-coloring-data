# Universal Census Release Profile v1

This profile is the exact producer/verifier interface for a compact bounded
universal-census result and its external replay archive. It is intentionally a
finite-computation contract, not an unbounded mathematical statement.

The standalone verifier independently trusts
`https://github.com/chenle02/total-coloring-toolkit` unless a reuser explicitly
passes `--expected-code-repository URL`. Both the manifest release and summary
producer must equal this value. Learning the expected repository from either
release field would permit a coordinated provenance substitution and is
forbidden.

## Completed run inputs

There is exactly one completed toolkit run for each declared positive order,
with at most 256 runs in one v1 summary. Every run
must have the same toolkit source identity, generator executable identity,
check matrix, filter, search limits, and checkpoint interval. Version 1 is
explicitly unsharded:

- `generator_spec.connected` is `false`;
- `min_degree`, `max_degree`, `shard_index`, and `shard_count` are `null`;
- public shard identity is `{"count": 1, "index": 0}`; and
- generator arguments are exactly `["-q", "ORDER"]`.

The required check matrix is ordered as follows:

1. `dsatur-iterative-v1`, palette offset 1
2. `dsatur-iterative-v1`, palette offset 2
3. `static-order-iterative-v1`, palette offset 1

The corresponding summary IDs are `dsatur-delta-plus-2`,
`dsatur-delta-plus-3`, and `static-delta-plus-2`.

The compact summary must set `scope.require_high_degree` to `true`. Thus the
declared graph stream is filtered by `2*Delta(G) >= n`; this is part of the
finite scope, not a caller-selectable release option.

## Replay archive

The archive is exactly one gzip member extending through raw-file EOF. It is
created with compression level 9 and mtime zero, and its complete ten-byte
header is exactly `1f8b08000000000002ff` (XFL 2, OS 255, and no optional
fields). The trailer must contain the valid CRC32 and ISIZE for the one
decompressed stream. Any raw suffix, including zero bytes, any concatenated
gzip member, a missing or malformed trailer, or any post-stream data is
forbidden.

The decompressed stream is deterministic USTAR. Members are lexicographically
ordered and have:

- only USTAR regular-file types;
- mode `0644`;
- uid, gid, and mtime zero;
- empty user, group, and link names;
- no pax or sparse metadata; and
- no directory entries.

Each 512-byte USTAR header must be the receipt-derived canonical header for
the member path and declared size. File padding through the next 512-byte
boundary is all zero. After the last member there are exactly two zero blocks,
followed only by zero bytes through the next 10240-byte record boundary. The
decompressed length must equal that canonical layout exactly; GNU tar and
other tar dialects are not accepted.

For each order, the exact members are:

```text
order-NN/completion.json
order-NN/manifest.json
order-NN/records.jsonl
```

`NN` is decimal order padded to at least two digits. No other member is
permitted. The summary binds every member path, byte length, and SHA-256 digest,
then binds the complete archive's logical name, HTTPS URL, media type, byte
length, and SHA-256 digest.

The URL grammar is deliberately narrower than a generic URI: literal lowercase
`https://`, a lowercase DNS host without user information or port, and one or
more nonempty literal RFC 3986 path components. Percent escapes, query and
fragment delimiters, double quotes, braces, brackets, DEL/C0 controls,
whitespace, backslash, and non-ASCII text are forbidden. The permitted path
component alphabet is ASCII alphanumeric plus `-._~!$&'()*+,;=:@`; apostrophe
is an RFC 3986 sub-delimiter.

Each embedded `manifest.json` and `completion.json` member is limited to 4 MiB
before extraction or hashing. Each physical line in `records.jsonl` is limited
to 16 MiB including its terminating LF. Strict JSON parsing applies throughout:
a JSON document is at most 16 MiB, nesting depth is at most 128, and an integer
literal is at most 128 decimal digits. Duplicate object keys, nonstandard
numeric constants, malformed UTF-8, and invalid JSON are rejected.
Lone UTF-16 surrogate code points are rejected recursively, including in JSON
object keys.

## Compact summary and claims

The summary separately records the public toolkit Git repository and full
commit. The embedded toolkit descriptors bind distribution version, package
source digest, Python identity, generator executable digest and arguments,
configuration, and shard identity. The verifier reconstructs each descriptor
from the summary and recomputes its run fingerprint.

Version 1 requires exactly one claim. Its `claim_type` is `finite_bound`, its
status is `verified_in_finite_scope`, and its order list is exactly the complete
ordered set of run orders in the summary. Its required-check list is exactly
`dsatur-delta-plus-2`, `dsatur-delta-plus-3`, and
`static-delta-plus-2`. Its finite scope is derived from the run orders and must
equal the following string, with `{orders}` replaced by their comma-space list:

```text
Only the complete unrestricted nauty-geng streams for the declared orders {orders}, filtered by 2*Delta(G) >= n, with every canonical equitable (Delta(G)+1)-class partition subjected to the three declared positive-witness checks.
```

Both the claim and the summary-level `limitations` array must contain exactly
these two strings in this order:

1. `The finite census is computational evidence and does not establish an unbounded theorem.`
2. `Generator completeness is assumed for the hash-pinned nauty-geng executable.`

The claim must also:

- have positive verified-graph, partition, and check-evaluation counts; and
- have zero `candidate_unsat`, `unknown`, and `error` counts across all named
  orders.

Embedded record, order, and partition indices and check palette/color counts
are exact nonboolean integers. Every check must satisfy
`color_count = degree_parameter + palette_offset`, and its backend/offset pair
must exactly match the declared check matrix. Duplicate graph detection remains
a separate scientific gate so archive verification can stream with bounded
memory.

Other claim types are reserved for a future schema and are not permitted in a
version 1 summary.

## Minimal toolkit publisher interface

The toolkit-side publisher needs only one release-preparation operation:

```text
prepare_universal_release(
    completed_run_directories,
    summary_output_path,
    archive_output_path,
    code_repository,
    code_commit,
    summary_id,
    created_utc,
    external_artifact_name,
    external_artifact_url,
    claim_id,
) -> {summary_path, archive_path, archive_bytes, archive_sha256}
```

All scientific configuration, counts, member receipts, generator identity,
source identity, run fingerprints, claim order scope, `finite_scope`, and both
limitations arrays must be derived from and cross-checked against the completed
directories rather than accepted as caller overrides. In particular, the
publisher interface must not accept `finite_scope` or `limitations` parameters.
The operation must reject incomplete, mixed-configuration, sharded, restricted,
or adverse-status inputs before writing final outputs. It should write both
outputs atomically and expose a dry-run plan to the existing public-data
promotion layer. The data repository remains responsible for registering the
summary as a local result, registering the archive as an external artifact,
updating `SHA256SUMS`, and running this standalone verifier.
