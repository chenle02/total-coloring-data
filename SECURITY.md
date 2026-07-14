# Security policy

## Supported versions

Security fixes are applied to the latest tagged release and the default branch.
Published data artifacts remain immutable; when a defect affects their safety or
trustworthiness, the project publishes a corrected version and marks the earlier
release as superseded instead of rewriting it in place.

| Version | Security updates |
| --- | --- |
| Latest tagged release | Yes |
| Default branch | Yes, on a best-effort pre-release basis |
| Superseded releases | No; consult the supersession notice |

## Reporting a vulnerability

Please report vulnerabilities through a
[private GitHub security advisory](https://github.com/chenle02/total-coloring-data/security/advisories/new).
If that channel is unavailable, email `chenle02@gmail.com` with the subject
`[total-coloring-data security]`.

Include the affected version or commit, a minimal reproduction, expected and
observed behavior, impact, and any suggested mitigation. Do not include
credentials or sensitive operational data. Please avoid public disclosure until
the maintainers have assessed the report and coordinated a fix. We aim to
acknowledge reports within seven days and provide an initial assessment within
fourteen days, although research schedules may occasionally require longer.

Security-relevant examples include a verifier bypass, path traversal, symlink
escape, arbitrary code execution, unsafe archive handling, schema-trust or
hash-inventory bypass, and a compromised CI or release dependency.

## Integrity is not mathematical validity

The standalone verifier establishes the release integrity envelope: trusted
schemas, strict parsing, safe paths, complete inventory, hashes, declared record
counts, and selected cross-field invariants. Passing it does **not** establish
that a graph generator is complete, a certificate is mathematically valid, a
bounded census proves an unbounded theorem, or independent solver backends
agree.

An error in a graph, certificate, theorem statement, or experimental conclusion
is normally a scientific-correctness report rather than a security
vulnerability. Open a public issue for a released claim, or contact the research
authors privately if premature disclosure would expose an unreleased result. If
the error also enables an integrity check to be bypassed, use the private
security channel.

## Disclosure and credit

The maintainers will validate the report, determine affected releases, prepare
tests and a fix, and coordinate disclosure. With the reporter's consent, the
advisory or release notes will credit the report. Please do not test against
systems or data outside your authorization.
