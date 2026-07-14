from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import unittest
from collections.abc import Callable
from pathlib import Path

from scripts.verify_release import _load_json, verify_repository

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def _canonical_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _result_payload() -> dict[str, object]:
    return {
        "schema_version": "1.0.0",
        "record_id": "fixture:triangle",
        "problem_digest": "a" * 64,
        "status": "witness",
        "producer": {
            "repository": "https://github.com/chenle02/total-coloring-toolkit",
            "commit": "b" * 40,
            "version": "0.1.0",
        },
        "parameters": {"colors": 3, "order": 3},
        "certificate": {"assignment": [0, 1, 2]},
    }


def _refresh_artifact_integrity(root: Path) -> None:
    result_path = root / "results/fixture.json"
    manifest_path = root / "manifests/dataset-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    digest = _sha256(result_path)
    manifest["artifacts"][0]["bytes"] = result_path.stat().st_size
    manifest["artifacts"][0]["sha256"] = digest
    _canonical_json(manifest_path, manifest)
    (root / "SHA256SUMS").write_text(
        f"{digest}  results/fixture.json\n", encoding="utf-8"
    )


def _make_release(root: Path) -> Path:
    (root / "results").mkdir(parents=True)
    (root / "reports").mkdir()
    (root / "manifests").mkdir()
    (root / "schemas").mkdir()
    shutil.copy2(
        REPOSITORY_ROOT / "schemas/dataset-manifest-v1.schema.json",
        root / "schemas/dataset-manifest-v1.schema.json",
    )
    shutil.copy2(
        REPOSITORY_ROOT / "schemas/result-v1.schema.json",
        root / "schemas/result-v1.schema.json",
    )
    result = root / "results/fixture.json"
    _canonical_json(result, _result_payload())
    digest = _sha256(result)
    manifest = {
        "$schema": "schemas/dataset-manifest-v1.schema.json",
        "schema_version": "1.0.0",
        "dataset": {
            "id": "total-coloring-data",
            "title": "Total Coloring Data",
            "license": "CC-BY-4.0",
            "repository": "https://github.com/chenle02/total-coloring-data",
        },
        "release": {
            "version": "1.0.0-rc.1",
            "status": "candidate",
            "created_utc": "2026-07-14T03:00:00Z",
            "code_repository": "https://github.com/chenle02/total-coloring-toolkit",
            "code_commit": "b" * 40,
        },
        "managed_roots": ["reports", "results"],
        "artifacts": [
            {
                "path": "results/fixture.json",
                "role": "result",
                "media_type": "application/json",
                "bytes": result.stat().st_size,
                "sha256": digest,
                "schema": "schemas/result-v1.schema.json",
                "records": 1,
                "description": "Small verifier fixture.",
            }
        ],
    }
    _canonical_json(root / "manifests/dataset-manifest.json", manifest)
    (root / "SHA256SUMS").write_text(
        f"{digest}  results/fixture.json\n", encoding="utf-8"
    )
    return root


