from __future__ import annotations

import gzip
import hashlib
import io
import json
import os
import shutil
import tarfile
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

from scripts.verify_release import (
    VerificationIssue,
    _canonical_json_bytes,
    _finite_scope_for_orders,
    _format_matches,
    _load_json,
    _validate_instance,
    verify_repository,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
CODE_REPOSITORY = "https://github.com/chenle02/total-coloring-toolkit"
CODE_COMMIT = "61c576fba28a03a91f6a7695e21d130cd7e76f22"
EXTERNAL_NAME = "archives/order-2-replay.tar.gz"
EXTERNAL_URL = (
    "https://github.com/chenle02/total-coloring-data/releases/download/"
    "v1.0.0-rc.1/order-2-replay.tar.gz"
)
FIXTURE_ROOT = REPOSITORY_ROOT / "tests/fixtures/toolkit-universal-order-02"


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _gzip_bytes(payload: bytes, *, compresslevel: int = 9) -> bytes:
    result = io.BytesIO()
    with gzip.GzipFile(
        filename="",
        mode="wb",
        fileobj=result,
        mtime=0,
        compresslevel=compresslevel,
    ) as compressed:
        compressed.write(payload)
    return result.getvalue()


def _archive_payloads() -> dict[str, bytes]:
    return {
        f"order-02/{name}": (FIXTURE_ROOT / name).read_bytes()
        for name in ("completion.json", "manifest.json", "records.jsonl")
    }


def _write_archive(
    path: Path,
    payloads: dict[str, bytes],
    *,
    member_type: bytes = tarfile.REGTYPE,
    duplicate_name: str | None = None,
    metadata_mtime: int = 0,
    gzip_mtime: int = 0,
    compresslevel: int = 9,
    sort_members: bool = True,
    tar_format: int = tarfile.USTAR_FORMAT,
) -> None:
    with path.open("wb") as raw_stream:
        with gzip.GzipFile(
            filename="",
            mode="wb",
            fileobj=raw_stream,
            mtime=gzip_mtime,
            compresslevel=compresslevel,
        ) as compressed:
            with tarfile.open(
                fileobj=compressed, mode="w", format=tar_format
            ) as archive:
                names = (
                    sorted(payloads)
                    if sort_members
                    else list(reversed(sorted(payloads)))
                )
                if duplicate_name is not None:
                    names.append(duplicate_name)
                for name in names:
                    payload = payloads[name]
                    member = tarfile.TarInfo(name)
                    member.size = len(payload)
                    member.mode = 0o644
                    member.uid = 0
                    member.gid = 0
                    member.uname = ""
                    member.gname = ""
                    member.mtime = metadata_mtime
                    member.type = member_type
                    archive.addfile(member, io.BytesIO(payload))


def _summary(external: Path) -> dict[str, object]:
    manifest = json.loads((FIXTURE_ROOT / "manifest.json").read_text(encoding="utf-8"))
    provenance = manifest["provenance"]
    config = provenance["config"]
    toolkit = provenance["toolkit"]
    generator = provenance["generator"]
    counts = manifest["counts"]
    checks = [
        {
            "check_id": "dsatur-delta-plus-2",
            "backend_id": "dsatur-iterative-v1",
            "palette_offset": 1,
            "description": "Replayable DSATUR witness check with Delta(G)+2 colors for every canonical equitable partition.",
        },
        {
            "check_id": "dsatur-delta-plus-3",
            "backend_id": "dsatur-iterative-v1",
            "palette_offset": 2,
            "description": "Replayable DSATUR witness check with Delta(G)+3 colors for every canonical equitable partition.",
        },
        {
            "check_id": "static-delta-plus-2",
            "backend_id": "static-order-iterative-v1",
            "palette_offset": 1,
            "description": "Replayable static-order witness check with Delta(G)+2 colors for every canonical equitable partition.",
        },
    ]
    members = {
        kind.removesuffix(".json").removesuffix(".jsonl"): {
            "path": f"order-02/{kind}",
            "bytes": (FIXTURE_ROOT / kind).stat().st_size,
            "sha256": _sha256(FIXTURE_ROOT / kind),
        }
        for kind in ("manifest.json", "completion.json", "records.jsonl")
    }
    return {
        "$schema": "schemas/universal-census-summary-v1.schema.json",
        "schema_version": "total-coloring.universal-census-summary.v1",
        "summary_id": "order-2-universal-census",
        "created_utc": "2026-07-14T12:00:00Z",
        "producer": {
            "repository": CODE_REPOSITORY,
            "commit": CODE_COMMIT,
            "distribution_version": toolkit["distribution_version"],
            "source_sha256": toolkit["source_sha256"],
            "python_implementation": toolkit["python_implementation"],
            "python_version": toolkit["python_version"],
        },
        "generator": {
            "name": generator["name"],
            "executable": generator["executable"],
            "sha256": generator["sha256"],
        },
        "scope": {
            "objective": provenance["objective"],
            "graph_family": "finite_simple_unlabeled_graphs",
            "connected": config["generator_spec"]["connected"],
            "min_degree": config["generator_spec"]["min_degree"],
            "max_degree": config["generator_spec"]["max_degree"],
            "require_high_degree": config["filters"]["require_high_degree"],
            "partition_enumerator": config["partition_enumerator"],
            "fix_distinguished_colors": config["fix_distinguished_colors"],
        },
        "configuration": {
            "checkpoint_interval": config["checkpoint_interval"],
            "search_limits": config["search_limits"],
        },
        "checks": checks,
        "runs": [
            {
                "order": 2,
                "run_fingerprint": manifest["run_fingerprint"],
                "generator_arguments": generator["arguments"],
                "shard_index": provenance["shard"]["index"],
                "shard_count": provenance["shard"]["count"],
                "record_count": manifest["record_count"],
                "partition_count": manifest["partition_count"],
                "check_evaluations": manifest["partition_count"] * len(checks),
                "counts": counts,
                "members": members,
            }
        ],
        "totals": {
            "order_count": 1,
            "record_count": manifest["record_count"],
            "partition_count": manifest["partition_count"],
            "check_evaluations": manifest["partition_count"] * len(checks),
            "counts": counts,
        },
        "claims": [
            {
                "claim_id": "U2-BOUND",
                "claim_type": "finite_bound",
                "status": "verified_in_finite_scope",
                "finite_scope": (
                    "Only the complete unrestricted nauty-geng streams for the "
                    "declared orders 2, filtered by 2*Delta(G) >= n, with every "
                    "canonical equitable (Delta(G)+1)-class partition subjected "
                    "to the three declared positive-witness checks."
                ),
                "orders": [2],
                "required_checks": [
                    "dsatur-delta-plus-2",
                    "dsatur-delta-plus-3",
                    "static-delta-plus-2",
                ],
                "limitations": [
                    "The finite census is computational evidence and does not "
                    "establish an unbounded theorem.",
                    "Generator completeness is assumed for the hash-pinned "
                    "nauty-geng executable.",
                ],
            }
        ],
        "limitations": [
            "The finite census is computational evidence and does not establish "
            "an unbounded theorem.",
            "Generator completeness is assumed for the hash-pinned nauty-geng "
            "executable.",
        ],
        "replay_archive": {
            "external_artifact": EXTERNAL_NAME,
            "url": EXTERNAL_URL,
            "media_type": "application/gzip",
            "bytes": external.stat().st_size,
            "sha256": _sha256(external),
        },
    }


def _refresh_local_integrity(root: Path) -> None:
    summary_path = root / "results/universal-summary.json"
    manifest_path = root / "manifests/dataset-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["artifacts"][0]["bytes"] = summary_path.stat().st_size
    manifest["artifacts"][0]["sha256"] = _sha256(summary_path)
    _write_json(manifest_path, manifest)
    (root / "SHA256SUMS").write_text(
        f"{_sha256(summary_path)}  results/universal-summary.json\n",
        encoding="utf-8",
    )


def _replace_external_archive(
    root: Path,
    payloads: dict[str, bytes],
    *,
    sync_member_integrity: bool = True,
    **archive_options: Any,
) -> Path:
    external = root / "external/order-2-replay.tar.gz"
    _write_archive(external, payloads, **archive_options)
    summary_path = root / "results/universal-summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    if sync_member_integrity:
        for descriptor in summary["runs"][0]["members"].values():
            path = descriptor["path"]
            if path in payloads:
                descriptor["bytes"] = len(payloads[path])
                descriptor["sha256"] = hashlib.sha256(payloads[path]).hexdigest()
    _write_json(summary_path, summary)
    _bind_external_archive(root, external)
    return external


def _bind_external_archive(root: Path, external: Path) -> None:
    summary_path = root / "results/universal-summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary["replay_archive"]["bytes"] = external.stat().st_size
    summary["replay_archive"]["sha256"] = _sha256(external)
    _write_json(summary_path, summary)

    manifest_path = root / "manifests/dataset-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["external_artifacts"][0]["bytes"] = external.stat().st_size
    manifest["external_artifacts"][0]["sha256"] = _sha256(external)
    _write_json(manifest_path, manifest)
    _refresh_local_integrity(root)


def _mutate_embedded_json(
    root: Path, member_name: str, mutate: Any
) -> tuple[Path, dict[str, bytes]]:
    payloads = _archive_payloads()
    document = json.loads(payloads[member_name].decode("utf-8"))
    mutate(document)
    payloads[member_name] = (
        json.dumps(document, allow_nan=False, separators=(",", ":"), sort_keys=True)
        + "\n"
    ).encode("utf-8")
    return _replace_external_archive(root, payloads), payloads


def _replace_records_with_recomputed_chain(
    root: Path, records: list[dict[str, Any]]
) -> Path:
    payloads = _archive_payloads()
    records_payload = b"".join(
        json.dumps(
            record,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        + b"\n"
        for record in records
    )
    records_sha256 = hashlib.sha256(records_payload).hexdigest()
    payloads["order-02/records.jsonl"] = records_payload

    manifest = json.loads(payloads["order-02/manifest.json"])
    manifest["artifacts"]["records_bytes"] = len(records_payload)
    manifest["artifacts"]["records_sha256"] = records_sha256
    manifest_payload = _canonical_json_bytes(manifest) + b"\n"
    payloads["order-02/manifest.json"] = manifest_payload

    completion = json.loads(payloads["order-02/completion.json"])
    completion["manifest_sha256"] = hashlib.sha256(manifest_payload).hexdigest()
    completion["records_sha256"] = records_sha256
    payloads["order-02/completion.json"] = _canonical_json_bytes(completion) + b"\n"
    return _replace_external_archive(root, payloads)


def _make_v2_release(root: Path) -> tuple[Path, Path]:
    for directory in ("results", "reports", "manifests", "schemas", "external"):
        (root / directory).mkdir(parents=True)
    for schema_name in (
        "dataset-manifest-v2.schema.json",
        "universal-census-summary-v1.schema.json",
    ):
        shutil.copy2(
            REPOSITORY_ROOT / "schemas" / schema_name,
            root / "schemas" / schema_name,
        )

    external = root / "external/order-2-replay.tar.gz"
    _write_archive(external, _archive_payloads())
    summary_path = root / "results/universal-summary.json"
    _write_json(summary_path, _summary(external))
    manifest = {
        "$schema": "schemas/dataset-manifest-v2.schema.json",
        "schema_version": "2.0.0",
        "dataset": {
            "id": "total-coloring-data",
            "title": "Total Coloring Data",
            "license": "CC-BY-4.0",
            "repository": "https://github.com/chenle02/total-coloring-data",
        },
        "release": {
            "version": "1.0.0-rc.1",
            "status": "candidate",
            "created_utc": "2026-07-14T12:00:00Z",
            "code_repository": CODE_REPOSITORY,
            "code_commit": CODE_COMMIT,
        },
        "managed_roots": ["reports", "results"],
        "artifacts": [
            {
                "path": "results/universal-summary.json",
                "role": "result",
                "media_type": "application/json",
                "bytes": summary_path.stat().st_size,
                "sha256": _sha256(summary_path),
                "schema": "schemas/universal-census-summary-v1.schema.json",
                "records": 1,
                "description": "Finite-scope universal census summary fixture.",
            }
        ],
        "external_artifacts": [
            {
                "name": EXTERNAL_NAME,
                "url": EXTERNAL_URL,
                "media_type": "application/gzip",
                "bytes": external.stat().st_size,
                "sha256": _sha256(external),
                "description": "Replayable run transcript fixture.",
            }
        ],
    }
    _write_json(root / "manifests/dataset-manifest.json", manifest)
    (root / "SHA256SUMS").write_text(
        f"{_sha256(summary_path)}  results/universal-summary.json\n",
        encoding="utf-8",
    )
    return root, external


class V2ReleaseVerifierTests(unittest.TestCase):
    def test_v2_release_verifies_without_downloading_external_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root, _ = _make_v2_release(Path(temporary))
            report = verify_repository(root)
        self.assertTrue(report.ok, report.issues)
        self.assertEqual(report.artifact_count, 1)
        self.assertEqual(report.external_artifact_count, 1)
        self.assertEqual(report.external_files_verified, 0)

    def test_supplied_external_artifact_verifies_offline(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root, external = _make_v2_release(Path(temporary))
            report = verify_repository(root, external_files=[(EXTERNAL_NAME, external)])
        self.assertTrue(report.ok, report.issues)
        self.assertEqual(report.external_files_verified, 1)

    def test_supplied_external_tamper_and_missing_file_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root, external = _make_v2_release(Path(temporary))
            external.write_bytes(b"deterministic replay archive fixturf\n")
            tamper_report = verify_repository(
                root, external_files=[(EXTERNAL_NAME, external)]
            )
            missing_report = verify_repository(
                root,
                external_files=[(EXTERNAL_NAME, root / "external/missing.tar.gz")],
            )
        self.assertIn(
            "external-file-hash", {issue.code for issue in tamper_report.issues}
        )
        self.assertIn(
            "external-file-missing", {issue.code for issue in missing_report.issues}
        )

    def test_supplied_external_names_are_unique_safe_and_declared(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root, external = _make_v2_release(Path(temporary))
            duplicate = verify_repository(
                root,
                external_files=[
                    (EXTERNAL_NAME, external),
                    (EXTERNAL_NAME, external),
                ],
            )
            unsafe = verify_repository(
                root, external_files=[("../replay.tar.gz", external)]
            )
            undeclared = verify_repository(
                root, external_files=[("archives/other.tar.gz", external)]
            )
        self.assertIn(
            "external-file-duplicate", {issue.code for issue in duplicate.issues}
        )
        self.assertIn("external-file-name", {issue.code for issue in unsafe.issues})
        self.assertIn(
            "external-file-undeclared", {issue.code for issue in undeclared.issues}
        )

    @unittest.skipUnless(hasattr(os, "symlink"), "symlinks unavailable")
    def test_supplied_external_rejects_symlinked_path_component(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root, external = _make_v2_release(Path(temporary))
            linked_directory = root / "linked-external"
            linked_directory.symlink_to(external.parent, target_is_directory=True)
            report = verify_repository(
                root,
                external_files=[(EXTERNAL_NAME, linked_directory / external.name)],
            )
        self.assertIn("external-file-symlink", {issue.code for issue in report.issues})

    def test_replay_archive_rejects_traversal_unexpected_and_missing_members(
        self,
    ) -> None:
        cases = (
            (
                "traversal",
                lambda payloads: payloads.__setitem__("../escape.json", b"{}\n"),
                "archive-ustar-layout",
            ),
            (
                "unexpected",
                lambda payloads: payloads.__setitem__(
                    "order-02/unexpected.json", b"{}\n"
                ),
                "archive-ustar-layout",
            ),
            (
                "missing",
                lambda payloads: payloads.pop("order-02/completion.json"),
                "archive-ustar-layout",
            ),
        )
        for label, mutate, expected_code in cases:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as temporary:
                root, _ = _make_v2_release(Path(temporary))
                payloads = _archive_payloads()
                mutate(payloads)
                external = _replace_external_archive(root, payloads)
                report = verify_repository(
                    root, external_files=[(EXTERNAL_NAME, external)]
                )
            self.assertIn(expected_code, {issue.code for issue in report.issues})

    def test_replay_archive_rejects_duplicate_and_nonregular_members(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root, _ = _make_v2_release(Path(temporary))
            external = _replace_external_archive(
                root,
                _archive_payloads(),
                duplicate_name="order-02/records.jsonl",
            )
            duplicate_report = verify_repository(
                root, external_files=[(EXTERNAL_NAME, external)]
            )
        self.assertIn(
            "archive-ustar-layout",
            {issue.code for issue in duplicate_report.issues},
        )

        for member_type in (tarfile.SYMTYPE, tarfile.LNKTYPE, tarfile.CHRTYPE):
            with (
                self.subTest(member_type=member_type),
                tempfile.TemporaryDirectory() as temporary,
            ):
                root, _ = _make_v2_release(Path(temporary))
                external = _replace_external_archive(
                    root, _archive_payloads(), member_type=member_type
                )
                report = verify_repository(
                    root, external_files=[(EXTERNAL_NAME, external)]
                )
            self.assertIn(
                "archive-ustar-layout", {issue.code for issue in report.issues}
            )

    def test_replay_archive_rejects_nondeterministic_metadata_and_order(self) -> None:
        cases = (
            ("member-mtime", {"metadata_mtime": 1}, "archive-ustar-layout"),
            ("gzip-mtime", {"gzip_mtime": 1}, "archive-gzip-header"),
            ("member-order", {"sort_members": False}, "archive-ustar-layout"),
        )
        for label, options, expected_code in cases:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as temporary:
                root, _ = _make_v2_release(Path(temporary))
                external = _replace_external_archive(
                    root, _archive_payloads(), **options
                )
                report = verify_repository(
                    root, external_files=[(EXTERNAL_NAME, external)]
                )
            self.assertIn(expected_code, {issue.code for issue in report.issues})

    def test_replay_archive_checks_each_declared_member_size_and_hash(self) -> None:
        for label, payload, expected_code in (
            ("same-size-tamper", b"X" * 2227, "archive-member-hash"),
            ("size-tamper", b"X" * 2228, "archive-ustar-layout"),
        ):
            with self.subTest(label=label), tempfile.TemporaryDirectory() as temporary:
                root, _ = _make_v2_release(Path(temporary))
                payloads = _archive_payloads()
                payloads["order-02/records.jsonl"] = payload
                external = _replace_external_archive(
                    root, payloads, sync_member_integrity=False
                )
                report = verify_repository(
                    root, external_files=[(EXTERNAL_NAME, external)]
                )
            self.assertIn(expected_code, {issue.code for issue in report.issues})

    def test_embedded_schema_versions_are_strictly_bound(self) -> None:
        cases = (
            (
                "manifest",
                "order-02/manifest.json",
                lambda value: value.__setitem__("schema_version", "wrong"),
                "archive-manifest-version",
            ),
            (
                "completion",
                "order-02/completion.json",
                lambda value: value.__setitem__("schema_version", "wrong"),
                "archive-completion-version",
            ),
        )
        for label, member_name, mutate, expected_code in cases:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as temporary:
                root, _ = _make_v2_release(Path(temporary))
                external, _ = _mutate_embedded_json(root, member_name, mutate)
                report = verify_repository(
                    root, external_files=[(EXTERNAL_NAME, external)]
                )
            self.assertIn(expected_code, {issue.code for issue in report.issues})

        with tempfile.TemporaryDirectory() as temporary:
            root, _ = _make_v2_release(Path(temporary))
            payloads = _archive_payloads()
            lines = payloads["order-02/records.jsonl"].decode("utf-8").splitlines()
            record = json.loads(lines[0])
            record["schema_version"] = "wrong"
            lines[0] = json.dumps(record, separators=(",", ":"), sort_keys=True)
            payloads["order-02/records.jsonl"] = ("\n".join(lines) + "\n").encode()
            external = _replace_external_archive(root, payloads)
            report = verify_repository(root, external_files=[(EXTERNAL_NAME, external)])
        self.assertIn("archive-record-version", {issue.code for issue in report.issues})

    def test_embedded_hash_count_and_fingerprint_chain_is_strict(self) -> None:
        cases = (
            (
                "records-hash",
                "order-02/manifest.json",
                lambda value: value["artifacts"].__setitem__(
                    "records_sha256", "0" * 64
                ),
                "archive-record-binding",
            ),
            (
                "completion-hash",
                "order-02/completion.json",
                lambda value: value.__setitem__("manifest_sha256", "0" * 64),
                "archive-completion-binding",
            ),
            (
                "manifest-count",
                "order-02/manifest.json",
                lambda value: value.__setitem__("record_count", 3),
                "archive-manifest-counts",
            ),
            (
                "fingerprint",
                "order-02/manifest.json",
                lambda value: value.__setitem__("run_fingerprint", "0" * 64),
                "archive-run-fingerprint",
            ),
        )
        for label, member_name, mutate, expected_code in cases:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as temporary:
                root, _ = _make_v2_release(Path(temporary))
                external, _ = _mutate_embedded_json(root, member_name, mutate)
                report = verify_repository(
                    root, external_files=[(EXTERNAL_NAME, external)]
                )
            self.assertIn(expected_code, {issue.code for issue in report.issues})

    def test_embedded_provenance_fields_are_exactly_cross_bound(self) -> None:
        mutations = (
            (
                "generator",
                lambda value: value["provenance"]["generator"].__setitem__(
                    "sha256", "0" * 64
                ),
            ),
            (
                "arguments",
                lambda value: value["provenance"]["generator"].__setitem__(
                    "arguments", ["-q", "-c", "2"]
                ),
            ),
            (
                "checks",
                lambda value: value["provenance"]["config"].__setitem__("checks", []),
            ),
            (
                "filter",
                lambda value: value["provenance"]["config"]["filters"].__setitem__(
                    "require_high_degree", False
                ),
            ),
            (
                "limits",
                lambda value: value["provenance"]["config"][
                    "search_limits"
                ].__setitem__("max_nodes_per_check", 100),
            ),
            (
                "shard",
                lambda value: value["provenance"].__setitem__(
                    "shard", {"count": 2, "index": 0}
                ),
            ),
            (
                "source",
                lambda value: value["provenance"]["toolkit"].__setitem__(
                    "source_sha256", "0" * 64
                ),
            ),
        )
        for label, mutate in mutations:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as temporary:
                root, _ = _make_v2_release(Path(temporary))
                external, _ = _mutate_embedded_json(
                    root, "order-02/manifest.json", mutate
                )
                report = verify_repository(
                    root, external_files=[(EXTERNAL_NAME, external)]
                )
            self.assertIn("archive-provenance", {issue.code for issue in report.issues})

    def test_embedded_json_and_jsonl_are_strict_and_finite(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root, _ = _make_v2_release(Path(temporary))
            payloads = _archive_payloads()
            payloads["order-02/manifest.json"] = b'{"complete":true,"complete":true}\n'
            external = _replace_external_archive(root, payloads)
            duplicate_report = verify_repository(
                root, external_files=[(EXTERNAL_NAME, external)]
            )
        self.assertIn("archive-json", {issue.code for issue in duplicate_report.issues})

        with tempfile.TemporaryDirectory() as temporary:
            root, _ = _make_v2_release(Path(temporary))
            payloads = _archive_payloads()
            payloads["order-02/records.jsonl"] = payloads[
                "order-02/records.jsonl"
            ].replace(b'"degree_parameter":1', b'"degree_parameter":1e999', 1)
            external = _replace_external_archive(root, payloads)
            nonfinite_report = verify_repository(
                root, external_files=[(EXTERNAL_NAME, external)]
            )
        self.assertIn(
            "archive-record-json", {issue.code for issue in nonfinite_report.issues}
        )

    def test_summary_v1_requires_one_canonical_finite_bound_claim(self) -> None:
        limitations = [
            "The finite census is computational evidence and does not establish "
            "an unbounded theorem.",
            "Generator completeness is assumed for the hash-pinned nauty-geng "
            "executable.",
        ]
        mutations = (
            (
                "no-claim",
                lambda summary: summary.__setitem__("claims", []),
                "summary-claim-count",
            ),
            (
                "two-claims",
                lambda summary: summary["claims"].append(
                    dict(summary["claims"][0], claim_id="U2-SECOND")
                ),
                "summary-claim-count",
            ),
            (
                "reserved-type",
                lambda summary: summary["claims"][0].__setitem__(
                    "claim_type", "unbounded_theorem"
                ),
                "summary-claim-type",
            ),
            (
                "wrong-status",
                lambda summary: summary["claims"][0].__setitem__("status", "open"),
                "summary-claim-status",
            ),
            (
                "partial-orders",
                lambda summary: summary["claims"][0].__setitem__("orders", []),
                "summary-claim-orders",
            ),
            (
                "nested-array-order",
                lambda summary: summary["claims"][0].__setitem__("orders", [[]]),
                "summary-claim-orders",
            ),
            (
                "object-order",
                lambda summary: summary["claims"][0].__setitem__("orders", [{}]),
                "summary-claim-orders",
            ),
            (
                "zero-order",
                lambda summary: summary["claims"][0].__setitem__("orders", [0]),
                "summary-claim-orders",
            ),
            (
                "handwritten-scope",
                lambda summary: summary["claims"][0].__setitem__(
                    "finite_scope", "order 2"
                ),
                "summary-claim-scope",
            ),
            (
                "claim-limitations",
                lambda summary: summary["claims"][0].__setitem__(
                    "limitations", list(reversed(limitations))
                ),
                "summary-claim-limitations",
            ),
            (
                "global-limitations",
                lambda summary: summary.__setitem__(
                    "limitations", list(reversed(limitations))
                ),
                "summary-limitations",
            ),
            (
                "no-high-degree-filter",
                lambda summary: summary["scope"].__setitem__(
                    "require_high_degree", False
                ),
                "summary-high-degree-filter",
            ),
        )
        for label, mutate, expected_code in mutations:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as temporary:
                root, _ = _make_v2_release(Path(temporary))
                summary_path = root / "results/universal-summary.json"
                summary = json.loads(summary_path.read_text(encoding="utf-8"))
                mutate(summary)
                _write_json(summary_path, summary)
                _refresh_local_integrity(root)
                report = verify_repository(root)
            self.assertIn(expected_code, {issue.code for issue in report.issues})

    def test_malformed_summary_containers_and_manifest_status_never_crash(self) -> None:
        summary_mutations: tuple[tuple[str, object], ...] = (
            ("scope", []),
            ("configuration", []),
            ("generator", []),
            ("producer", []),
            ("checks", {}),
        )
        for field, replacement in summary_mutations:
            with self.subTest(field=field), tempfile.TemporaryDirectory() as temporary:
                root, external = _make_v2_release(Path(temporary))
                summary_path = root / "results/universal-summary.json"
                summary = json.loads(summary_path.read_text(encoding="utf-8"))
                summary[field] = replacement
                _write_json(summary_path, summary)
                _refresh_local_integrity(root)
                report = verify_repository(
                    root, external_files=[(EXTERNAL_NAME, external)]
                )
            codes = {issue.code for issue in report.issues}
            self.assertIn("schema-type", codes)
            self.assertIn("archive-summary-shape", codes)

        for replacement in ([], {}):
            with (
                self.subTest(manifest_status=replacement),
                tempfile.TemporaryDirectory() as temporary,
            ):
                root, _ = _make_v2_release(Path(temporary))
                manifest_path = root / "manifests/dataset-manifest.json"
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                manifest["release"]["status"] = replacement
                _write_json(manifest_path, manifest)
                report = verify_repository(root)
            self.assertIn("schema-enum", {issue.code for issue in report.issues})

    def test_semantic_validation_boundaries_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root, _ = _make_v2_release(Path(temporary))
            with patch(
                "scripts.verify_release._validate_universal_summary_semantics",
                side_effect=AssertionError("forced summary failure"),
            ):
                summary_report = verify_repository(root)
        self.assertIn(
            "summary-semantic-error", {issue.code for issue in summary_report.issues}
        )

        with tempfile.TemporaryDirectory() as temporary:
            root, external = _make_v2_release(Path(temporary))
            with patch(
                "scripts.verify_release._verify_replay_archive",
                side_effect=TypeError("forced archive failure"),
            ):
                archive_report = verify_repository(
                    root, external_files=[(EXTERNAL_NAME, external)]
                )
        self.assertIn(
            "archive-semantic-error", {issue.code for issue in archive_report.issues}
        )

    def test_orders_are_positive_and_run_count_is_bounded_before_layout(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root, _ = _make_v2_release(Path(temporary))
            summary_path = root / "results/universal-summary.json"
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            summary["runs"][0]["order"] = 0
            summary["runs"][0]["generator_arguments"] = ["-q", "0"]
            summary["claims"][0]["orders"] = [0]
            _write_json(summary_path, summary)
            _refresh_local_integrity(root)
            zero_report = verify_repository(root)
        zero_codes = {issue.code for issue in zero_report.issues}
        self.assertIn("schema-minimum", zero_codes)
        self.assertIn("summary-run-order", zero_codes)
        self.assertIn("summary-claim-orders", zero_codes)
        with self.assertRaises(ValueError):
            _finite_scope_for_orders([0])
        with self.assertRaises(ValueError):
            _finite_scope_for_orders([17])

        with tempfile.TemporaryDirectory() as temporary:
            root, external = _make_v2_release(Path(temporary))
            summary_path = root / "results/universal-summary.json"
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            summary["runs"] = [None] * 257
            _write_json(summary_path, summary)
            _refresh_local_integrity(root)
            with patch(
                "scripts.verify_release._canonical_tar_layout",
                side_effect=AssertionError("layout must not run"),
            ) as layout:
                run_limit_report = verify_repository(
                    root, external_files=[(EXTERNAL_NAME, external)]
                )
            layout.assert_not_called()
        run_limit_codes = {issue.code for issue in run_limit_report.issues}
        self.assertIn("summary-run-limit", run_limit_codes)
        self.assertIn("archive-run-limit", run_limit_codes)

        for invalid_order in (0, False, 2.0, 17):
            with (
                self.subTest(archive_order=invalid_order),
                tempfile.TemporaryDirectory() as temporary,
            ):
                root, external = _make_v2_release(Path(temporary))
                summary_path = root / "results/universal-summary.json"
                summary = json.loads(summary_path.read_text(encoding="utf-8"))
                summary["runs"][0]["order"] = invalid_order
                summary["claims"][0]["orders"] = [invalid_order]
                _write_json(summary_path, summary)
                _refresh_local_integrity(root)
                with (
                    patch(
                        "scripts.verify_release._canonical_tar_layout",
                        side_effect=AssertionError("layout must not run"),
                    ) as layout,
                    patch(
                        "scripts.verify_release.zlib.decompressobj",
                        side_effect=AssertionError("decompression must not run"),
                    ) as decompress,
                    patch(
                        "scripts.verify_release.tarfile.open",
                        side_effect=AssertionError("archive open must not run"),
                    ) as archive_open,
                ):
                    invalid_order_report = verify_repository(
                        root, external_files=[(EXTERNAL_NAME, external)]
                    )
                layout.assert_not_called()
                decompress.assert_not_called()
                archive_open.assert_not_called()
            invalid_codes = {issue.code for issue in invalid_order_report.issues}
            self.assertIn(
                "archive-summary-order",
                invalid_codes,
            )
            if invalid_order == 17:
                self.assertIn("schema-maximum", invalid_codes)
                self.assertIn("summary-run-order", invalid_codes)
                self.assertIn("summary-claim-orders", invalid_codes)

    def test_unhashable_embedded_status_values_never_crash(self) -> None:
        cases: tuple[tuple[str, str, object], ...] = (
            ("record-list", "record", []),
            ("record-object", "record", {}),
            ("check-list", "check", []),
            ("check-object", "check", {}),
        )
        for label, target, replacement in cases:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as temporary:
                root, _ = _make_v2_release(Path(temporary))
                payloads = _archive_payloads()
                records = [
                    json.loads(line)
                    for line in payloads["order-02/records.jsonl"].splitlines()
                ]
                if target == "record":
                    records[1]["status"] = replacement
                    expected_code = "archive-record-status"
                else:
                    records[1]["partitions"][0]["checks"][0]["status"] = replacement
                    expected_code = "archive-check-status"
                payloads["order-02/records.jsonl"] = b"".join(
                    json.dumps(
                        record,
                        allow_nan=False,
                        separators=(",", ":"),
                        sort_keys=True,
                    ).encode("utf-8")
                    + b"\n"
                    for record in records
                )
                external = _replace_external_archive(root, payloads)
                report = verify_repository(
                    root, external_files=[(EXTERNAL_NAME, external)]
                )
            self.assertIn(expected_code, {issue.code for issue in report.issues})

    def test_embedded_numeric_bindings_are_exact_and_chain_recomputed(self) -> None:
        cases: tuple[tuple[str, Any, str], ...] = (
            (
                "record-index-bool",
                lambda records: records[1].__setitem__("index", True),
                "archive-record-index",
            ),
            (
                "record-index-float",
                lambda records: records[1].__setitem__("index", 1.0),
                "archive-record-index",
            ),
            (
                "record-index-wrong",
                lambda records: records[1].__setitem__("index", 999),
                "archive-record-index",
            ),
            (
                "record-order-bool",
                lambda records: records[1].__setitem__("order", True),
                "archive-record-order",
            ),
            (
                "record-order-float",
                lambda records: records[1].__setitem__("order", 2.0),
                "archive-record-order",
            ),
            (
                "record-order-wrong",
                lambda records: records[1].__setitem__("order", 999),
                "archive-record-order",
            ),
            (
                "partition-index-bool",
                lambda records: records[1]["partitions"][0].__setitem__("index", False),
                "archive-partition-index",
            ),
            (
                "partition-index-float",
                lambda records: records[1]["partitions"][0].__setitem__("index", 0.0),
                "archive-partition-index",
            ),
            (
                "partition-index-wrong",
                lambda records: records[1]["partitions"][0].__setitem__("index", 999),
                "archive-partition-index",
            ),
            (
                "palette-offset-bool",
                lambda records: records[1]["partitions"][0]["checks"][0].__setitem__(
                    "palette_offset", True
                ),
                "archive-check-shape",
            ),
            (
                "palette-offset-float",
                lambda records: records[1]["partitions"][0]["checks"][0].__setitem__(
                    "palette_offset", 1.0
                ),
                "archive-check-shape",
            ),
            (
                "palette-offset-wrong",
                lambda records: records[1]["partitions"][0]["checks"][0].__setitem__(
                    "palette_offset", 999
                ),
                "archive-check-matrix",
            ),
            (
                "color-count-bool",
                lambda records: records[1]["partitions"][0]["checks"][0].__setitem__(
                    "color_count", True
                ),
                "archive-check-shape",
            ),
            (
                "color-count-float",
                lambda records: records[1]["partitions"][0]["checks"][0].__setitem__(
                    "color_count", 3.0
                ),
                "archive-check-shape",
            ),
            (
                "color-count-wrong",
                lambda records: records[1]["partitions"][0]["checks"][0].__setitem__(
                    "color_count", 999
                ),
                "archive-check-color-count",
            ),
            (
                "degree-parameter-cross-binding",
                lambda records: records[1].__setitem__("degree_parameter", 999),
                "archive-check-color-count",
            ),
        )
        stale_chain_codes = {
            "archive-completion-binding",
            "archive-member-hash",
            "archive-record-binding",
        }
        for label, mutate, expected_code in cases:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as temporary:
                root, _ = _make_v2_release(Path(temporary))
                records = [
                    json.loads(line)
                    for line in (FIXTURE_ROOT / "records.jsonl")
                    .read_bytes()
                    .splitlines()
                ]
                mutate(records)
                external = _replace_records_with_recomputed_chain(root, records)
                report = verify_repository(
                    root, external_files=[(EXTERNAL_NAME, external)]
                )
            codes = {issue.code for issue in report.issues}
            self.assertIn(expected_code, codes)
            self.assertFalse(stale_chain_codes & codes, codes)

    def test_duplicate_graph_detection_remains_a_separate_scientific_gate(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root, _ = _make_v2_release(Path(temporary))
            records = [
                json.loads(line)
                for line in (FIXTURE_ROOT / "records.jsonl").read_bytes().splitlines()
            ]
            records[1]["graph6"] = records[0]["graph6"]
            external = _replace_records_with_recomputed_chain(root, records)
            report = verify_repository(root, external_files=[(EXTERNAL_NAME, external)])
        self.assertTrue(report.ok, report.issues)

    def test_gzip_stream_requires_exact_header_trailer_and_raw_eof(self) -> None:
        def flip(raw: bytes, index: int) -> bytes:
            mutated = bytearray(raw)
            mutated[index] ^= 0x01
            return bytes(mutated)

        cases = (
            ("raw-text-suffix", lambda raw: raw + b"x", "archive-gzip-trailing"),
            ("raw-zero-suffix", lambda raw: raw + b"\0", "archive-gzip-trailing"),
            (
                "concatenated-member",
                lambda raw: raw + _gzip_bytes(b""),
                "archive-gzip-trailing",
            ),
            ("missing-trailer", lambda raw: raw[:-8], "archive-gzip-stream"),
            ("bad-crc", lambda raw: flip(raw, -8), "archive-gzip-stream"),
            ("bad-isize", lambda raw: flip(raw, -4), "archive-gzip-stream"),
            ("truncate-one", lambda raw: raw[:-1], "archive-gzip-stream"),
            ("truncate-twenty", lambda raw: raw[:-20], "archive-gzip-stream"),
            ("truncate-512", lambda raw: raw[:-512], "archive-gzip-stream"),
            ("wrong-xfl", lambda raw: raw[:8] + b"\0" + raw[9:], "archive-gzip-header"),
            (
                "wrong-os",
                lambda raw: raw[:9] + b"\x03" + raw[10:],
                "archive-gzip-header",
            ),
        )
        for label, mutate, expected_code in cases:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as temporary:
                root, external = _make_v2_release(Path(temporary))
                external.write_bytes(mutate(external.read_bytes()))
                _bind_external_archive(root, external)
                report = verify_repository(
                    root, external_files=[(EXTERNAL_NAME, external)]
                )
            self.assertIn(expected_code, {issue.code for issue in report.issues})

    def test_ustar_requires_exact_format_padding_end_and_length(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root, _ = _make_v2_release(Path(temporary))
            external = _replace_external_archive(
                root, _archive_payloads(), tar_format=tarfile.GNU_FORMAT
            )
            gnu_report = verify_repository(
                root, external_files=[(EXTERNAL_NAME, external)]
            )
        self.assertIn(
            "archive-ustar-layout", {issue.code for issue in gnu_report.issues}
        )

        for label, index in (
            (
                "member-padding",
                512 + len(_archive_payloads()["order-02/completion.json"]),
            ),
            ("terminal-padding", -1),
        ):
            with self.subTest(label=label), tempfile.TemporaryDirectory() as temporary:
                root, external = _make_v2_release(Path(temporary))
                tar_payload = bytearray(gzip.decompress(external.read_bytes()))
                tar_payload[index] = 1
                external.write_bytes(_gzip_bytes(bytes(tar_payload)))
                _bind_external_archive(root, external)
                report = verify_repository(
                    root, external_files=[(EXTERNAL_NAME, external)]
                )
            self.assertIn(
                "archive-ustar-layout", {issue.code for issue in report.issues}
            )

        for label, suffix in (("nonzero", b"x"), ("zero", b"\0")):
            with self.subTest(label=label), tempfile.TemporaryDirectory() as temporary:
                root, external = _make_v2_release(Path(temporary))
                tar_with_suffix = gzip.decompress(external.read_bytes()) + suffix
                external.write_bytes(_gzip_bytes(tar_with_suffix))
                _bind_external_archive(root, external)
                report = verify_repository(
                    root, external_files=[(EXTERNAL_NAME, external)]
                )
            self.assertIn(
                "archive-ustar-length", {issue.code for issue in report.issues}
            )

    def test_archive_metadata_and_jsonl_size_limits_are_enforced_streamingly(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root, _ = _make_v2_release(Path(temporary))
            payloads = _archive_payloads()
            payloads["order-02/manifest.json"] = b"{}\n" + b" " * (4 * 1024 * 1024)
            external = _replace_external_archive(root, payloads)
            metadata_report = verify_repository(
                root, external_files=[(EXTERNAL_NAME, external)]
            )
        self.assertIn(
            "archive-member-size", {issue.code for issue in metadata_report.issues}
        )

        with tempfile.TemporaryDirectory() as temporary:
            root, _ = _make_v2_release(Path(temporary))
            payloads = _archive_payloads()
            payloads["order-02/records.jsonl"] = (
                b'{"detail":"' + b"x" * (17 * 1024 * 1024) + b'"}\n'
            )
            external = _replace_external_archive(root, payloads)
            record_report = verify_repository(
                root, external_files=[(EXTERNAL_NAME, external)]
            )
        self.assertIn(
            "archive-record-size", {issue.code for issue in record_report.issues}
        )

    def test_json_integer_document_and_nesting_limits_fail_closed(self) -> None:
        huge_integer = b"9" * 5000
        too_deep = b"[" * 129 + b"0" + b"]" * 129
        oversized = b" " * (16 * 1024 * 1024 + 1)
        root_cases = (
            ("integer", b'{"value":' + huge_integer + b"}"),
            ("nesting", too_deep),
            ("document-size", oversized),
        )
        for label, payload in root_cases:
            with self.subTest(root=label), tempfile.TemporaryDirectory() as temporary:
                root, _ = _make_v2_release(Path(temporary))
                (root / "manifests/dataset-manifest.json").write_bytes(payload)
                report = verify_repository(root)
            self.assertIn("manifest-json", {issue.code for issue in report.issues})

        for label, payload in root_cases:
            with (
                self.subTest(summary=label),
                tempfile.TemporaryDirectory() as temporary,
            ):
                root, _ = _make_v2_release(Path(temporary))
                (root / "results/universal-summary.json").write_bytes(payload)
                _refresh_local_integrity(root)
                report = verify_repository(root)
            self.assertIn("artifact-json", {issue.code for issue in report.issues})

    def test_lone_surrogates_are_rejected_recursively_and_never_reencoded(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            document = Path(temporary) / "surrogate.json"
            document.write_bytes(b'{"outer":[{"value":"\\ud800"}]}')
            with self.assertRaises(json.JSONDecodeError):
                _load_json(document)
        with self.assertRaises(ValueError):
            _canonical_json_bytes({"outer": [{"\ud800": "value"}]})
        self.assertEqual(
            _canonical_json_bytes({"emoji": "\U0001f600"}),
            b'{"emoji":"\xf0\x9f\x98\x80"}',
        )

        with tempfile.TemporaryDirectory() as temporary:
            root, _ = _make_v2_release(Path(temporary))
            manifest_path = root / "manifests/dataset-manifest.json"
            manifest_path.write_bytes(
                manifest_path.read_bytes().replace(
                    b"Total Coloring Data", b"\\ud800", 1
                )
            )
            manifest_report = verify_repository(root)
        self.assertIn("manifest-json", {issue.code for issue in manifest_report.issues})

        with tempfile.TemporaryDirectory() as temporary:
            root, _ = _make_v2_release(Path(temporary))
            summary_path = root / "results/universal-summary.json"
            summary_path.write_bytes(
                summary_path.read_bytes().replace(
                    b"order-2-universal-census", b"\\ud800", 1
                )
            )
            _refresh_local_integrity(root)
            summary_report = verify_repository(root)
        self.assertIn("artifact-json", {issue.code for issue in summary_report.issues})

        with tempfile.TemporaryDirectory() as temporary:
            root, _ = _make_v2_release(Path(temporary))
            payloads = _archive_payloads()
            payloads["order-02/records.jsonl"] = payloads[
                "order-02/records.jsonl"
            ].replace(b'"detail":"', b'"detail":"\\ud800', 1)
            external = _replace_external_archive(root, payloads)
            archive_report = verify_repository(
                root, external_files=[(EXTERNAL_NAME, external)]
            )
        self.assertIn(
            "archive-record-json", {issue.code for issue in archive_report.issues}
        )

    def test_checksum_input_is_utf8_and_size_bounded(self) -> None:
        cases = (
            ("invalid-utf8", b"\xff\n", "checksums-encoding"),
            ("oversized-line", b"#" + b"x" * 4095 + b"\n", "checksums-line-size"),
            ("oversized-file", b"#" * (4 * 1024 * 1024 + 1), "checksums-size"),
        )
        for label, payload, expected_code in cases:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as temporary:
                root, _ = _make_v2_release(Path(temporary))
                (root / "SHA256SUMS").write_bytes(payload)
                report = verify_repository(root)
            self.assertIn(expected_code, {issue.code for issue in report.issues})

    def test_verification_issue_count_is_hard_capped(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root, _ = _make_v2_release(Path(temporary))
            manifest_path = root / "manifests/dataset-manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["artifacts"] = [None] * 1200
            _write_json(manifest_path, manifest)
            report = verify_repository(root)
        self.assertEqual(len(report.issues), 1000)
        self.assertEqual(report.issues[-1].code, "issue-limit")

    def test_near_limit_arrays_obey_max_items_and_diagnostic_cap(self) -> None:
        item_count = (16 * 1024 * 1024 - 2) // 5
        self.assertLessEqual(5 * item_count + 1, 16 * 1024 * 1024)
        near_limit_array = [None] * item_count

        bounded_issues: list[VerificationIssue] = []
        _validate_instance(
            near_limit_array,
            {"type": "array", "maxItems": 3, "items": {"type": "object"}},
            "$bounded",
            bounded_issues,
        )
        self.assertEqual(len(bounded_issues), 4)
        self.assertEqual(bounded_issues[0].code, "schema-items")

        capped_issues: list[VerificationIssue] = []
        _validate_instance(
            near_limit_array,
            {"type": "array", "items": {"type": "object"}},
            "$capped",
            capped_issues,
        )
        self.assertEqual(len(capped_issues), 1000)
        self.assertEqual(capped_issues[-1].code, "issue-limit")

    def test_oversized_summary_arrays_short_circuit_semantics(self) -> None:
        cases = (
            ("checks", [None] * 10_000, "summary-check-limit"),
            ("claims", [None] * 10_000, "summary-claim-count"),
        )
        for field, replacement, expected_code in cases:
            with self.subTest(field=field), tempfile.TemporaryDirectory() as temporary:
                root, _ = _make_v2_release(Path(temporary))
                summary_path = root / "results/universal-summary.json"
                summary = json.loads(summary_path.read_text(encoding="utf-8"))
                summary[field] = replacement
                _write_json(summary_path, summary)
                _refresh_local_integrity(root)
                report = verify_repository(root)
            self.assertIn(expected_code, {issue.code for issue in report.issues})

    def test_external_inventory_order_uniqueness_and_namespace_are_enforced(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root, _ = _make_v2_release(Path(temporary))
            manifest_path = root / "manifests/dataset-manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            first = manifest["external_artifacts"][0]
            second = dict(first)
            second["name"] = "archives/another.tar.gz"
            second["url"] = "https://example.org/z-another.tar.gz"
            manifest["external_artifacts"] = [first, second]
            _write_json(manifest_path, manifest)
            order_report = verify_repository(root)

            manifest["external_artifacts"] = [first, dict(first)]
            _write_json(manifest_path, manifest)
            duplicate_report = verify_repository(root)

            collision = dict(first)
            collision["name"] = "results/universal-summary.json"
            manifest["external_artifacts"] = [collision]
            _write_json(manifest_path, manifest)
            collision_report = verify_repository(root)
        order_codes = {issue.code for issue in order_report.issues}
        self.assertIn("external-artifact-order", order_codes)
        self.assertIn("external-url-order", order_codes)
        duplicate_codes = {issue.code for issue in duplicate_report.issues}
        self.assertIn("external-artifact-duplicate", duplicate_codes)
        self.assertIn("external-url-duplicate", duplicate_codes)
        self.assertIn(
            "artifact-namespace-collision",
            {issue.code for issue in collision_report.issues},
        )

    def test_summary_provenance_archive_and_count_invariants_are_enforced(self) -> None:
        mutations = (
            (
                "producer",
                lambda value: value["producer"].__setitem__("commit", "a" * 40),
                "summary-producer-commit",
            ),
            (
                "run-counts",
                lambda value: value["runs"][0]["counts"].__setitem__("skipped", 2),
                "summary-run-counts",
            ),
            (
                "evaluations",
                lambda value: value["runs"][0].__setitem__("check_evaluations", 1),
                "summary-run-check-evaluations",
            ),
            (
                "totals",
                lambda value: value["totals"].__setitem__("partition_count", 2),
                "summary-totals",
            ),
            (
                "archive",
                lambda value: value["replay_archive"].__setitem__("sha256", "0" * 64),
                "summary-replay-binding",
            ),
            (
                "claim-order",
                lambda value: value["claims"][0].__setitem__("orders", [3]),
                "summary-claim-orders",
            ),
            (
                "limitations",
                lambda value: value.__setitem__("limitations", []),
                "summary-limitations",
            ),
            (
                "malformed-check",
                lambda value: value["checks"][0].__setitem__("backend_id", []),
                "schema-enum",
            ),
            (
                "misleading-unbounded-description",
                lambda value: value["checks"][0].__setitem__(
                    "description",
                    "This check proves an unbounded total-coloring theorem for every graph.",
                ),
                "summary-required-check",
            ),
            (
                "restricted-generator",
                lambda value: value["runs"][0].__setitem__(
                    "generator_arguments", ["-q", "-c", "2"]
                ),
                "summary-generator-arguments",
            ),
            (
                "sharded",
                lambda value: value["runs"][0].__setitem__("shard_count", 2),
                "summary-shard",
            ),
            (
                "zero-timeout",
                lambda value: value["configuration"]["search_limits"].__setitem__(
                    "timeout_seconds_per_check", 0
                ),
                "summary-search-limit",
            ),
        )
        for label, mutate, expected_code in mutations:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as temporary:
                root, _ = _make_v2_release(Path(temporary))
                summary_path = root / "results/universal-summary.json"
                summary = json.loads(summary_path.read_text(encoding="utf-8"))
                mutate(summary)
                _write_json(summary_path, summary)
                _refresh_local_integrity(root)
                report = verify_repository(root)
            self.assertIn(expected_code, {issue.code for issue in report.issues})

    def test_summary_repository_trust_rejects_coordinated_substitution(self) -> None:
        attacker_repository = "https://example.org/attacker-toolkit"
        with tempfile.TemporaryDirectory() as temporary:
            root, _ = _make_v2_release(Path(temporary))
            manifest_path = root / "manifests/dataset-manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["release"]["code_repository"] = attacker_repository
            _write_json(manifest_path, manifest)
            summary_path = root / "results/universal-summary.json"
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            summary["producer"]["repository"] = attacker_repository
            _write_json(summary_path, summary)
            _refresh_local_integrity(root)

            default_report = verify_repository(root)
            override_report = verify_repository(
                root, expected_code_repository=attacker_repository
            )

        default_codes = {issue.code for issue in default_report.issues}
        self.assertIn("release-code-repository", default_codes)
        self.assertIn("summary-producer-repository", default_codes)
        self.assertTrue(override_report.ok, override_report.issues)

    def test_summary_archive_member_paths_must_be_unique_and_canonical(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root, _ = _make_v2_release(Path(temporary))
            summary_path = root / "results/universal-summary.json"
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            members = summary["runs"][0]["members"]
            members["completion"]["path"] = members["manifest"]["path"]
            _write_json(summary_path, summary)
            _refresh_local_integrity(root)
            report = verify_repository(root)
        codes = {issue.code for issue in report.issues}
        self.assertIn("summary-member-name", codes)
        self.assertIn("summary-member-duplicate", codes)

        with tempfile.TemporaryDirectory() as temporary:
            root, _ = _make_v2_release(Path(temporary))
            summary_path = root / "results/universal-summary.json"
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            summary["runs"][0]["members"]["completion"]["path"] = (
                "wrong-parent/completion.json"
            )
            _write_json(summary_path, summary)
            _refresh_local_integrity(root)
            parent_report = verify_repository(root)
        self.assertIn(
            "summary-member-parent", {issue.code for issue in parent_report.issues}
        )

    def test_verified_claims_are_nonvacuous_zero_adverse_and_cover_checks(self) -> None:
        mutations = (
            (
                "missing-checks",
                lambda summary: summary["claims"][0].__setitem__("required_checks", []),
                "summary-claim-checks",
            ),
            (
                "adverse",
                lambda summary: (
                    summary["runs"][0]["counts"].update(
                        {"candidate_unsat": 1, "skipped": 0}
                    ),
                    summary["totals"]["counts"].update(
                        {"candidate_unsat": 1, "skipped": 0}
                    ),
                ),
                "summary-claim-adverse-status",
            ),
            (
                "vacuous",
                lambda summary: (
                    summary["runs"][0].update(
                        {
                            "partition_count": 0,
                            "check_evaluations": 0,
                            "counts": {
                                "candidate_unsat": 0,
                                "error": 0,
                                "skipped": 2,
                                "unknown": 0,
                                "verified_all": 0,
                            },
                        }
                    ),
                    summary["totals"].update(
                        {
                            "partition_count": 0,
                            "check_evaluations": 0,
                            "counts": {
                                "candidate_unsat": 0,
                                "error": 0,
                                "skipped": 2,
                                "unknown": 0,
                                "verified_all": 0,
                            },
                        }
                    ),
                ),
                "summary-claim-vacuous",
            ),
        )
        for label, mutate, expected_code in mutations:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as temporary:
                root, _ = _make_v2_release(Path(temporary))
                summary_path = root / "results/universal-summary.json"
                summary = json.loads(summary_path.read_text(encoding="utf-8"))
                mutate(summary)
                _write_json(summary_path, summary)
                _refresh_local_integrity(root)
                report = verify_repository(root)
            self.assertIn(expected_code, {issue.code for issue in report.issues})

    def test_summary_run_fingerprints_must_be_unique(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root, _ = _make_v2_release(Path(temporary))
            summary_path = root / "results/universal-summary.json"
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            second_run = json.loads(json.dumps(summary["runs"][0]))
            second_run["order"] = 3
            second_run["generator_arguments"] = ["-q", "3"]
            for member in second_run["members"].values():
                member["path"] = member["path"].replace("order-02", "order-03")
            summary["runs"].append(second_run)
            totals = summary["totals"]
            totals["order_count"] = 2
            totals["record_count"] = 4
            totals["partition_count"] = 2
            totals["check_evaluations"] = 6
            totals["counts"]["verified_all"] = 2
            totals["counts"]["skipped"] = 2
            _write_json(summary_path, summary)
            _refresh_local_integrity(root)
            report = verify_repository(root)
        self.assertIn(
            "summary-run-fingerprint-duplicate",
            {issue.code for issue in report.issues},
        )

    def test_schema_const_and_enum_comparisons_are_json_type_aware(self) -> None:
        const_issues: list[VerificationIssue] = []
        enum_issues: list[VerificationIssue] = []
        _validate_instance(True, {"const": 1}, "$const", const_issues)
        _validate_instance(True, {"enum": [1]}, "$enum", enum_issues)
        self.assertIn("schema-const", {issue.code for issue in const_issues})
        self.assertIn("schema-enum", {issue.code for issue in enum_issues})

        for field, replacement in (
            ("shard_index", False),
            ("shard_index", 0.0),
            ("shard_count", True),
            ("shard_count", 1.0),
        ):
            with (
                self.subTest(field=field, replacement=replacement),
                tempfile.TemporaryDirectory() as temporary,
            ):
                root, _ = _make_v2_release(Path(temporary))
                summary_path = root / "results/universal-summary.json"
                summary = json.loads(summary_path.read_text(encoding="utf-8"))
                summary["runs"][0][field] = replacement
                _write_json(summary_path, summary)
                _refresh_local_integrity(root)
                report = verify_repository(root)
            codes = {issue.code for issue in report.issues}
            self.assertIn("schema-type", codes)

        summary_schema = _load_json(
            REPOSITORY_ROOT / "schemas/universal-census-summary-v1.schema.json"
        )
        run_properties = summary_schema["properties"]["runs"]["items"]["properties"]
        self.assertEqual(run_properties["shard_index"], {"type": "integer", "const": 0})
        self.assertEqual(run_properties["shard_count"], {"type": "integer", "const": 1})

    def test_schema_maximum_is_json_number_type_aware(self) -> None:
        cases = (
            (16, False),
            (17, True),
            (16.5, True),
            (True, False),
            ("17", False),
        )
        for value, should_fail in cases:
            with self.subTest(value=value):
                issues: list[VerificationIssue] = []
                _validate_instance(value, {"maximum": 16}, "$maximum", issues)
                self.assertEqual(
                    "schema-maximum" in {issue.code for issue in issues},
                    should_fail,
                )

    def test_strict_json_loader_rejects_overflowing_numeric_literal(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            document = Path(temporary) / "overflow.json"
            document.write_text('{"value": 1e999}\n', encoding="utf-8")
            with self.assertRaises(json.JSONDecodeError):
                _load_json(document)

    def test_external_https_urls_are_strictly_normalized(self) -> None:
        invalid_urls = (
            "http://github.com/archive.tar.gz",
            "HTTPS://github.com/archive.tar.gz",
            "https://user@github.com/archive.tar.gz",
            "https://github.com:443/archive.tar.gz",
            "https://github.com/archive.tar.gz?download=1",
            "https://github.com/archive.tar.gz#fragment",
            "https://github.com/a/../archive.tar.gz",
            "https://github.com/a/%2e%2e/archive.tar.gz",
            "https://github.com/%",
            "https://github.com/%2",
            "https://github.com/%GG",
            "https://github.com/%FF",
            "https://github.com/%41",
            "https://github.com/%2F",
            "https://GITHUB.com/archive.tar.gz",
            "https://github.com//archive.tar.gz",
            "https://github.com\\@evil.example/archive.tar.gz",
            "https://-bad.example/archive.tar.gz",
            "https://github.com/archive tar.gz",
            "https://[bad/archive.tar.gz",
            'https://github.com/a"b/archive.tar.gz',
            "https://github.com/{archive}.tar.gz",
            "https://github.com/[archive].tar.gz",
            "https://github.com/`archive`.tar.gz",
            "https://github.com/^archive.tar.gz",
            "https://github.com/|archive.tar.gz",
            "https://github.com/archive\x7f.tar.gz",
            "https://github.com/archive\x1f.tar.gz",
            "https://github.com/café/archive.tar.gz",
        )
        for url in invalid_urls:
            with self.subTest(url=url), tempfile.TemporaryDirectory() as temporary:
                root, _ = _make_v2_release(Path(temporary))
                manifest_path = root / "manifests/dataset-manifest.json"
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                manifest["external_artifacts"][0]["url"] = url
                _write_json(manifest_path, manifest)
                summary_path = root / "results/universal-summary.json"
                summary = json.loads(summary_path.read_text(encoding="utf-8"))
                summary["replay_archive"]["url"] = url
                _write_json(summary_path, summary)
                _refresh_local_integrity(root)
                report = verify_repository(root)
            self.assertIn("schema-format", {issue.code for issue in report.issues})

        with tempfile.TemporaryDirectory() as temporary:
            root, _ = _make_v2_release(Path(temporary))
            manifest_path = root / "manifests/dataset-manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["release"]["code_repository"] = "https://[bad/repository"
            _write_json(manifest_path, manifest)
            generic_uri_report = verify_repository(root)
        self.assertIn(
            "schema-format", {issue.code for issue in generic_uri_report.issues}
        )

        valid_pchar_url = "https://example.org/AZaz09-._~!$&'()*+,;=:@/archive.tar.gz"
        with tempfile.TemporaryDirectory() as temporary:
            root, _ = _make_v2_release(Path(temporary))
            manifest_path = root / "manifests/dataset-manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["external_artifacts"][0]["url"] = valid_pchar_url
            _write_json(manifest_path, manifest)
            summary_path = root / "results/universal-summary.json"
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            summary["replay_archive"]["url"] = valid_pchar_url
            _write_json(summary_path, summary)
            _refresh_local_integrity(root)
            valid_pchar_report = verify_repository(root)
        self.assertTrue(valid_pchar_report.ok, valid_pchar_report.issues)

    def test_https_path_component_ascii_alphabet_is_exact(self) -> None:
        allowed = set(
            "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
            "abcdefghijklmnopqrstuvwxyz"
            "0123456789"
            "-._~!$&'()*+,;=:@"
        )
        for codepoint in range(128):
            character = chr(codepoint)
            if character == "/":
                continue
            url = f"https://example.org/a{character}b/archive.tar.gz"
            with self.subTest(codepoint=codepoint, character=repr(character)):
                self.assertEqual(
                    _format_matches(url, "https-uri"), character in allowed
                )

    def test_modified_v2_or_summary_schema_is_rejected_by_trust_pin(self) -> None:
        for schema_name in (
            "dataset-manifest-v2.schema.json",
            "universal-census-summary-v1.schema.json",
        ):
            with (
                self.subTest(schema=schema_name),
                tempfile.TemporaryDirectory() as temporary,
            ):
                root, _ = _make_v2_release(Path(temporary))
                schema_path = root / "schemas" / schema_name
                schema = json.loads(schema_path.read_text(encoding="utf-8"))
                schema["description"] = "weakened replacement"
                _write_json(schema_path, schema)
                report = verify_repository(root)
            self.assertIn("schema-digest", {issue.code for issue in report.issues})


if __name__ == "__main__":
    unittest.main()
