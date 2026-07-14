#!/usr/bin/env python3
"""Verify a Total Coloring Data release using only the Python standard library.

The verifier intentionally does not import the production toolkit. It checks a
small, explicitly supported subset of JSON Schema Draft 2020-12 and rejects
unsupported schema keywords instead of silently ignoring them.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import urlsplit

MANIFEST_PATH = PurePosixPath("manifests/dataset-manifest.json")
CHECKSUMS_PATH = PurePosixPath("SHA256SUMS")
MANIFEST_SCHEMA_PATH = PurePosixPath("schemas/dataset-manifest-v1.schema.json")
RESULT_SCHEMA_PATH = PurePosixPath("schemas/result-v1.schema.json")
TRUSTED_SCHEMA_DIGESTS = {
    MANIFEST_SCHEMA_PATH: (
        "d820fadf9dfb1de44c81c1cf9baea43b95de8fc360448e02d2c16461cb747133"
    ),
    RESULT_SCHEMA_PATH: (
        "56acf75e9d41a64d1c2bf8d2e2651cb12a7fdefe7eac0ed55397dc231e36139a"
    ),
}
SUPPORTED_SCHEMA_URI = "https://json-schema.org/draft/2020-12/schema"
SUPPORTED_SCHEMA_KEYS = frozenset(
    {
        "$schema",
        "$id",
        "title",
        "description",
        "type",
        "additionalProperties",
        "required",
        "properties",
        "items",
        "const",
        "enum",
        "pattern",
        "format",
        "minLength",
        "minimum",
    }
)


@dataclass(frozen=True, slots=True)
class VerificationIssue:
    code: str
    location: str
    message: str


@dataclass(frozen=True, slots=True)
class VerificationReport:
    root: str
    manifest: str
    artifact_count: int
    issues: tuple[VerificationIssue, ...]

    @property
    def ok(self) -> bool:
        return not self.issues


def _issue(
    issues: list[VerificationIssue], code: str, location: str, message: str
) -> None:
    issues.append(VerificationIssue(code=code, location=location, message=message))


def _reject_json_constant(value: str) -> None:
    raise json.JSONDecodeError(f"nonstandard JSON constant {value!r}", value, 0)


def _reject_duplicate_json_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise json.JSONDecodeError(f"duplicate JSON object key {key!r}", key, 0)
        result[key] = value
    return result


def _load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(
            handle,
            parse_constant=_reject_json_constant,
            object_pairs_hook=_reject_duplicate_json_keys,
        )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_digest(value: Any) -> str:
    payload = json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _safe_relative_path(value: str) -> PurePosixPath | None:
    if not value or "\\" in value or any(ord(character) < 32 for character in value):
        return None
    path = PurePosixPath(value)
    if path.is_absolute() or str(path) != value:
        return None
    if any(part in {"", ".", ".."} for part in path.parts):
        return None
    return path


def _type_matches(instance: Any, expected: str) -> bool:
    if expected == "object":
        return isinstance(instance, dict)
    if expected == "array":
        return isinstance(instance, list)
    if expected == "string":
        return isinstance(instance, str)
    if expected == "integer":
        return isinstance(instance, int) and not isinstance(instance, bool)
    if expected == "number":
        return isinstance(instance, (int, float)) and not isinstance(instance, bool)
    if expected == "boolean":
        return isinstance(instance, bool)
    if expected == "null":
        return instance is None
    raise ValueError(f"unsupported JSON Schema type {expected!r}")


def _format_matches(value: str, format_name: str) -> bool:
    if format_name == "sha256":
        return re.fullmatch(r"[0-9a-f]{64}", value) is not None
    if format_name == "relative-path":
        return _safe_relative_path(value) is not None
    if format_name == "uri":
        parsed = urlsplit(value)
        return parsed.scheme in {"http", "https"} and bool(parsed.netloc)
    if format_name == "date-time":
        try:
            parsed_time = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return False
        return parsed_time.tzinfo is not None
    if format_name == "utc-date-time":
        if (
            re.fullmatch(
                r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z", value
            )
            is None
        ):
            return False
        try:
            datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
        except ValueError:
            return False
        return True
    raise ValueError(f"unsupported JSON Schema format {format_name!r}")


def _validate_schema_definition(
    schema: Any, location: str, issues: list[VerificationIssue]
) -> None:
    if not isinstance(schema, dict):
        _issue(issues, "schema-definition", location, "schema node must be an object")
        return
    unsupported = sorted(set(schema) - SUPPORTED_SCHEMA_KEYS)
    if unsupported:
        _issue(
            issues,
            "schema-keyword",
            location,
            "unsupported schema keyword(s): " + ", ".join(unsupported),
        )
    schema_uri = schema.get("$schema")
    if schema_uri is not None and schema_uri != SUPPORTED_SCHEMA_URI:
        _issue(
            issues, "schema-version", location, f"unsupported $schema {schema_uri!r}"
        )
    properties = schema.get("properties", {})
    if properties is not None and not isinstance(properties, dict):
        _issue(issues, "schema-definition", location, "properties must be an object")
    elif isinstance(properties, dict):
        for key, child in properties.items():
            _validate_schema_definition(
                child, f"{location}.properties[{key!r}]", issues
            )
    items = schema.get("items")
    if items is not None:
        _validate_schema_definition(items, f"{location}.items", issues)


def _validate_instance(
    instance: Any,
    schema: dict[str, Any],
    location: str,
    issues: list[VerificationIssue],
) -> None:
    expected_types = schema.get("type")
    allowed_types: tuple[str, ...]
    if isinstance(expected_types, str):
        allowed_types = (expected_types,)
    elif isinstance(expected_types, list) and all(
        isinstance(item, str) for item in expected_types
    ):
        allowed_types = tuple(expected_types)
    elif expected_types is None:
        allowed_types = ()
    else:
        _issue(
            issues,
            "schema-definition",
            location,
            "type must be a string or string array",
        )
        return
    if allowed_types:
        try:
            matches = any(
                _type_matches(instance, expected) for expected in allowed_types
            )
        except ValueError as error:
            _issue(issues, "schema-definition", location, str(error))
            return
        if not matches:
            _issue(
                issues,
                "schema-type",
                location,
                f"expected {' or '.join(allowed_types)}, found {type(instance).__name__}",
            )
            return

    if "const" in schema and instance != schema["const"]:
        _issue(issues, "schema-const", location, f"expected {schema['const']!r}")
    if "enum" in schema and instance not in schema["enum"]:
        _issue(issues, "schema-enum", location, f"value {instance!r} is not permitted")

    if isinstance(instance, str):
        minimum_length = schema.get("minLength")
        if isinstance(minimum_length, int) and len(instance) < minimum_length:
            _issue(
                issues, "schema-length", location, f"minimum length is {minimum_length}"
            )
        pattern = schema.get("pattern")
        if isinstance(pattern, str) and re.search(pattern, instance) is None:
            _issue(issues, "schema-pattern", location, f"does not match {pattern!r}")
        format_name = schema.get("format")
        if isinstance(format_name, str):
            try:
                format_ok = _format_matches(instance, format_name)
            except ValueError as error:
                _issue(issues, "schema-definition", location, str(error))
            else:
                if not format_ok:
                    _issue(issues, "schema-format", location, f"invalid {format_name}")

    minimum = schema.get("minimum")
    if (
        minimum is not None
        and isinstance(instance, (int, float))
        and not isinstance(instance, bool)
    ):
        if instance < minimum:
            _issue(issues, "schema-minimum", location, f"minimum is {minimum}")

    if isinstance(instance, dict):
        required = schema.get("required", [])
        if not isinstance(required, list) or not all(
            isinstance(item, str) for item in required
        ):
            _issue(
                issues, "schema-definition", location, "required must be a string array"
            )
            required = []
        for key in required:
            if key not in instance:
                _issue(
                    issues,
                    "schema-required",
                    location,
                    f"missing required property {key!r}",
                )
        properties = schema.get("properties", {})
        if not isinstance(properties, dict):
            return
        if schema.get("additionalProperties") is False:
            for key in sorted(set(instance) - set(properties)):
                _issue(
                    issues,
                    "schema-additional",
                    f"{location}.{key}",
                    "property is not allowed",
                )
        for key, child_schema in properties.items():
            if key in instance and isinstance(child_schema, dict):
                _validate_instance(
                    instance[key], child_schema, f"{location}.{key}", issues
                )

    if isinstance(instance, list):
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for index, value in enumerate(instance):
                _validate_instance(value, item_schema, f"{location}[{index}]", issues)


def _resolve_regular_file(
    root: Path,
    relative: PurePosixPath,
    location: str,
    issues: list[VerificationIssue],
) -> Path | None:
    candidate = root.joinpath(*relative.parts)
    current = root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            _issue(issues, "symlink", location, f"symlink is forbidden: {relative}")
            return None
    if not candidate.is_file():
        _issue(issues, "missing-file", location, f"regular file not found: {relative}")
        return None
    try:
        candidate.resolve(strict=True).relative_to(root.resolve(strict=True))
    except (OSError, ValueError):
        _issue(issues, "path-escape", location, f"path escapes repository: {relative}")
        return None
    return candidate


def _load_trusted_schema(
    root: Path,
    relative: PurePosixPath,
    location: str,
    issues: list[VerificationIssue],
) -> dict[str, Any] | None:
    """Load a schema only when its canonical content matches the trust store."""

    expected_digest = TRUSTED_SCHEMA_DIGESTS.get(relative)
    if expected_digest is None:
        _issue(
            issues,
            "schema-untrusted",
            location,
            f"schema is not trusted by this verifier: {relative}",
        )
        return None
    schema_file = _resolve_regular_file(root, relative, location, issues)
    if schema_file is None:
        return None
    try:
        schema = _load_json(schema_file)
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        _issue(issues, "schema-json", str(relative), str(error))
        return None
    actual_digest = _canonical_digest(schema)
    if actual_digest != expected_digest:
        _issue(
            issues,
            "schema-digest",
            location,
            f"expected {expected_digest}, found {actual_digest}",
        )
        return None
    _validate_schema_definition(schema, location, issues)
    if not isinstance(schema, dict):
        _issue(issues, "schema-definition", location, "schema must be an object")
        return None
    return schema


def _is_nonzero_git_commit(value: object) -> bool:
    return (
        isinstance(value, str)
        and re.fullmatch(r"[0-9a-f]{40}", value) is not None
        and value != "0" * 40
    )


def _is_json_media_type(value: object) -> bool:
    if not isinstance(value, str):
        return False
    base_type = value.partition(";")[0].strip().lower()
    return base_type == "application/json" or base_type.endswith("+json")


def _has_hidden_component(path: PurePosixPath) -> bool:
    return any(part.startswith(".") for part in path.parts)


def _validate_result_semantics(
    record: Any,
    location: str,
    expected_repository: object,
    expected_commit: object,
    issues: list[VerificationIssue],
) -> None:
    """Enforce cross-field claims independently of JSON Schema.

    producer.version is descriptive package metadata and is intentionally not
    compared with the dataset release version. Repository and commit are exact
    provenance bindings and must match the release envelope.
    """

    if not isinstance(record, dict):
        return
    status = record.get("status")
    certificate = record.get("certificate")
    producer = record.get("producer")
    if isinstance(producer, dict):
        if producer.get("repository") != expected_repository:
            _issue(
                issues,
                "result-producer-repository",
                f"{location}.producer.repository",
                "must equal release.code_repository",
            )
        if producer.get("commit") != expected_commit:
            _issue(
                issues,
                "result-producer-commit",
                f"{location}.producer.commit",
                "must equal release.code_commit",
            )
    if status == "witness":
        if not isinstance(certificate, dict) or not certificate:
            _issue(
                issues,
                "result-certificate",
                f"{location}.certificate",
                "witness status requires a nonempty certificate object",
            )
    elif status in {"candidate_unsat", "unknown", "error"} and certificate is not None:
        _issue(
            issues,
            "result-certificate",
            f"{location}.certificate",
            f"{status} status requires a null certificate",
        )


def _parse_checksums(path: Path, issues: list[VerificationIssue]) -> dict[str, str]:
    result: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as error:
        _issue(issues, "checksums-read", str(CHECKSUMS_PATH), str(error))
        return result
    for line_number, line in enumerate(lines, start=1):
        if not line or line.startswith("#"):
            continue
        match = re.fullmatch(r"([0-9a-f]{64})  (.+)", line)
        location = f"{CHECKSUMS_PATH}:{line_number}"
        if match is None:
            _issue(issues, "checksums-format", location, "expected '<sha256>  <path>'")
            continue
        digest, raw_path = match.groups()
        relative = _safe_relative_path(raw_path)
        if relative is None:
            _issue(issues, "checksums-path", location, f"unsafe path {raw_path!r}")
            continue
        if raw_path in result:
            _issue(
                issues, "checksums-duplicate", location, f"duplicate path {raw_path!r}"
            )
            continue
        result[raw_path] = digest
    if list(result) != sorted(result):
        _issue(
            issues,
            "checksums-order",
            str(CHECKSUMS_PATH),
            "entries must be path-sorted",
        )
    return result


def _managed_files(
    root: Path,
    managed_roots: list[str],
    release_status: object,
    issues: list[VerificationIssue],
) -> set[str]:
    found: set[str] = set()
    for root_name in managed_roots:
        managed = root / root_name
        if managed.is_symlink() or not managed.is_dir():
            _issue(
                issues,
                "managed-root",
                root_name,
                "managed root must be a real directory",
            )
            continue
        for directory, directory_names, file_names in os.walk(
            managed, followlinks=False
        ):
            directory_path = Path(directory)
            for name in tuple(directory_names):
                child = directory_path / name
                if child.is_symlink():
                    _issue(
                        issues,
                        "symlink",
                        str(child.relative_to(root)),
                        "directory symlink forbidden",
                    )
                    directory_names.remove(name)
                elif name.startswith("."):
                    _issue(
                        issues,
                        "managed-hidden",
                        str(child.relative_to(root)),
                        "hidden directories are forbidden in managed roots",
                    )
                    directory_names.remove(name)
            for name in file_names:
                child = directory_path / name
                relative = child.relative_to(root).as_posix()
                if child.is_symlink() or not child.is_file():
                    _issue(
                        issues,
                        "managed-file",
                        relative,
                        "must be a regular non-symlink file",
                    )
                    continue
                if name.startswith("."):
                    if name == ".gitkeep":
                        if release_status == "development":
                            continue
                        _issue(
                            issues,
                            "managed-placeholder",
                            relative,
                            ".gitkeep is permitted only for development releases",
                        )
                    else:
                        _issue(
                            issues,
                            "managed-hidden",
                            relative,
                            "hidden files are forbidden in managed roots",
                        )
                    continue
                found.add(relative)
    return found


def verify_repository(root: Path) -> VerificationReport:
    issues: list[VerificationIssue] = []
    root = root.resolve()
    manifest_file = _resolve_regular_file(
        root, MANIFEST_PATH, str(MANIFEST_PATH), issues
    )
    if manifest_file is None:
        return VerificationReport(str(root), str(MANIFEST_PATH), 0, tuple(issues))
    try:
        manifest = _load_json(manifest_file)
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        _issue(issues, "manifest-json", str(MANIFEST_PATH), str(error))
        return VerificationReport(str(root), str(MANIFEST_PATH), 0, tuple(issues))
    if not isinstance(manifest, dict):
        _issue(
            issues, "manifest-type", str(MANIFEST_PATH), "manifest must be an object"
        )
        return VerificationReport(str(root), str(MANIFEST_PATH), 0, tuple(issues))

    schema_reference = manifest.get("$schema")
    if schema_reference != MANIFEST_SCHEMA_PATH.as_posix():
        _issue(
            issues,
            "manifest-schema-reference",
            str(MANIFEST_PATH),
            f"$schema must be exactly {MANIFEST_SCHEMA_PATH.as_posix()!r}",
        )
        return VerificationReport(str(root), str(MANIFEST_PATH), 0, tuple(issues))
    schema = _load_trusted_schema(root, MANIFEST_SCHEMA_PATH, "$schema", issues)
    if schema is None:
        return VerificationReport(str(root), str(MANIFEST_PATH), 0, tuple(issues))
    _validate_instance(manifest, schema, "$manifest", issues)

    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, list):
        artifacts = []
    paths = [
        raw_path
        for artifact in artifacts
        if isinstance(artifact, dict)
        and isinstance(raw_path := artifact.get("path"), str)
    ]
    if paths != sorted(paths):
        _issue(
            issues, "artifact-order", "artifacts", "artifacts must be sorted by path"
        )
    if len(paths) != len(set(paths)):
        _issue(
            issues, "artifact-duplicate", "artifacts", "artifact paths must be unique"
        )

    release = manifest.get("release", {})
    release_status = release.get("status") if isinstance(release, dict) else None
    release_repository = (
        release.get("code_repository") if isinstance(release, dict) else None
    )
    release_commit = release.get("code_commit") if isinstance(release, dict) else None
    if release_status in {"candidate", "published"}:
        if not _is_nonzero_git_commit(release.get("code_commit")):
            _issue(
                issues,
                "release-provenance",
                "release.code_commit",
                "candidate and published releases require a nonzero 40-hex commit",
            )

    managed_roots = manifest.get("managed_roots")
    if not isinstance(managed_roots, list) or not all(
        isinstance(item, str) for item in managed_roots
    ):
        managed_roots = []
    expected_hashes: dict[str, str] = {}
    result_record_locations: dict[str, str] = {}
    for index, artifact in enumerate(artifacts):
        location = f"artifacts[{index}]"
        if not isinstance(artifact, dict):
            continue
        raw_path = artifact.get("path")
        relative = _safe_relative_path(raw_path) if isinstance(raw_path, str) else None
        if relative is None:
            continue
        if _has_hidden_component(relative):
            _issue(
                issues,
                "artifact-hidden",
                f"{location}.path",
                "artifact paths may not contain hidden components",
            )
            continue
        if not relative.parts or relative.parts[0] not in managed_roots:
            _issue(
                issues,
                "artifact-root",
                f"{location}.path",
                "path is outside managed roots",
            )
            continue
        artifact_file = _resolve_regular_file(
            root, relative, f"{location}.path", issues
        )
        if artifact_file is None:
            continue
        expected_bytes = artifact.get("bytes")
        actual_bytes = artifact_file.stat().st_size
        if isinstance(expected_bytes, int) and not isinstance(expected_bytes, bool):
            if actual_bytes != expected_bytes:
                _issue(
                    issues,
                    "artifact-bytes",
                    str(relative),
                    f"expected {expected_bytes}, found {actual_bytes}",
                )
        expected_hash = artifact.get("sha256")
        if isinstance(expected_hash, str):
            expected_hashes[str(relative)] = expected_hash
            actual_hash = _sha256(artifact_file)
            if actual_hash != expected_hash:
                _issue(
                    issues,
                    "artifact-hash",
                    str(relative),
                    f"expected {expected_hash}, found {actual_hash}",
                )

        raw_record_schema = artifact.get("schema")
        role = artifact.get("role")
        if role == "result":
            if not _is_json_media_type(artifact.get("media_type")):
                _issue(
                    issues,
                    "result-media-type",
                    f"{location}.media_type",
                    "result artifacts require a JSON media type with a trusted schema",
                )
            if not isinstance(raw_record_schema, str):
                _issue(
                    issues,
                    "artifact-schema-required",
                    f"{location}.schema",
                    "machine-readable result artifacts require a trusted schema",
                )
            elif raw_record_schema != RESULT_SCHEMA_PATH.as_posix():
                _issue(
                    issues,
                    "result-schema",
                    f"{location}.schema",
                    f"result artifacts must use {RESULT_SCHEMA_PATH.as_posix()}",
                )
        if isinstance(raw_record_schema, str):
            record_schema_relative = _safe_relative_path(raw_record_schema)
            if (
                record_schema_relative is None
                or record_schema_relative.parts[0] != "schemas"
            ):
                _issue(
                    issues,
                    "artifact-schema",
                    f"{location}.schema",
                    "schema path must be under schemas/",
                )
                continue
            record_schema = _load_trusted_schema(
                root, record_schema_relative, f"{location}.schema", issues
            )
            if record_schema is None:
                continue
            try:
                record = _load_json(artifact_file)
            except (OSError, UnicodeError, json.JSONDecodeError) as error:
                _issue(issues, "artifact-json", str(relative), str(error))
                continue
            _validate_instance(record, record_schema, str(relative), issues)
            if record_schema_relative == RESULT_SCHEMA_PATH:
                _validate_result_semantics(
                    record,
                    str(relative),
                    release_repository,
                    release_commit,
                    issues,
                )
                if isinstance(record, dict) and isinstance(
                    record_id := record.get("record_id"), str
                ):
                    previous = result_record_locations.get(record_id)
                    if previous is not None:
                        _issue(
                            issues,
                            "result-record-id-duplicate",
                            f"{relative}.record_id",
                            f"duplicate {record_id!r}; first declared at {previous}",
                        )
                    else:
                        result_record_locations[record_id] = str(relative)
            declared_records = artifact.get("records")
            if isinstance(declared_records, int) and not isinstance(
                declared_records, bool
            ):
                actual_records = len(record) if isinstance(record, list) else 1
                if declared_records != actual_records:
                    _issue(
                        issues,
                        "artifact-records",
                        str(relative),
                        f"expected {declared_records}, found {actual_records}",
                    )

    checksums_file = _resolve_regular_file(
        root, CHECKSUMS_PATH, str(CHECKSUMS_PATH), issues
    )
    actual_checksums = (
        _parse_checksums(checksums_file, issues) if checksums_file else {}
    )
    if actual_checksums != expected_hashes:
        missing = sorted(set(expected_hashes) - set(actual_checksums))
        extra = sorted(set(actual_checksums) - set(expected_hashes))
        mismatched = sorted(
            path
            for path in set(expected_hashes) & set(actual_checksums)
            if expected_hashes[path] != actual_checksums[path]
        )
        _issue(
            issues,
            "checksums-inventory",
            str(CHECKSUMS_PATH),
            f"missing={missing}, extra={extra}, mismatched={mismatched}",
        )

    actual_managed = _managed_files(root, managed_roots, release_status, issues)
    declared_managed = set(paths)
    if actual_managed != declared_managed:
        _issue(
            issues,
            "managed-inventory",
            "managed_roots",
            f"unlisted={sorted(actual_managed - declared_managed)}, missing={sorted(declared_managed - actual_managed)}",
        )

    return VerificationReport(
        str(root), str(MANIFEST_PATH), len(artifacts), tuple(issues)
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="repository root")
    parser.add_argument(
        "--json", action="store_true", help="emit machine-readable report"
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    report = verify_repository(args.root)
    if args.json:
        print(json.dumps(asdict(report), indent=2, sort_keys=True))
    elif report.ok:
        print(f"OK: {report.artifact_count} artifact(s) verified under {report.root}")
    else:
        print(f"FAILED: {len(report.issues)} verification issue(s)", file=sys.stderr)
        for issue in report.issues:
            print(
                f"  [{issue.code}] {issue.location}: {issue.message}", file=sys.stderr
            )
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