class ReleaseVerifierTests(unittest.TestCase):
    def test_repository_scaffold_verifies(self) -> None:
        report = verify_repository(REPOSITORY_ROOT)
        self.assertTrue(report.ok, report.issues)
        self.assertEqual(report.artifact_count, 0)

    def test_complete_candidate_release_verifies(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            report = verify_repository(_make_release(Path(temporary)))
        self.assertTrue(report.ok, report.issues)
        self.assertEqual(report.artifact_count, 1)

    def test_trusted_schema_pins_use_canonical_json_content(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = _make_release(Path(temporary))
            for schema_path in (
                root / "schemas/dataset-manifest-v1.schema.json",
                root / "schemas/result-v1.schema.json",
            ):
                schema = json.loads(schema_path.read_text(encoding="utf-8"))
                schema_path.write_text(
                    json.dumps(schema, ensure_ascii=False, separators=(",", ":")),
                    encoding="utf-8",
                )
            report = verify_repository(root)
        self.assertTrue(report.ok, report.issues)

    def test_tampered_artifact_fails_hash_and_byte_checks(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = _make_release(Path(temporary))
            (root / "results/fixture.json").write_text("{}\n", encoding="utf-8")
            report = verify_repository(root)
        codes = {issue.code for issue in report.issues}
        self.assertIn("artifact-hash", codes)
        self.assertIn("artifact-bytes", codes)

    def test_unlisted_managed_file_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = _make_release(Path(temporary))
            (root / "reports/unreviewed.txt").write_text("scratch\n", encoding="utf-8")
            report = verify_repository(root)
        self.assertIn("managed-inventory", {issue.code for issue in report.issues})

    def test_path_traversal_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = _make_release(Path(temporary))
            manifest_path = root / "manifests/dataset-manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["artifacts"][0]["path"] = "../escape.json"
            _canonical_json(manifest_path, manifest)
            report = verify_repository(root)
        codes = {issue.code for issue in report.issues}
        self.assertIn("schema-format", codes)

    @unittest.skipUnless(hasattr(os, "symlink"), "symlinks unavailable")
    def test_symlinked_artifact_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = _make_release(Path(temporary))
            result = root / "results/fixture.json"
            target = root / "fixture-target.json"
            result.replace(target)
            result.symlink_to(target)
            report = verify_repository(root)
        self.assertIn("symlink", {issue.code for issue in report.issues})

    def test_modified_schema_with_unsupported_keyword_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = _make_release(Path(temporary))
            schema_path = root / "schemas/result-v1.schema.json"
            schema = json.loads(schema_path.read_text(encoding="utf-8"))
            schema["unevaluatedProperties"] = False
            _canonical_json(schema_path, schema)
            report = verify_repository(root)
        self.assertIn("schema-digest", {issue.code for issue in report.issues})

    def test_release_requires_a_code_commit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = _make_release(Path(temporary))
            manifest_path = root / "manifests/dataset-manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["release"]["code_commit"] = "UNSET"
            _canonical_json(manifest_path, manifest)
            report = verify_repository(root)
        self.assertIn("release-provenance", {issue.code for issue in report.issues})

    def test_checksum_inventory_must_match_manifest_exactly(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = _make_release(Path(temporary))
            (root / "SHA256SUMS").write_text(
                f"{'0' * 64}  results/fixture.json\n", encoding="utf-8"
            )
            report = verify_repository(root)
        self.assertIn("checksums-inventory", {issue.code for issue in report.issues})

    def test_record_schema_is_enforced(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = _make_release(Path(temporary))
            result_path = root / "results/fixture.json"
            payload = _result_payload()
            payload["status"] = "proved_unsat"
            _canonical_json(result_path, payload)
            _refresh_artifact_integrity(root)
            report = verify_repository(root)
        self.assertIn("schema-enum", {issue.code for issue in report.issues})

    def test_weakened_manifest_schema_is_rejected_by_pinned_digest(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = _make_release(Path(temporary))
            _canonical_json(
                root / "schemas/dataset-manifest-v1.schema.json",
                {
                    "$schema": "https://json-schema.org/draft/2020-12/schema",
                    "type": "object",
                },
            )
            manifest_path = root / "manifests/dataset-manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest.pop("dataset")
            manifest.pop("release")
            _canonical_json(manifest_path, manifest)
            report = verify_repository(root)
        self.assertIn("schema-digest", {issue.code for issue in report.issues})

    def test_alternate_manifest_schema_reference_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = _make_release(Path(temporary))
            _canonical_json(
                root / "schemas/permissive.json",
                {
                    "$schema": "https://json-schema.org/draft/2020-12/schema",
                    "type": "object",
                },
            )
            manifest_path = root / "manifests/dataset-manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["$schema"] = "schemas/permissive.json"
            _canonical_json(manifest_path, manifest)
            report = verify_repository(root)
        self.assertIn(
            "manifest-schema-reference", {issue.code for issue in report.issues}
        )

    def test_weakened_result_schema_is_rejected_by_pinned_digest(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = _make_release(Path(temporary))
            _canonical_json(
                root / "schemas/result-v1.schema.json",
                {
                    "$schema": "https://json-schema.org/draft/2020-12/schema",
                    "type": "object",
                },
            )
            report = verify_repository(root)
        self.assertIn("schema-digest", {issue.code for issue in report.issues})

    def test_hidden_managed_file_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = _make_release(Path(temporary))
            (root / "results/.secret-token").write_text("secret\n", encoding="utf-8")
            report = verify_repository(root)
        self.assertIn("managed-hidden", {issue.code for issue in report.issues})

    def test_gitkeep_is_allowed_only_for_development(self) -> None:
        development_report = verify_repository(REPOSITORY_ROOT)
        self.assertTrue(development_report.ok, development_report.issues)

        for status in ("candidate", "published"):
            with (
                self.subTest(status=status),
                tempfile.TemporaryDirectory() as temporary,
            ):
                root = _make_release(Path(temporary))
                (root / "results/.gitkeep").touch()
                manifest_path = root / "manifests/dataset-manifest.json"
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                manifest["release"]["status"] = status
                _canonical_json(manifest_path, manifest)
                report = verify_repository(root)
            self.assertIn(
                "managed-placeholder", {issue.code for issue in report.issues}
            )

    def test_zero_release_commit_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = _make_release(Path(temporary))
            manifest_path = root / "manifests/dataset-manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["release"]["code_commit"] = "0" * 40
            _canonical_json(manifest_path, manifest)
            report = verify_repository(root)
        codes = {issue.code for issue in report.issues}
        self.assertIn("schema-pattern", codes)
        self.assertIn("release-provenance", codes)

    def test_release_timestamp_must_be_canonical_utc_z(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = _make_release(Path(temporary))
            manifest_path = root / "manifests/dataset-manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["release"]["created_utc"] = "2026-07-13T23:00:00-04:00"
            _canonical_json(manifest_path, manifest)
            report = verify_repository(root)
        self.assertIn("schema-format", {issue.code for issue in report.issues})

    def test_zero_producer_commit_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = _make_release(Path(temporary))
            result_path = root / "results/fixture.json"
            payload = _result_payload()
            producer = payload["producer"]
            self.assertIsInstance(producer, dict)
            assert isinstance(producer, dict)
            producer["commit"] = "0" * 40
            _canonical_json(result_path, payload)
            _refresh_artifact_integrity(root)
            report = verify_repository(root)
        self.assertIn("schema-pattern", {issue.code for issue in report.issues})

    def test_witness_requires_nonempty_certificate(self) -> None:
        certificates: tuple[object, ...] = (None, {})
        for certificate in certificates:
            with (
                self.subTest(certificate=certificate),
                tempfile.TemporaryDirectory() as temporary,
            ):
                root = _make_release(Path(temporary))
                result_path = root / "results/fixture.json"
                payload = _result_payload()
                payload["certificate"] = certificate
                _canonical_json(result_path, payload)
                _refresh_artifact_integrity(root)
                report = verify_repository(root)
            self.assertIn("result-certificate", {issue.code for issue in report.issues})

    def test_nonwitness_status_rejects_witness_certificate(self) -> None:
        for status in ("candidate_unsat", "unknown", "error"):
            with (
                self.subTest(status=status),
                tempfile.TemporaryDirectory() as temporary,
            ):
                root = _make_release(Path(temporary))
                result_path = root / "results/fixture.json"
                payload = _result_payload()
                payload["status"] = status
                _canonical_json(result_path, payload)
                _refresh_artifact_integrity(root)
                report = verify_repository(root)
            self.assertIn("result-certificate", {issue.code for issue in report.issues})

    def test_result_artifact_requires_trusted_schema(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = _make_release(Path(temporary))
            manifest_path = root / "manifests/dataset-manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            del manifest["artifacts"][0]["schema"]
            _canonical_json(manifest_path, manifest)
            report = verify_repository(root)
        self.assertIn(
            "artifact-schema-required", {issue.code for issue in report.issues}
        )

    def test_strict_json_loader_rejects_constants_and_duplicate_keys(self) -> None:
        malformed_documents = (
            '{"value": NaN}\n',
            '{"value": Infinity}\n',
            '{"value": -Infinity}\n',
            '{"status": "error", "status": "witness"}\n',
        )
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "document.json"
            for document in malformed_documents:
                with self.subTest(document=document):
                    path.write_text(document, encoding="utf-8")
                    with self.assertRaises(json.JSONDecodeError):
                        _load_json(path)

    def test_manifest_rejects_nonstandard_constant_and_duplicate_key(self) -> None:
        mutations: tuple[Callable[[str], str], ...] = (
            lambda text: text.replace('"bytes": ', '"bytes": NaN, "ignored": ', 1),
            lambda text: text.replace(
                '"status": "candidate"',
                '"status": "error", "status": "candidate"',
                1,
            ),
        )
        for mutation in mutations:
            with (
                self.subTest(mutation=mutation),
                tempfile.TemporaryDirectory() as temporary,
            ):
                root = _make_release(Path(temporary))
                manifest_path = root / "manifests/dataset-manifest.json"
                manifest_path.write_text(
                    mutation(manifest_path.read_text(encoding="utf-8")),
                    encoding="utf-8",
                )
                report = verify_repository(root)
            self.assertIn("manifest-json", {issue.code for issue in report.issues})

    def test_result_rejects_nan_infinity_and_duplicate_keys(self) -> None:
        malformed_payloads: list[str] = []
        for value in (float("nan"), float("inf"), float("-inf")):
            payload = _result_payload()
            parameters = payload["parameters"]
            self.assertIsInstance(parameters, dict)
            assert isinstance(parameters, dict)
            parameters["timeout"] = value
            malformed_payloads.append(json.dumps(payload, allow_nan=True) + "\n")
        malformed_payloads.append(
            json.dumps(_result_payload(), sort_keys=True).replace(
                '"status": "witness"',
                '"status": "error", "status": "witness"',
            )
            + "\n"
        )
        for document in malformed_payloads:
            with (
                self.subTest(document=document),
                tempfile.TemporaryDirectory() as temporary,
            ):
                root = _make_release(Path(temporary))
                (root / "results/fixture.json").write_text(document, encoding="utf-8")
                _refresh_artifact_integrity(root)
                report = verify_repository(root)
            self.assertIn("artifact-json", {issue.code for issue in report.issues})

    def test_result_producer_must_match_release_provenance(self) -> None:
        mutations = (
            (
                "repository",
                "https://example.invalid/other-toolkit",
                "result-producer-repository",
            ),
            ("commit", "c" * 40, "result-producer-commit"),
        )
        for field, value, expected_code in mutations:
            with (
                self.subTest(field=field),
                tempfile.TemporaryDirectory() as temporary,
            ):
                root = _make_release(Path(temporary))
                result_path = root / "results/fixture.json"
                payload = _result_payload()
                producer = payload["producer"]
                self.assertIsInstance(producer, dict)
                assert isinstance(producer, dict)
                producer[field] = value
                _canonical_json(result_path, payload)
                _refresh_artifact_integrity(root)
                report = verify_repository(root)
            self.assertIn(expected_code, {issue.code for issue in report.issues})

    def test_duplicate_record_id_across_result_artifacts_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = _make_release(Path(temporary))
            second_result = root / "results/fixture-2.json"
            _canonical_json(second_result, _result_payload())
            second_digest = _sha256(second_result)
            manifest_path = root / "manifests/dataset-manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["artifacts"].insert(
                0,
                {
                    "path": "results/fixture-2.json",
                    "role": "result",
                    "media_type": "application/json",
                    "bytes": second_result.stat().st_size,
                    "sha256": second_digest,
                    "schema": "schemas/result-v1.schema.json",
                    "records": 1,
                    "description": "Duplicate identifier fixture.",
                },
            )
            manifest["artifacts"].sort(key=lambda artifact: artifact["path"])
            _canonical_json(manifest_path, manifest)
            first_digest = _sha256(root / "results/fixture.json")
            (root / "SHA256SUMS").write_text(
                f"{second_digest}  results/fixture-2.json\n"
                f"{first_digest}  results/fixture.json\n",
                encoding="utf-8",
            )
            report = verify_repository(root)
        self.assertIn(
            "result-record-id-duplicate", {issue.code for issue in report.issues}
        )


if __name__ == "__main__":
    unittest.main()
