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
import math
import os
import re
import sys
import tarfile
import zlib
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any, cast
from urllib.parse import urlsplit

MANIFEST_PATH = PurePosixPath("manifests/dataset-manifest.json")
CHECKSUMS_PATH = PurePosixPath("SHA256SUMS")
DEFAULT_EXPECTED_CODE_REPOSITORY = "https://github.com/chenle02/total-coloring-toolkit"
MANIFEST_V1_SCHEMA_PATH = PurePosixPath("schemas/dataset-manifest-v1.schema.json")
MANIFEST_V2_SCHEMA_PATH = PurePosixPath("schemas/dataset-manifest-v2.schema.json")
RESULT_SCHEMA_PATH = PurePosixPath("schemas/result-v1.schema.json")
UNIVERSAL_SUMMARY_SCHEMA_PATH = PurePosixPath(
    "schemas/universal-census-summary-v1.schema.json"
)
TRUSTED_MANIFEST_SCHEMAS = frozenset({MANIFEST_V1_SCHEMA_PATH, MANIFEST_V2_SCHEMA_PATH})
TRUSTED_RESULT_SCHEMAS = frozenset({RESULT_SCHEMA_PATH, UNIVERSAL_SUMMARY_SCHEMA_PATH})
TRUSTED_SCHEMA_DIGESTS = {
    MANIFEST_V1_SCHEMA_PATH: (
        "f8adbf0081e768a1e15d2f88f249afd1c0eb422e4ebfd4ec840fb28e50b400e2"
    ),
    MANIFEST_V2_SCHEMA_PATH: (
        "60351bf5daeda4d119678896cbe2a5771d451aaf279c4ae12f9f99dfd4c657fd"
    ),
    RESULT_SCHEMA_PATH: (
        "56acf75e9d41a64d1c2bf8d2e2651cb12a7fdefe7eac0ed55397dc231e36139a"
    ),
    UNIVERSAL_SUMMARY_SCHEMA_PATH: (
        "3c62b94577b715c74e6cd70421c189332f10f242ffa2b7f2edf2e0f5e6186f09"
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
        "minItems",
        "maxItems",
        "minimum",
    }
)

_MAX_JSON_DOCUMENT_BYTES = 16 * 1024 * 1024
_MAX_JSON_INTEGER_DIGITS = 128
_MAX_JSON_NESTING_DEPTH = 128
_MAX_UNIVERSAL_RECORD_BYTES = 16 * 1024 * 1024
_MAX_SMALL_ARCHIVE_MEMBER_BYTES = 4 * 1024 * 1024
_MAX_REPLAY_UNCOMPRESSED_BYTES = 16 * 1024 * 1024 * 1024
_MAX_CHECKSUM_FILE_BYTES = 4 * 1024 * 1024
_MAX_CHECKSUM_LINE_BYTES = 4096
_MAX_UNIVERSAL_RUNS = 256
_MAX_VERIFICATION_ISSUES = 1000
_CANONICAL_MANAGED_ROOTS = ("reports", "results")
_RFC3986_LITERAL_PCHAR = re.compile(r"[A-Za-z0-9._~!$&'()*+,;=:@-]+")
_TAR_BLOCK_SIZE = 512
_TAR_RECORD_SIZE = 10_240
_CANONICAL_GZIP_HEADER = b"\x1f\x8b\x08\x00\x00\x00\x00\x00\x02\xff"
_UNTRUSTED_SEMANTIC_ERRORS = (
    TypeError,
    KeyError,
    IndexError,
    AttributeError,
    AssertionError,
    ValueError,
    RecursionError,
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
    external_artifact_count: int = 0
    external_files_verified: int = 0

    @property
    def ok(self) -> bool:
        return not self.issues


@dataclass(frozen=True, slots=True)
class _RecordScan:
    sha256: str
    byte_count: int
    record_count: int
    partition_count: int
    check_evaluations: int
    counts: dict[str, int]


def _issue(
    issues: list[VerificationIssue], code: str, location: str, message: str
) -> None:
    if len(issues) >= _MAX_VERIFICATION_ISSUES:
        return
    if len(issues) == _MAX_VERIFICATION_ISSUES - 1:
        issues.append(
            VerificationIssue(
                code="issue-limit",
                location="$verifier",
                message=(
                    f"stopped recording issues at {_MAX_VERIFICATION_ISSUES}; "
                    "the release remains invalid"
                ),
            )
        )
        return
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


def _parse_finite_json_float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed):
        raise json.JSONDecodeError(f"nonfinite JSON number {value!r}", value, 0)
    return parsed


def _parse_bounded_json_int(value: str) -> int:
    digits = value[1:] if value.startswith("-") else value
    if len(digits) > _MAX_JSON_INTEGER_DIGITS:
        raise json.JSONDecodeError(
            f"JSON integer exceeds {_MAX_JSON_INTEGER_DIGITS} digits", value, 0
        )
    try:
        return int(value)
    except ValueError as error:
        raise json.JSONDecodeError(
            f"invalid JSON integer {value!r}", value, 0
        ) from error


def _validate_json_nesting(value: bytes) -> None:
    depth = 0
    in_string = False
    escaped = False
    for byte in value:
        if in_string:
            if escaped:
                escaped = False
            elif byte == 0x5C:
                escaped = True
            elif byte == 0x22:
                in_string = False
            continue
        if byte == 0x22:
            in_string = True
        elif byte in {0x5B, 0x7B}:
            depth += 1
            if depth > _MAX_JSON_NESTING_DEPTH:
                raise json.JSONDecodeError(
                    f"JSON nesting exceeds {_MAX_JSON_NESTING_DEPTH}",
                    value.decode("utf-8", errors="replace"),
                    0,
                )
        elif byte in {0x5D, 0x7D}:
            depth -= 1


def _reject_lone_surrogates(value: Any) -> None:
    pending = [value]
    while pending:
        current = pending.pop()
        if isinstance(current, str):
            if any(0xD800 <= ord(character) <= 0xDFFF for character in current):
                raise json.JSONDecodeError(
                    "JSON strings must not contain lone UTF-16 surrogates", "", 0
                )
        elif isinstance(current, dict):
            pending.extend(current.keys())
            pending.extend(current.values())
        elif isinstance(current, (list, tuple)):
            pending.extend(current)


def _strict_json_load_bytes(value: bytes, *, max_bytes: int) -> Any:
    if len(value) > max_bytes:
        raise json.JSONDecodeError(f"JSON document exceeds {max_bytes} bytes", "", 0)
    _validate_json_nesting(value)
    try:
        parsed = json.loads(
            value,
            parse_constant=_reject_json_constant,
            parse_float=_parse_finite_json_float,
            parse_int=_parse_bounded_json_int,
            object_pairs_hook=_reject_duplicate_json_keys,
        )
        _reject_lone_surrogates(parsed)
        return parsed
    except RecursionError as error:
        raise json.JSONDecodeError(
            "JSON nesting exceeds parser limits", "", 0
        ) from error


def _load_json(path: Path) -> Any:
    with path.open("rb") as handle:
        value = handle.read(_MAX_JSON_DOCUMENT_BYTES + 1)
    return _strict_json_load_bytes(value, max_bytes=_MAX_JSON_DOCUMENT_BYTES)


def _load_json_bytes(value: bytes) -> Any:
    return _strict_json_load_bytes(value, max_bytes=_MAX_UNIVERSAL_RECORD_BYTES)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_digest(value: Any) -> str:
    return hashlib.sha256(_canonical_json_bytes(value)).hexdigest()


def _canonical_json_bytes(value: Any) -> bytes:
    _reject_lone_surrogates(value)
    try:
        return json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except UnicodeEncodeError as error:
        raise ValueError("canonical JSON is not valid UTF-8") from error


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


def _json_equal(left: Any, right: Any) -> bool:
    """Compare JSON values without Python's bool/int equality coercion."""

    if type(left) is not type(right):
        return False
    if isinstance(left, dict):
        return left.keys() == right.keys() and all(
            _json_equal(value, right[key]) for key, value in left.items()
        )
    if isinstance(left, list):
        return len(left) == len(right) and all(
            _json_equal(left_item, right_item)
            for left_item, right_item in zip(left, right, strict=True)
        )
    return bool(left == right)


def _format_matches(value: str, format_name: str) -> bool:
    if format_name == "sha256":
        return re.fullmatch(r"[0-9a-f]{64}", value) is not None
    if format_name == "relative-path":
        return _safe_relative_path(value) is not None
    if format_name == "uri":
        try:
            parsed = urlsplit(value)
        except ValueError:
            return False
        return parsed.scheme in {"http", "https"} and bool(parsed.netloc)
    if format_name == "https-uri":
        if (
            not value.startswith("https://")
            or any(
                character.isspace() or ord(character) < 32 or ord(character) == 127
                for character in value
            )
            or "\\" in value
            or "%" in value
            or "?" in value
            or "#" in value
            or not value.isascii()
        ):
            return False
        try:
            parsed = urlsplit(value)
            port = parsed.port
        except ValueError:
            return False
        hostname = parsed.hostname
        if (
            parsed.scheme != "https"
            or not hostname
            or parsed.username is not None
            or parsed.password is not None
            or port is not None
            or parsed.query
            or parsed.fragment
            or parsed.netloc != hostname
            or hostname != hostname.lower()
        ):
            return False
        labels = hostname.split(".")
        if (
            len(hostname) > 253
            or len(labels) < 2
            or any(
                len(label) > 63
                or re.fullmatch(r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?", label) is None
                for label in labels
            )
        ):
            return False
        if not parsed.path.startswith("/") or parsed.path in {"", "/"}:
            return False
        parts = parsed.path.split("/")[1:]
        return bool(parts) and all(
            part not in {"", ".", ".."}
            and _RFC3986_LITERAL_PCHAR.fullmatch(part) is not None
            for part in parts
        )
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
    for keyword in ("minItems", "maxItems"):
        bound = schema.get(keyword)
        if bound is not None and (
            not isinstance(bound, int) or isinstance(bound, bool) or bound < 0
        ):
            _issue(
                issues,
                "schema-definition",
                location,
                f"{keyword} must be a nonnegative integer",
            )
    if (
        isinstance(schema.get("minItems"), int)
        and isinstance(schema.get("maxItems"), int)
        and schema["minItems"] > schema["maxItems"]
    ):
        _issue(
            issues,
            "schema-definition",
            location,
            "minItems may not exceed maxItems",
        )


def _validate_instance(
    instance: Any,
    schema: dict[str, Any],
    location: str,
    issues: list[VerificationIssue],
) -> None:
    if len(issues) >= _MAX_VERIFICATION_ISSUES:
        return
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

    if "const" in schema and not _json_equal(instance, schema["const"]):
        _issue(issues, "schema-const", location, f"expected {schema['const']!r}")
    if "enum" in schema and not any(
        _json_equal(instance, candidate) for candidate in schema["enum"]
    ):
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
            if len(issues) >= _MAX_VERIFICATION_ISSUES:
                return
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
                if len(issues) >= _MAX_VERIFICATION_ISSUES:
                    return
                _issue(
                    issues,
                    "schema-additional",
                    f"{location}.{key}",
                    "property is not allowed",
                )
        for key, child_schema in properties.items():
            if len(issues) >= _MAX_VERIFICATION_ISSUES:
                return
            if key in instance and isinstance(child_schema, dict):
                _validate_instance(
                    instance[key], child_schema, f"{location}.{key}", issues
                )

    if isinstance(instance, list):
        minimum_items = schema.get("minItems")
        if isinstance(minimum_items, int) and len(instance) < minimum_items:
            _issue(
                issues,
                "schema-items",
                location,
                f"minimum item count is {minimum_items}",
            )
        maximum_items = schema.get("maxItems")
        if isinstance(maximum_items, int) and len(instance) > maximum_items:
            _issue(
                issues,
                "schema-items",
                location,
                f"maximum item count is {maximum_items}",
            )
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            validated_items = instance
            validation_limit: int | None = None
            if (
                isinstance(maximum_items, int)
                and not isinstance(maximum_items, bool)
                and maximum_items >= 0
            ):
                validation_limit = maximum_items
            const_value = schema.get("const")
            if isinstance(const_value, list):
                const_limit = len(const_value)
                validation_limit = (
                    const_limit
                    if validation_limit is None
                    else min(validation_limit, const_limit)
                )
            if validation_limit is not None:
                validated_items = instance[:validation_limit]
            for index, value in enumerate(validated_items):
                if len(issues) >= _MAX_VERIFICATION_ISSUES:
                    return
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
    except (
        OSError,
        UnicodeError,
        json.JSONDecodeError,
        ValueError,
        RecursionError,
    ) as error:
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
    provenance bindings. The repository is trusted verifier configuration;
    the commit must match the release envelope.
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
                "must equal the trusted expected code repository",
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
    elif (
        isinstance(status, str)
        and status in {"candidate_unsat", "unknown", "error"}
        and certificate is not None
    ):
        _issue(
            issues,
            "result-certificate",
            f"{location}.certificate",
            f"{status} status requires a null certificate",
        )


_UNIVERSAL_COUNT_KEYS = (
    "verified_all",
    "candidate_unsat",
    "unknown",
    "error",
    "skipped",
)
_REQUIRED_UNIVERSAL_CHECKS = {
    "dsatur-delta-plus-2": ("dsatur-iterative-v1", 1),
    "dsatur-delta-plus-3": ("dsatur-iterative-v1", 2),
    "static-delta-plus-2": ("static-order-iterative-v1", 1),
}
_REQUIRED_UNIVERSAL_CHECK_IDS = tuple(sorted(_REQUIRED_UNIVERSAL_CHECKS))
_FINITE_BOUND_LIMITATIONS = (
    "The finite census is computational evidence and does not establish an unbounded theorem.",
    "Generator completeness is assumed for the hash-pinned nauty-geng executable.",
)
_UNIVERSAL_MANIFEST_VERSION = "total-coloring.universal-census-manifest.v1"
_UNIVERSAL_COMPLETION_VERSION = "total-coloring.universal-census-completion.v1"
_UNIVERSAL_RECORD_VERSION = "total-coloring.universal-census-record.v1"


def _finite_scope_for_orders(orders: Sequence[int]) -> str:
    if not orders or any(_positive_integer(order) is None for order in orders):
        raise ValueError("finite-scope orders must be positive nonboolean integers")
    rendered_orders = ", ".join(str(order) for order in orders)
    return (
        "Only the complete unrestricted nauty-geng streams for the declared orders "
        f"{rendered_orders}, filtered by 2*Delta(G) >= n, with every canonical equitable "
        "(Delta(G)+1)-class partition subjected to the three declared positive-witness "
        "checks."
    )


def _nonnegative_integer(value: object) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    return None


def _positive_integer(value: object) -> int | None:
    parsed = _nonnegative_integer(value)
    if parsed is not None and parsed >= 1:
        return parsed
    return None


def _universal_counts(value: object) -> dict[str, int] | None:
    if not isinstance(value, dict) or set(value) != set(_UNIVERSAL_COUNT_KEYS):
        return None
    counts: dict[str, int] = {}
    for key in _UNIVERSAL_COUNT_KEYS:
        parsed = _nonnegative_integer(value.get(key))
        if parsed is None:
            return None
        counts[key] = parsed
    return counts


def _validate_universal_summary_semantics(
    summary: Any,
    location: str,
    expected_repository: object,
    expected_commit: object,
    external_artifacts: dict[str, dict[str, Any]],
    issues: list[VerificationIssue],
) -> None:
    """Check finite-census invariants that JSON Schema cannot express.

    This validates arithmetic, deterministic ordering, and exact provenance
    bindings. ``expected_repository`` is trusted verifier configuration, not a
    value learned from the release being checked. It deliberately does not
    infer an unbounded mathematical claim from finite status counts.
    """

    if not isinstance(summary, dict):
        return

    producer = summary.get("producer")
    if isinstance(producer, dict):
        if producer.get("repository") != expected_repository:
            _issue(
                issues,
                "summary-producer-repository",
                f"{location}.producer.repository",
                "must equal the trusted expected code repository",
            )
        if producer.get("commit") != expected_commit:
            _issue(
                issues,
                "summary-producer-commit",
                f"{location}.producer.commit",
                "must equal release.code_commit",
            )

    scope = summary.get("scope")
    if isinstance(scope, dict) and scope.get("require_high_degree") is not True:
        _issue(
            issues,
            "summary-high-degree-filter",
            f"{location}.scope.require_high_degree",
            "universal-census summary v1 requires the high-degree filter",
        )

    replay = summary.get("replay_archive")
    if isinstance(replay, dict):
        external_name = replay.get("external_artifact")
        declared = (
            external_artifacts.get(external_name)
            if isinstance(external_name, str)
            else None
        )
        if declared is None:
            _issue(
                issues,
                "summary-replay-external",
                f"{location}.replay_archive.external_artifact",
                "must name exactly one declared external artifact",
            )
        else:
            for field in ("url", "media_type", "bytes", "sha256"):
                if replay.get(field) != declared.get(field):
                    _issue(
                        issues,
                        "summary-replay-binding",
                        f"{location}.replay_archive.{field}",
                        f"must equal external_artifacts[{external_name!r}].{field}",
                    )

    checks = summary.get("checks")
    check_count = len(checks) if isinstance(checks, list) else 0
    if isinstance(checks, list):
        if len(checks) > len(_REQUIRED_UNIVERSAL_CHECKS):
            _issue(
                issues,
                "summary-check-limit",
                f"{location}.checks",
                f"summary v1 permits exactly {len(_REQUIRED_UNIVERSAL_CHECKS)} checks",
            )
            return
        if not checks:
            _issue(
                issues,
                "summary-checks-empty",
                f"{location}.checks",
                "at least one configured check is required",
            )
        check_ids: list[str] = []
        for item in checks:
            if isinstance(item, dict):
                check_id = item.get("check_id")
                if isinstance(check_id, str):
                    check_ids.append(check_id)
        if len(check_ids) == len(checks):
            if check_ids != sorted(check_ids):
                _issue(
                    issues,
                    "summary-check-order",
                    f"{location}.checks",
                    "checks must be sorted by check_id",
                )
            if len(check_ids) != len(set(check_ids)):
                _issue(
                    issues,
                    "summary-check-duplicate",
                    f"{location}.checks",
                    "check_id values must be unique",
                )
        check_specs: list[tuple[str, int]] = []
        for item in checks:
            if isinstance(item, dict):
                backend_id = item.get("backend_id")
                palette_offset = item.get("palette_offset")
                if (
                    isinstance(backend_id, str)
                    and isinstance(palette_offset, int)
                    and not isinstance(palette_offset, bool)
                ):
                    check_specs.append((backend_id, palette_offset))
        if len(check_specs) == len(checks) and len(check_specs) != len(
            set(check_specs)
        ):
            _issue(
                issues,
                "summary-check-spec-duplicate",
                f"{location}.checks",
                "backend_id and palette_offset pairs must be unique",
            )
        checks_by_id = {
            item["check_id"]: (item["backend_id"], item["palette_offset"])
            for item in checks
            if isinstance(item, dict)
            and isinstance(item.get("check_id"), str)
            and isinstance(item.get("backend_id"), str)
            and isinstance(item.get("palette_offset"), int)
            and not isinstance(item.get("palette_offset"), bool)
        }
        for check_id, required_spec in _REQUIRED_UNIVERSAL_CHECKS.items():
            if checks_by_id.get(check_id) != required_spec:
                _issue(
                    issues,
                    "summary-required-check",
                    f"{location}.checks",
                    f"{check_id!r} must declare backend/offset {required_spec!r}",
                )
        if checks_by_id != _REQUIRED_UNIVERSAL_CHECKS or check_ids != list(
            _REQUIRED_UNIVERSAL_CHECK_IDS
        ):
            _issue(
                issues,
                "summary-check-profile",
                f"{location}.checks",
                "v1 requires exactly the three canonical DSATUR/static check declarations",
            )
    else:
        checks_by_id = {}

    configuration = summary.get("configuration")
    if isinstance(configuration, dict):
        limits = configuration.get("search_limits")
        if isinstance(limits, dict):
            timeout = limits.get("timeout_seconds_per_check")
            if isinstance(timeout, int | float) and not isinstance(timeout, bool):
                if not math.isfinite(timeout) or timeout <= 0:
                    _issue(
                        issues,
                        "summary-search-limit",
                        f"{location}.configuration.search_limits.timeout_seconds_per_check",
                        "a numeric timeout must be finite and strictly positive",
                    )

    runs = summary.get("runs")
    if isinstance(runs, list) and len(runs) > _MAX_UNIVERSAL_RUNS:
        _issue(
            issues,
            "summary-run-limit",
            f"{location}.runs",
            f"summary v1 permits at most {_MAX_UNIVERSAL_RUNS} runs",
        )
        return
    aggregate_record_count = 0
    aggregate_partition_count = 0
    aggregate_check_evaluations = 0
    aggregate_counts = {key: 0 for key in _UNIVERSAL_COUNT_KEYS}
    run_orders: list[int] = []
    run_fingerprints: list[str] = []
    archive_member_paths: dict[str, str] = {}
    if isinstance(runs, list):
        if not runs:
            _issue(
                issues,
                "summary-runs-empty",
                f"{location}.runs",
                "at least one completed order run is required",
            )
        for run_index, run in enumerate(runs):
            run_location = f"{location}.runs[{run_index}]"
            if not isinstance(run, dict):
                continue
            order = _positive_integer(run.get("order"))
            if order is not None:
                run_orders.append(order)
            else:
                _issue(
                    issues,
                    "summary-run-order",
                    f"{run_location}.order",
                    "run order must be a positive nonboolean integer",
                )
            run_fingerprint = run.get("run_fingerprint")
            if isinstance(run_fingerprint, str):
                run_fingerprints.append(run_fingerprint)
            arguments = run.get("generator_arguments")
            if order is not None and arguments != ["-q", str(order)]:
                _issue(
                    issues,
                    "summary-generator-arguments",
                    f"{run_location}.generator_arguments",
                    f"unrestricted v1 runs require exactly ['-q', {str(order)!r}]",
                )
            if run.get("shard_index") != 0 or run.get("shard_count") != 1:
                _issue(
                    issues,
                    "summary-shard",
                    run_location,
                    "v1 release summaries permit only shard_index=0, shard_count=1",
                )
            record_count = _nonnegative_integer(run.get("record_count"))
            partition_count = _nonnegative_integer(run.get("partition_count"))
            check_evaluations = _nonnegative_integer(run.get("check_evaluations"))
            counts = _universal_counts(run.get("counts"))
            if record_count is not None:
                aggregate_record_count += record_count
            if partition_count is not None:
                aggregate_partition_count += partition_count
            if check_evaluations is not None:
                aggregate_check_evaluations += check_evaluations
            if counts is not None:
                for key, value in counts.items():
                    aggregate_counts[key] += value
                if record_count is not None and sum(counts.values()) != record_count:
                    _issue(
                        issues,
                        "summary-run-counts",
                        f"{run_location}.counts",
                        "status counts must sum to record_count",
                    )
            if partition_count is not None and check_evaluations is not None:
                expected_evaluations = partition_count * check_count
                if check_evaluations != expected_evaluations:
                    _issue(
                        issues,
                        "summary-run-check-evaluations",
                        f"{run_location}.check_evaluations",
                        f"expected partition_count * configured checks = {expected_evaluations}",
                    )

            members = run.get("members")
            if isinstance(members, dict):
                expected_basenames = {
                    "manifest": "manifest.json",
                    "completion": "completion.json",
                    "records": "records.jsonl",
                }
                for member_kind, expected_basename in expected_basenames.items():
                    member = members.get(member_kind)
                    if not isinstance(member, dict):
                        continue
                    raw_path = member.get("path")
                    relative = (
                        _safe_relative_path(raw_path)
                        if isinstance(raw_path, str)
                        else None
                    )
                    member_location = f"{run_location}.members.{member_kind}.path"
                    if relative is None:
                        continue
                    if _has_hidden_component(relative):
                        _issue(
                            issues,
                            "summary-member-hidden",
                            member_location,
                            "archive member paths may not contain hidden components",
                        )
                    if relative.name != expected_basename:
                        _issue(
                            issues,
                            "summary-member-name",
                            member_location,
                            f"{member_kind} receipt must end in {expected_basename!r}",
                        )
                    if order is not None:
                        expected_parent = PurePosixPath(f"order-{order:02d}")
                        if relative.parent != expected_parent:
                            _issue(
                                issues,
                                "summary-member-parent",
                                member_location,
                                f"expected canonical parent {expected_parent.as_posix()!r}",
                            )
                    canonical_member_path = relative.as_posix()
                    previous = archive_member_paths.get(canonical_member_path)
                    if previous is not None:
                        _issue(
                            issues,
                            "summary-member-duplicate",
                            member_location,
                            f"archive member path was first declared at {previous}",
                        )
                    else:
                        archive_member_paths[canonical_member_path] = member_location

        if len(run_orders) == len(runs):
            if run_orders != sorted(run_orders):
                _issue(
                    issues,
                    "summary-run-order",
                    f"{location}.runs",
                    "runs must be sorted by order",
                )
            if len(run_orders) != len(set(run_orders)):
                _issue(
                    issues,
                    "summary-run-duplicate",
                    f"{location}.runs",
                    "run orders must be unique",
                )
        if len(run_fingerprints) == len(runs) and len(run_fingerprints) != len(
            set(run_fingerprints)
        ):
            _issue(
                issues,
                "summary-run-fingerprint-duplicate",
                f"{location}.runs",
                "run fingerprints must be unique",
            )

    totals = summary.get("totals")
    if isinstance(totals, dict) and isinstance(runs, list):
        expected_totals = {
            "order_count": len(runs),
            "record_count": aggregate_record_count,
            "partition_count": aggregate_partition_count,
            "check_evaluations": aggregate_check_evaluations,
        }
        for field, expected in expected_totals.items():
            if totals.get(field) != expected:
                _issue(
                    issues,
                    "summary-totals",
                    f"{location}.totals.{field}",
                    f"expected sum over runs = {expected}",
                )
        total_counts = _universal_counts(totals.get("counts"))
        if total_counts is not None and total_counts != aggregate_counts:
            _issue(
                issues,
                "summary-total-counts",
                f"{location}.totals.counts",
                "status counts must equal the component-wise sum over runs",
            )
        total_record_count = _nonnegative_integer(totals.get("record_count"))
        if total_counts is not None and total_record_count is not None:
            if sum(total_counts.values()) != total_record_count:
                _issue(
                    issues,
                    "summary-total-counts",
                    f"{location}.totals.counts",
                    "status counts must sum to totals.record_count",
                )

    claims = summary.get("claims")
    if isinstance(claims, list):
        if len(claims) != 1:
            _issue(
                issues,
                "summary-claim-count",
                f"{location}.claims",
                "summary v1 requires exactly one finite_bound claim",
            )
            if len(claims) > 1:
                return
        claim_ids: list[str] = []
        for claim in claims:
            if isinstance(claim, dict):
                claim_id = claim.get("claim_id")
                if isinstance(claim_id, str):
                    claim_ids.append(claim_id)
        if len(claim_ids) == len(claims):
            if claim_ids != sorted(claim_ids):
                _issue(
                    issues,
                    "summary-claim-order",
                    f"{location}.claims",
                    "claims must be sorted by claim_id",
                )
            if len(claim_ids) != len(set(claim_ids)):
                _issue(
                    issues,
                    "summary-claim-duplicate",
                    f"{location}.claims",
                    "claim_id values must be unique",
                )
        available_orders = set(run_orders)
        run_items = runs if isinstance(runs, list) else []
        runs_by_order = {
            run.get("order"): run
            for run in run_items
            if isinstance(run, dict) and _positive_integer(run.get("order")) is not None
        }
        for claim_index, claim in enumerate(claims):
            if not isinstance(claim, dict):
                continue
            claim_location = f"{location}.claims[{claim_index}]"
            if claim.get("claim_type") != "finite_bound":
                _issue(
                    issues,
                    "summary-claim-type",
                    f"{claim_location}.claim_type",
                    "summary v1 reserves all claim types except finite_bound",
                )
            if claim.get("status") != "verified_in_finite_scope":
                _issue(
                    issues,
                    "summary-claim-status",
                    f"{claim_location}.status",
                    "the canonical finite_bound claim must be verified_in_finite_scope",
                )
            orders = claim.get("orders")
            valid_orders: list[int] | None = None
            if (
                isinstance(orders, list)
                and orders
                and len(orders) <= _MAX_UNIVERSAL_RUNS
                and all(_positive_integer(order) is not None for order in orders)
            ):
                valid_orders = orders
                if orders != sorted(orders) or len(orders) != len(set(orders)):
                    _issue(
                        issues,
                        "summary-claim-orders",
                        f"{claim_location}.orders",
                        "orders must be sorted and unique",
                    )
                unknown_orders = sorted(set(orders) - available_orders)
                if unknown_orders:
                    _issue(
                        issues,
                        "summary-claim-orders",
                        f"{claim_location}.orders",
                        f"orders have no run receipt: {unknown_orders}",
                    )
                if orders != run_orders:
                    _issue(
                        issues,
                        "summary-claim-orders",
                        f"{claim_location}.orders",
                        f"finite_bound orders must equal all run orders: {run_orders!r}",
                    )
                if len(run_orders) == len(run_items) and run_orders:
                    expected_scope = _finite_scope_for_orders(run_orders)
                else:
                    expected_scope = None
                if (
                    expected_scope is None
                    or claim.get("finite_scope") != expected_scope
                ):
                    _issue(
                        issues,
                        "summary-claim-scope",
                        f"{claim_location}.finite_scope",
                        (
                            f"expected canonical finite scope {expected_scope!r}"
                            if expected_scope is not None
                            else "canonical finite scope requires valid positive run orders"
                        ),
                    )
            else:
                _issue(
                    issues,
                    "summary-claim-orders",
                    f"{claim_location}.orders",
                    "orders must be a nonempty array of positive nonboolean integers",
                )
            limitations = claim.get("limitations")
            if limitations != list(_FINITE_BOUND_LIMITATIONS):
                _issue(
                    issues,
                    "summary-claim-limitations",
                    f"{claim_location}.limitations",
                    "finite_bound requires the canonical bounded-evidence and generator-completeness limitations",
                )
            required_checks = claim.get("required_checks")
            if (
                isinstance(required_checks, list)
                and len(required_checks) <= len(_REQUIRED_UNIVERSAL_CHECK_IDS)
                and all(isinstance(check_id, str) for check_id in required_checks)
            ):
                if required_checks != sorted(required_checks) or len(
                    required_checks
                ) != len(set(required_checks)):
                    _issue(
                        issues,
                        "summary-claim-checks",
                        f"{claim_location}.required_checks",
                        "required_checks must be sorted and unique",
                    )
                unknown_checks = sorted(set(required_checks) - set(checks_by_id))
                if unknown_checks:
                    _issue(
                        issues,
                        "summary-claim-checks",
                        f"{claim_location}.required_checks",
                        f"checks are not configured: {unknown_checks}",
                    )
                if required_checks != list(_REQUIRED_UNIVERSAL_CHECK_IDS):
                    _issue(
                        issues,
                        "summary-claim-checks",
                        f"{claim_location}.required_checks",
                        f"expected exactly {list(_REQUIRED_UNIVERSAL_CHECK_IDS)!r}",
                    )
                if claim.get("status") == "verified_in_finite_scope":
                    missing_required = sorted(
                        set(_REQUIRED_UNIVERSAL_CHECKS) - set(required_checks)
                    )
                    if missing_required:
                        _issue(
                            issues,
                            "summary-claim-checks",
                            f"{claim_location}.required_checks",
                            f"verified status must cover required checks: {missing_required}",
                        )
            if (
                claim.get("status") == "verified_in_finite_scope"
                and valid_orders is not None
            ):
                supporting_runs = [runs_by_order.get(order) for order in valid_orders]
                adverse = {"candidate_unsat": 0, "unknown": 0, "error": 0}
                verified_all = 0
                partitions = 0
                evaluations = 0
                for supporting_run in supporting_runs:
                    if not isinstance(supporting_run, dict):
                        continue
                    run_counts = _universal_counts(supporting_run.get("counts"))
                    if run_counts is not None:
                        for key in adverse:
                            adverse[key] += run_counts[key]
                        verified_all += run_counts["verified_all"]
                    partitions += (
                        _nonnegative_integer(supporting_run.get("partition_count")) or 0
                    )
                    evaluations += (
                        _nonnegative_integer(supporting_run.get("check_evaluations"))
                        or 0
                    )
                if any(adverse.values()):
                    _issue(
                        issues,
                        "summary-claim-adverse-status",
                        claim_location,
                        f"verified finite status requires zero adverse outcomes, found {adverse}",
                    )
                if verified_all <= 0 or partitions <= 0 or evaluations <= 0:
                    _issue(
                        issues,
                        "summary-claim-vacuous",
                        claim_location,
                        "verified finite status requires positive verified graphs, partitions, and check evaluations",
                    )

    limitations = summary.get("limitations")
    if limitations != list(_FINITE_BOUND_LIMITATIONS):
        _issue(
            issues,
            "summary-limitations",
            f"{location}.limitations",
            "summary v1 requires the canonical bounded-evidence and generator-completeness limitations",
        )


def _exact_embedded_object(
    value: object,
    expected_keys: set[str],
    location: str,
    issues: list[VerificationIssue],
) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        _issue(issues, "archive-json-type", location, "expected a JSON object")
        return None
    actual_keys = set(value)
    if actual_keys != expected_keys:
        _issue(
            issues,
            "archive-json-keys",
            location,
            f"missing={sorted(expected_keys - actual_keys)}, extra={sorted(actual_keys - expected_keys)}",
        )
    return value


def _valid_digest(value: object) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _validate_edge_array(
    value: object, location: str, issues: list[VerificationIssue]
) -> None:
    if not isinstance(value, list):
        _issue(issues, "archive-record-shape", location, "expected an edge array")
        return
    previous: tuple[int, int] | None = None
    for index, edge in enumerate(value):
        edge_location = f"{location}[{index}]"
        if (
            not isinstance(edge, list)
            or len(edge) != 2
            or any(_nonnegative_integer(endpoint) is None for endpoint in edge)
        ):
            _issue(
                issues,
                "archive-record-shape",
                edge_location,
                "each edge must be a pair of nonnegative integers",
            )
            continue
        checked = (edge[0], edge[1])
        if checked[0] >= checked[1]:
            _issue(
                issues,
                "archive-record-shape",
                edge_location,
                "edge endpoints must satisfy left < right",
            )
        if previous is not None and checked <= previous:
            _issue(
                issues,
                "archive-record-order",
                edge_location,
                "edges must be unique and lexicographically sorted",
            )
        previous = checked


def _validate_integer_array(
    value: object, location: str, issues: list[VerificationIssue]
) -> None:
    if not isinstance(value, list) or any(
        _nonnegative_integer(item) is None for item in value
    ):
        _issue(
            issues,
            "archive-record-shape",
            location,
            "expected an array of nonnegative integers",
        )


def _validate_partition_transcript(
    value: object,
    *,
    location: str,
    partition_index: int,
    degree_parameter: int | None,
    expected_checks: list[tuple[str, int]],
    require_witnesses: bool,
    issues: list[VerificationIssue],
) -> int:
    partition_result = _exact_embedded_object(
        value, {"auxiliary", "checks", "index", "partition"}, location, issues
    )
    if partition_result is None:
        return 0
    parsed_partition_index = _nonnegative_integer(partition_result.get("index"))
    if parsed_partition_index is None or parsed_partition_index != partition_index:
        _issue(
            issues,
            "archive-partition-index",
            f"{location}.index",
            f"expected contiguous index {partition_index}",
        )

    partition = _exact_embedded_object(
        partition_result.get("partition"),
        {"fingerprint", "pairs", "singletons"},
        f"{location}.partition",
        issues,
    )
    if partition is not None:
        if not _valid_digest(partition.get("fingerprint")):
            _issue(
                issues,
                "archive-record-digest",
                f"{location}.partition.fingerprint",
                "expected a lowercase SHA-256 digest",
            )
        _validate_edge_array(
            partition.get("pairs"), f"{location}.partition.pairs", issues
        )
        _validate_integer_array(
            partition.get("singletons"), f"{location}.partition.singletons", issues
        )

    auxiliary = _exact_embedded_object(
        partition_result.get("auxiliary"),
        {"distinguished_edges", "graph6", "graph_fingerprint"},
        f"{location}.auxiliary",
        issues,
    )
    if auxiliary is not None:
        if not isinstance(auxiliary.get("graph6"), str) or not auxiliary.get("graph6"):
            _issue(
                issues,
                "archive-record-shape",
                f"{location}.auxiliary.graph6",
                "expected a nonempty graph6 string",
            )
        if not _valid_digest(auxiliary.get("graph_fingerprint")):
            _issue(
                issues,
                "archive-record-digest",
                f"{location}.auxiliary.graph_fingerprint",
                "expected a lowercase SHA-256 digest",
            )
        _validate_edge_array(
            auxiliary.get("distinguished_edges"),
            f"{location}.auxiliary.distinguished_edges",
            issues,
        )

    checks = partition_result.get("checks")
    if not isinstance(checks, list):
        _issue(
            issues,
            "archive-check-shape",
            f"{location}.checks",
            "expected a check-result array",
        )
        return 0
    actual_specs: list[tuple[str, int]] = []
    for check_index, check_value in enumerate(checks):
        check_location = f"{location}.checks[{check_index}]"
        check = _exact_embedded_object(
            check_value,
            {
                "auxiliary_edge_colors",
                "backend_id",
                "color_count",
                "detail",
                "palette_offset",
                "problem_digest",
                "stats",
                "status",
            },
            check_location,
            issues,
        )
        if check is None:
            continue
        backend_id = check.get("backend_id")
        palette_offset = _nonnegative_integer(check.get("palette_offset"))
        if not isinstance(backend_id, str):
            _issue(
                issues,
                "archive-check-shape",
                f"{check_location}.backend_id",
                "expected a backend identifier string",
            )
        if palette_offset is None:
            _issue(
                issues,
                "archive-check-shape",
                f"{check_location}.palette_offset",
                "expected a nonnegative nonboolean integer",
            )
        if isinstance(backend_id, str) and palette_offset is not None:
            actual_specs.append((backend_id, palette_offset))
        color_count = _nonnegative_integer(check.get("color_count"))
        if color_count is None:
            _issue(
                issues,
                "archive-check-shape",
                f"{check_location}.color_count",
                "expected a nonnegative integer",
            )
        elif degree_parameter is not None and palette_offset is not None:
            expected_color_count = degree_parameter + palette_offset
            if color_count != expected_color_count:
                _issue(
                    issues,
                    "archive-check-color-count",
                    f"{check_location}.color_count",
                    (
                        "expected degree_parameter + palette_offset = "
                        f"{expected_color_count}"
                    ),
                )
        if not isinstance(check.get("detail"), str) or not check.get("detail"):
            _issue(
                issues,
                "archive-check-shape",
                f"{check_location}.detail",
                "expected nonempty detail text",
            )
        if not _valid_digest(check.get("problem_digest")):
            _issue(
                issues,
                "archive-record-digest",
                f"{check_location}.problem_digest",
                "expected a lowercase SHA-256 digest",
            )
        stats = _exact_embedded_object(
            check.get("stats"),
            {"backtracks", "nodes"},
            f"{check_location}.stats",
            issues,
        )
        if stats is not None and any(
            _nonnegative_integer(stats.get(key)) is None
            for key in ("backtracks", "nodes")
        ):
            _issue(
                issues,
                "archive-check-shape",
                f"{check_location}.stats",
                "search counters must be nonnegative integers",
            )
        status = check.get("status")
        if not isinstance(status, str) or status not in {
            "witness",
            "candidate_unsat",
            "unknown",
            "error",
        }:
            _issue(
                issues,
                "archive-check-status",
                f"{check_location}.status",
                f"unsupported status {status!r}",
            )
        colors = check.get("auxiliary_edge_colors")
        if status == "witness":
            _validate_integer_array(
                colors, f"{check_location}.auxiliary_edge_colors", issues
            )
        elif colors is not None:
            _issue(
                issues,
                "archive-check-certificate",
                f"{check_location}.auxiliary_edge_colors",
                "nonwitness checks require a null assignment",
            )
        if require_witnesses and status != "witness":
            _issue(
                issues,
                "archive-verified-check",
                f"{check_location}.status",
                "verified_all records require a witness for every configured check",
            )
    if actual_specs != expected_checks:
        _issue(
            issues,
            "archive-check-matrix",
            f"{location}.checks",
            f"expected configured checks {expected_checks!r}, found {actual_specs!r}",
        )
    return len(checks)


def _scan_record_member(
    stream: Any,
    *,
    location: str,
    expected_run_fingerprint: str,
    expected_order: int,
    expected_checks: list[tuple[str, int]],
    issues: list[VerificationIssue],
) -> _RecordScan:
    digest = hashlib.sha256()
    byte_count = 0
    record_count = 0
    partition_count = 0
    check_evaluations = 0
    counts = {key: 0 for key in _UNIVERSAL_COUNT_KEYS}
    while True:
        raw_line = stream.readline(_MAX_UNIVERSAL_RECORD_BYTES + 1)
        if not raw_line:
            break
        digest.update(raw_line)
        byte_count += len(raw_line)
        line_location = f"{location}:{record_count + 1}"
        if len(raw_line) > _MAX_UNIVERSAL_RECORD_BYTES:
            terminated = raw_line.endswith(b"\n")
            while not terminated:
                continuation = stream.readline(_MAX_UNIVERSAL_RECORD_BYTES + 1)
                if not continuation:
                    break
                digest.update(continuation)
                byte_count += len(continuation)
                terminated = continuation.endswith(b"\n")
            _issue(
                issues,
                "archive-record-size",
                line_location,
                f"record exceeds {_MAX_UNIVERSAL_RECORD_BYTES} bytes",
            )
            record_count += 1
            continue
        if not raw_line.endswith(b"\n"):
            _issue(
                issues,
                "archive-record-termination",
                line_location,
                "every JSONL record must end with one newline",
            )
            payload = raw_line
        else:
            payload = raw_line[:-1]
        if not payload:
            _issue(
                issues,
                "archive-record-empty",
                line_location,
                "blank JSONL records are forbidden",
            )
            continue
        try:
            record_value = _load_json_bytes(payload)
        except (UnicodeError, json.JSONDecodeError, ValueError) as error:
            _issue(issues, "archive-record-json", line_location, str(error))
            continue
        if payload != _canonical_json_bytes(record_value):
            _issue(
                issues,
                "archive-record-canonical",
                line_location,
                "record must use toolkit canonical JSON bytes",
            )
        record = _exact_embedded_object(
            record_value,
            {
                "degree_parameter",
                "detail",
                "eligible",
                "graph6",
                "graph_fingerprint",
                "index",
                "max_degree",
                "min_degree",
                "order",
                "outcome_code",
                "partition_count",
                "partitions",
                "run_fingerprint",
                "schema_version",
                "size",
                "status",
            },
            line_location,
            issues,
        )
        if record is None:
            continue
        if record.get("schema_version") != _UNIVERSAL_RECORD_VERSION:
            _issue(
                issues,
                "archive-record-version",
                f"{line_location}.schema_version",
                f"expected {_UNIVERSAL_RECORD_VERSION!r}",
            )
        if record.get("run_fingerprint") != expected_run_fingerprint:
            _issue(
                issues,
                "archive-record-run",
                f"{line_location}.run_fingerprint",
                "record does not belong to the declared run",
            )
        record_index = _nonnegative_integer(record.get("index"))
        if record_index is None or record_index != record_count:
            _issue(
                issues,
                "archive-record-index",
                f"{line_location}.index",
                f"expected contiguous index {record_count}",
            )
        record_order = _positive_integer(record.get("order"))
        if record_order is None or record_order != expected_order:
            _issue(
                issues,
                "archive-record-order",
                f"{line_location}.order",
                f"expected graph order {expected_order}",
            )
        parsed_fields = {
            field: _nonnegative_integer(record.get(field))
            for field in ("degree_parameter", "size", "min_degree", "max_degree")
        }
        for field, parsed_value in parsed_fields.items():
            if parsed_value is None:
                _issue(
                    issues,
                    "archive-record-shape",
                    f"{line_location}.{field}",
                    "expected a nonnegative integer",
                )
        if not isinstance(record.get("detail"), str) or not record.get("detail"):
            _issue(
                issues,
                "archive-record-shape",
                f"{line_location}.detail",
                "expected nonempty detail text",
            )
        if (
            not isinstance(record.get("outcome_code"), str)
            or re.fullmatch(r"[a-z][a-z0-9_]*", record.get("outcome_code", "")) is None
        ):
            _issue(
                issues,
                "archive-record-shape",
                f"{line_location}.outcome_code",
                "expected a normalized outcome code",
            )
        graph6 = record.get("graph6")
        if not isinstance(graph6, str) or not graph6:
            _issue(
                issues,
                "archive-record-shape",
                f"{line_location}.graph6",
                "expected a nonempty graph6 string",
            )
        if not _valid_digest(record.get("graph_fingerprint")):
            _issue(
                issues,
                "archive-record-digest",
                f"{line_location}.graph_fingerprint",
                "expected a lowercase SHA-256 digest",
            )
        status = record.get("status")
        if not isinstance(status, str) or status not in counts:
            _issue(
                issues,
                "archive-record-status",
                f"{line_location}.status",
                f"unsupported status {status!r}",
            )
        else:
            counts[status] += 1
        eligible = record.get("eligible")
        if not isinstance(eligible, bool):
            _issue(
                issues,
                "archive-record-shape",
                f"{line_location}.eligible",
                "eligible must be a JSON boolean",
            )
        partitions = record.get("partitions")
        declared_partitions = _nonnegative_integer(record.get("partition_count"))
        if not isinstance(partitions, list) or declared_partitions is None:
            _issue(
                issues,
                "archive-partition-count",
                line_location,
                "partitions must be an array with a nonnegative declared count",
            )
            partitions = []
            declared_partitions = 0
        elif declared_partitions != len(partitions):
            _issue(
                issues,
                "archive-partition-count",
                f"{line_location}.partition_count",
                f"expected array length {len(partitions)}",
            )
        if status == "skipped" and (eligible is not False or declared_partitions != 0):
            _issue(
                issues,
                "archive-record-classification",
                line_location,
                "skipped records must be ineligible with zero partitions",
            )
        if status == "verified_all" and (
            eligible is not True or declared_partitions <= 0
        ):
            _issue(
                issues,
                "archive-record-classification",
                line_location,
                "verified_all records must be eligible and nonvacuous",
            )
        for partition_index, partition in enumerate(partitions):
            check_evaluations += _validate_partition_transcript(
                partition,
                location=f"{line_location}.partitions[{partition_index}]",
                partition_index=partition_index,
                degree_parameter=parsed_fields["degree_parameter"],
                expected_checks=expected_checks,
                require_witnesses=status == "verified_all",
                issues=issues,
            )
        partition_count += declared_partitions
        record_count += 1
    return _RecordScan(
        sha256=digest.hexdigest(),
        byte_count=byte_count,
        record_count=record_count,
        partition_count=partition_count,
        check_evaluations=check_evaluations,
        counts=counts,
    )


def _read_small_archive_member(
    archive: tarfile.TarFile,
    member: tarfile.TarInfo,
    *,
    location: str,
    issues: list[VerificationIssue],
) -> bytes | None:
    if member.size > _MAX_SMALL_ARCHIVE_MEMBER_BYTES:
        _issue(
            issues,
            "archive-member-size",
            location,
            "manifest and completion members may not exceed 4 MiB",
        )
        return None
    stream = archive.extractfile(member)
    if stream is None:
        _issue(issues, "archive-member-read", location, "unable to read regular member")
        return None
    with stream:
        payload = stream.read(member.size + 1)
    if len(payload) != member.size:
        _issue(
            issues,
            "archive-member-size",
            location,
            f"tar header declares {member.size} bytes, extracted {len(payload)}",
        )
        return None
    return payload


def _parse_canonical_embedded_json(
    payload: bytes, location: str, issues: list[VerificationIssue]
) -> dict[str, Any] | None:
    if not payload.endswith(b"\n") or payload.endswith(b"\n\n"):
        _issue(
            issues,
            "archive-json-canonical",
            location,
            "toolkit JSON files require exactly one trailing newline",
        )
    document = payload[:-1] if payload.endswith(b"\n") else payload
    try:
        value = _load_json_bytes(document)
    except (UnicodeError, json.JSONDecodeError, ValueError) as error:
        _issue(issues, "archive-json", location, str(error))
        return None
    if document != _canonical_json_bytes(value):
        _issue(
            issues,
            "archive-json-canonical",
            location,
            "toolkit JSON files must use canonical JSON bytes",
        )
    if not isinstance(value, dict):
        _issue(issues, "archive-json-type", location, "expected a JSON object")
        return None
    return value


def _expected_run_descriptor(
    summary: dict[str, Any],
    run: dict[str, Any],
    *,
    location: str,
    issues: list[VerificationIssue],
) -> dict[str, object] | None:
    scope = summary.get("scope")
    configuration = summary.get("configuration")
    generator = summary.get("generator")
    producer = summary.get("producer")
    checks = summary.get("checks")
    containers = (
        ("scope", scope, dict),
        ("configuration", configuration, dict),
        ("generator", generator, dict),
        ("producer", producer, dict),
        ("checks", checks, list),
    )
    invalid = False
    for name, value, expected_type in containers:
        if not isinstance(value, expected_type):
            invalid = True
            _issue(
                issues,
                "archive-summary-shape",
                f"{location}.summary.{name}",
                f"expected {expected_type.__name__}",
            )
    if invalid:
        return None
    scope = cast(dict[str, Any], scope)
    configuration = cast(dict[str, Any], configuration)
    generator = cast(dict[str, Any], generator)
    producer = cast(dict[str, Any], producer)
    checks = cast(list[Any], checks)
    if not all(isinstance(check, dict) for check in checks):
        _issue(
            issues,
            "archive-summary-shape",
            f"{location}.summary.checks",
            "every configured check must be an object",
        )
        return None
    check_specs = [
        {
            "backend_id": check.get("backend_id"),
            "palette_offset": check.get("palette_offset"),
        }
        for check in checks
        if isinstance(check, dict)
    ]
    return {
        "config": {
            "checkpoint_interval": configuration.get("checkpoint_interval"),
            "checks": check_specs,
            "filters": {"require_high_degree": scope.get("require_high_degree")},
            "fix_distinguished_colors": scope.get("fix_distinguished_colors"),
            "generator_spec": {
                "connected": scope.get("connected"),
                "max_degree": scope.get("max_degree"),
                "min_degree": scope.get("min_degree"),
                "order": run.get("order"),
                "shard_count": None,
                "shard_index": None,
            },
            "partition_enumerator": scope.get("partition_enumerator"),
            "search_limits": configuration.get("search_limits"),
        },
        "generator": {
            "arguments": run.get("generator_arguments"),
            "executable": generator.get("executable"),
            "name": generator.get("name"),
            "sha256": generator.get("sha256"),
        },
        "objective": scope.get("objective"),
        "shard": {"count": run.get("shard_count"), "index": run.get("shard_index")},
        "toolkit": {
            "distribution_version": producer.get("distribution_version"),
            "python_implementation": producer.get("python_implementation"),
            "python_version": producer.get("python_version"),
            "source_sha256": producer.get("source_sha256"),
        },
    }


def _verify_embedded_run(
    archive: tarfile.TarFile,
    member_by_name: dict[str, tarfile.TarInfo],
    *,
    summary: dict[str, Any],
    run: dict[str, Any],
    run_index: int,
    issues: list[VerificationIssue],
) -> None:
    location = f"replay_archive.runs[{run_index}]"
    members = run.get("members")
    if not isinstance(members, dict):
        return
    payloads: dict[str, bytes] = {}
    for kind in ("manifest", "completion"):
        descriptor = members.get(kind)
        if not isinstance(descriptor, dict) or not isinstance(
            descriptor.get("path"), str
        ):
            continue
        path = descriptor["path"]
        member = member_by_name.get(path)
        if member is None:
            continue
        payload = _read_small_archive_member(
            archive, member, location=f"{location}.{kind}", issues=issues
        )
        if payload is not None:
            payloads[kind] = payload

    manifest_payload = payloads.get("manifest")
    completion_payload = payloads.get("completion")
    if manifest_payload is None or completion_payload is None:
        return
    manifest = _parse_canonical_embedded_json(
        manifest_payload, f"{location}.manifest", issues
    )
    completion = _parse_canonical_embedded_json(
        completion_payload, f"{location}.completion", issues
    )
    if manifest is None or completion is None:
        return
    _exact_embedded_object(
        manifest,
        {
            "artifacts",
            "complete",
            "counts",
            "partition_count",
            "provenance",
            "record_count",
            "run_fingerprint",
            "schema_version",
        },
        f"{location}.manifest",
        issues,
    )
    _exact_embedded_object(
        completion,
        {
            "manifest_sha256",
            "record_count",
            "records_sha256",
            "run_fingerprint",
            "schema_version",
        },
        f"{location}.completion",
        issues,
    )
    if manifest.get("schema_version") != _UNIVERSAL_MANIFEST_VERSION:
        _issue(
            issues,
            "archive-manifest-version",
            f"{location}.manifest.schema_version",
            f"expected {_UNIVERSAL_MANIFEST_VERSION!r}",
        )
    if completion.get("schema_version") != _UNIVERSAL_COMPLETION_VERSION:
        _issue(
            issues,
            "archive-completion-version",
            f"{location}.completion.schema_version",
            f"expected {_UNIVERSAL_COMPLETION_VERSION!r}",
        )
    if manifest.get("complete") is not True:
        _issue(
            issues,
            "archive-manifest-complete",
            f"{location}.manifest.complete",
            "completed run manifest must contain JSON true",
        )

    expected_descriptor = _expected_run_descriptor(
        summary, run, location=location, issues=issues
    )
    if expected_descriptor is None:
        return
    provenance = manifest.get("provenance")
    if not _json_equal(provenance, expected_descriptor):
        _issue(
            issues,
            "archive-provenance",
            f"{location}.manifest.provenance",
            "embedded toolkit descriptor does not exactly match summary provenance",
        )
    recomputed_fingerprint = _canonical_digest(provenance)
    declared_fingerprint = run.get("run_fingerprint")
    if (
        manifest.get("run_fingerprint") != recomputed_fingerprint
        or completion.get("run_fingerprint") != recomputed_fingerprint
        or declared_fingerprint != recomputed_fingerprint
    ):
        _issue(
            issues,
            "archive-run-fingerprint",
            location,
            f"expected recomputed fingerprint {recomputed_fingerprint}",
        )

    records_descriptor = members.get("records")
    record_scan: _RecordScan | None = None
    if isinstance(records_descriptor, dict) and isinstance(
        records_descriptor.get("path"), str
    ):
        records_member = member_by_name.get(records_descriptor["path"])
        if records_member is not None:
            stream = archive.extractfile(records_member)
            if stream is None:
                _issue(
                    issues,
                    "archive-member-read",
                    f"{location}.records",
                    "unable to read regular record member",
                )
            else:
                checks = summary.get("checks")
                expected_checks: list[tuple[str, int]] = []
                if isinstance(checks, list):
                    for check in checks:
                        if isinstance(check, dict):
                            backend_id = check.get("backend_id")
                            palette_offset = check.get("palette_offset")
                            parsed_offset = _nonnegative_integer(palette_offset)
                            if (
                                isinstance(backend_id, str)
                                and parsed_offset is not None
                            ):
                                expected_checks.append((backend_id, parsed_offset))
                expected_order = _positive_integer(run.get("order"))
                if expected_order is None:
                    _issue(
                        issues,
                        "archive-summary-order",
                        f"{location}.order",
                        "run order must be a positive nonboolean integer",
                    )
                    return
                with stream:
                    record_scan = _scan_record_member(
                        stream,
                        location=f"{location}.records",
                        expected_run_fingerprint=recomputed_fingerprint,
                        expected_order=expected_order,
                        expected_checks=expected_checks,
                        issues=issues,
                    )

    if record_scan is None:
        return
    artifacts = _exact_embedded_object(
        manifest.get("artifacts"),
        {"records_bytes", "records_path", "records_sha256"},
        f"{location}.manifest.artifacts",
        issues,
    )
    manifest_counts = _universal_counts(manifest.get("counts"))
    if manifest_counts is None:
        _issue(
            issues,
            "archive-manifest-counts",
            f"{location}.manifest.counts",
            "expected exact nonnegative universal status counts",
        )
    expected_artifacts = {
        "records_bytes": record_scan.byte_count,
        "records_path": "records.jsonl",
        "records_sha256": record_scan.sha256,
    }
    if artifacts is not None and not _json_equal(artifacts, expected_artifacts):
        _issue(
            issues,
            "archive-record-binding",
            f"{location}.manifest.artifacts",
            f"expected {expected_artifacts!r}",
        )
    manifest_sha256 = hashlib.sha256(manifest_payload).hexdigest()
    expected_completion = {
        "manifest_sha256": manifest_sha256,
        "record_count": record_scan.record_count,
        "records_sha256": record_scan.sha256,
        "run_fingerprint": recomputed_fingerprint,
        "schema_version": _UNIVERSAL_COMPLETION_VERSION,
    }
    if not _json_equal(completion, expected_completion):
        _issue(
            issues,
            "archive-completion-binding",
            f"{location}.completion",
            "completion marker does not exactly bind manifest, records, and counts",
        )
    expected_run_values = {
        "record_count": record_scan.record_count,
        "partition_count": record_scan.partition_count,
        "check_evaluations": record_scan.check_evaluations,
        "counts": record_scan.counts,
    }
    for field, actual in expected_run_values.items():
        if not _json_equal(run.get(field), actual):
            _issue(
                issues,
                "archive-summary-counts",
                f"{location}.{field}",
                f"summary value does not match parsed transcript: expected {actual!r}",
            )
        if field in {"record_count", "partition_count", "counts"} and not _json_equal(
            manifest.get(field), actual
        ):
            _issue(
                issues,
                "archive-manifest-counts",
                f"{location}.manifest.{field}",
                f"manifest value does not match parsed transcript: expected {actual!r}",
            )


def _expected_replay_descriptors(
    summary: dict[str, Any],
    *,
    location: str,
    issues: list[VerificationIssue],
) -> dict[str, dict[str, Any]] | None:
    runs = summary.get("runs")
    if not isinstance(runs, list):
        _issue(
            issues,
            "archive-summary-shape",
            f"{location}.runs",
            "expected a run array",
        )
        return None
    if len(runs) > _MAX_UNIVERSAL_RUNS:
        _issue(
            issues,
            "archive-run-limit",
            f"{location}.runs",
            f"replay archive permits at most {_MAX_UNIVERSAL_RUNS} runs",
        )
        return None
    descriptors: dict[str, dict[str, Any]] = {}
    for run_index, run in enumerate(runs):
        if not isinstance(run, dict):
            _issue(
                issues,
                "archive-summary-shape",
                f"{location}.runs[{run_index}]",
                "expected a run object",
            )
            return None
        if _positive_integer(run.get("order")) is None:
            _issue(
                issues,
                "archive-summary-order",
                f"{location}.runs[{run_index}].order",
                "run order must be a positive nonboolean integer",
            )
            return None
        members = run.get("members")
        if not isinstance(members, dict):
            _issue(
                issues,
                "archive-summary-shape",
                f"{location}.runs[{run_index}].members",
                "expected a member-receipt object",
            )
            return None
        for kind in ("completion", "manifest", "records"):
            descriptor = members.get(kind)
            descriptor_location = f"{location}.runs[{run_index}].members.{kind}"
            if not isinstance(descriptor, dict):
                _issue(
                    issues,
                    "archive-summary-shape",
                    descriptor_location,
                    "expected a member receipt object",
                )
                return None
            path = descriptor.get("path")
            byte_count = _nonnegative_integer(descriptor.get("bytes"))
            digest = descriptor.get("sha256")
            relative = _safe_relative_path(path) if isinstance(path, str) else None
            if (
                relative is None
                or _has_hidden_component(relative)
                or byte_count is None
                or not _valid_digest(digest)
            ):
                _issue(
                    issues,
                    "archive-summary-shape",
                    descriptor_location,
                    "member receipt requires a safe path, nonnegative bytes, and SHA-256",
                )
                return None
            if (
                kind in {"completion", "manifest"}
                and byte_count > _MAX_SMALL_ARCHIVE_MEMBER_BYTES
            ):
                _issue(
                    issues,
                    "archive-member-size",
                    descriptor_location,
                    "manifest and completion members may not exceed 4 MiB",
                )
                return None
            canonical_path = relative.as_posix()
            if canonical_path in descriptors:
                _issue(
                    issues,
                    "archive-member-duplicate",
                    descriptor_location,
                    f"duplicate member receipt {canonical_path!r}",
                )
                return None
            descriptors[canonical_path] = descriptor
    if not descriptors:
        _issue(
            issues,
            "archive-summary-shape",
            location,
            "at least one replay member is required",
        )
        return None
    return descriptors


def _canonical_tar_layout(
    descriptors: dict[str, dict[str, Any]],
    *,
    location: str,
    issues: list[VerificationIssue],
) -> tuple[tuple[tuple[int, bytes], ...], tuple[tuple[int, int], ...], int] | None:
    headers: list[tuple[int, bytes]] = []
    zero_ranges: list[tuple[int, int]] = []
    offset = 0
    for name in sorted(descriptors):
        byte_count = _nonnegative_integer(descriptors[name].get("bytes"))
        if byte_count is None:  # guarded by _expected_replay_descriptors
            return None
        info = tarfile.TarInfo(name)
        info.size = byte_count
        info.mode = 0o644
        info.mtime = 0
        info.uid = 0
        info.gid = 0
        info.uname = ""
        info.gname = ""
        try:
            header = info.tobuf(
                format=tarfile.USTAR_FORMAT,
                encoding="utf-8",
                errors="surrogateescape",
            )
        except (UnicodeError, ValueError) as error:
            _issue(issues, "archive-ustar-layout", location, str(error))
            return None
        headers.append((offset, header))
        data_end = offset + _TAR_BLOCK_SIZE + byte_count
        offset += (
            _TAR_BLOCK_SIZE
            + ((byte_count + _TAR_BLOCK_SIZE - 1) // _TAR_BLOCK_SIZE) * _TAR_BLOCK_SIZE
        )
        if data_end < offset:
            zero_ranges.append((data_end, offset))
    terminal_end = offset + 2 * _TAR_BLOCK_SIZE
    archive_bytes = (
        (terminal_end + _TAR_RECORD_SIZE - 1) // _TAR_RECORD_SIZE
    ) * _TAR_RECORD_SIZE
    if archive_bytes > _MAX_REPLAY_UNCOMPRESSED_BYTES:
        _issue(
            issues,
            "archive-size-limit",
            location,
            f"declared USTAR expands beyond {_MAX_REPLAY_UNCOMPRESSED_BYTES} bytes",
        )
        return None
    zero_ranges.append((offset, archive_bytes))
    return tuple(headers), tuple(zero_ranges), archive_bytes


def _canonical_tar_chunk_matches(
    chunk: bytes,
    *,
    start: int,
    headers: Sequence[tuple[int, bytes]],
    zero_ranges: Sequence[tuple[int, int]],
) -> bool:
    end = start + len(chunk)
    for header_offset, expected in headers:
        header_end = header_offset + len(expected)
        overlap_start = max(start, header_offset)
        overlap_end = min(end, header_end)
        if overlap_start < overlap_end:
            actual_start = overlap_start - start
            expected_start = overlap_start - header_offset
            length = overlap_end - overlap_start
            if (
                chunk[actual_start : actual_start + length]
                != expected[expected_start : expected_start + length]
            ):
                return False
    for zero_start, zero_end in zero_ranges:
        overlap_start = max(start, zero_start)
        overlap_end = min(end, zero_end)
        if overlap_start < overlap_end and any(
            chunk[overlap_start - start : overlap_end - start]
        ):
            return False
    return True


def _validate_canonical_gzip_ustar(
    path: Path,
    descriptors: dict[str, dict[str, Any]],
    *,
    location: str,
    issues: list[VerificationIssue],
) -> bool:
    layout = _canonical_tar_layout(descriptors, location=location, issues=issues)
    if layout is None:
        return False
    headers, zero_ranges, expected_uncompressed_bytes = layout
    decompressor = zlib.decompressobj(16 + zlib.MAX_WBITS)
    decompressed_bytes = 0
    try:
        with path.open("rb") as handle:
            header = handle.read(len(_CANONICAL_GZIP_HEADER))
            if header != _CANONICAL_GZIP_HEADER:
                _issue(
                    issues,
                    "archive-gzip-header",
                    location,
                    "expected canonical gzip level-9 header with mtime=0 and OS=255",
                )
                return False
            handle.seek(0)
            gzip_eof = False
            while raw_chunk := handle.read(1024 * 1024):
                pending = raw_chunk
                drain_buffered_output = False
                while pending or drain_buffered_output:
                    drain_buffered_output = False
                    maximum = min(
                        1024 * 1024,
                        expected_uncompressed_bytes - decompressed_bytes + 1,
                    )
                    try:
                        output = decompressor.decompress(pending, maximum)
                    except zlib.error as error:
                        _issue(
                            issues,
                            "archive-gzip-stream",
                            location,
                            f"gzip stream, CRC32, or ISIZE is invalid: {error}",
                        )
                        return False
                    if not _canonical_tar_chunk_matches(
                        output,
                        start=decompressed_bytes,
                        headers=headers,
                        zero_ranges=zero_ranges,
                    ):
                        _issue(
                            issues,
                            "archive-ustar-layout",
                            location,
                            "archive bytes do not match the receipt-derived deterministic USTAR layout",
                        )
                        return False
                    decompressed_bytes += len(output)
                    if decompressed_bytes > expected_uncompressed_bytes:
                        _issue(
                            issues,
                            "archive-ustar-length",
                            location,
                            "decompressed USTAR has post-end payload or noncanonical padding length",
                        )
                        return False
                    pending = decompressor.unconsumed_tail
                    if decompressor.eof:
                        if decompressor.unused_data or pending or handle.read(1):
                            _issue(
                                issues,
                                "archive-gzip-trailing",
                                location,
                                "archive must contain exactly one gzip member through raw EOF",
                            )
                            return False
                        gzip_eof = True
                        break
                    if not pending and len(output) == maximum:
                        drain_buffered_output = True
                if gzip_eof:
                    break
            if not gzip_eof:
                _issue(
                    issues,
                    "archive-gzip-stream",
                    location,
                    "gzip stream or CRC32/ISIZE trailer is truncated",
                )
                return False
    except (EOFError, OSError, zlib.error) as error:
        _issue(issues, "archive-read", location, str(error))
        return False
    if decompressed_bytes != expected_uncompressed_bytes:
        _issue(
            issues,
            "archive-ustar-length",
            location,
            f"expected {expected_uncompressed_bytes} decompressed bytes, found {decompressed_bytes}",
        )
        return False
    return True


def _verify_replay_archive(
    path: Path, summary: dict[str, Any], issues: list[VerificationIssue]
) -> None:
    location = f"external_file[{path}]"
    runs = summary.get("runs")
    if not isinstance(runs, list):
        return
    expected_descriptors = _expected_replay_descriptors(
        summary, location=location, issues=issues
    )
    if expected_descriptors is None or not _validate_canonical_gzip_ustar(
        path, expected_descriptors, location=location, issues=issues
    ):
        return
    try:
        archive = tarfile.open(path, mode="r:gz", errorlevel=2)
    except (EOFError, OSError, tarfile.TarError, zlib.error) as error:
        _issue(issues, "archive-open", location, str(error))
        return
    with archive:
        if archive.pax_headers:
            _issue(
                issues,
                "archive-pax",
                location,
                "global pax headers are forbidden",
            )
        members: list[tarfile.TarInfo] = []
        try:
            for index, member in enumerate(archive):
                if index >= len(expected_descriptors):
                    _issue(
                        issues,
                        "archive-member-unexpected",
                        f"{location}.members[{index}]",
                        f"undeclared member {member.name!r}",
                    )
                    return
                members.append(member)
        except (EOFError, OSError, tarfile.TarError, zlib.error) as error:
            _issue(issues, "archive-read", location, str(error))
            return
        names = [member.name for member in members]
        if names != sorted(names):
            _issue(
                issues,
                "archive-member-order",
                location,
                "tar members must be lexicographically ordered",
            )
        if len(names) != len(set(names)):
            _issue(
                issues,
                "archive-member-duplicate",
                location,
                "duplicate tar member names are forbidden",
            )
        member_by_name: dict[str, tarfile.TarInfo] = {}
        for index, member in enumerate(members):
            member_location = f"{location}.members[{index}]"
            relative = _safe_relative_path(member.name)
            if relative is None or _has_hidden_component(relative):
                _issue(
                    issues,
                    "archive-member-path",
                    member_location,
                    f"unsafe or non-normalized member path {member.name!r}",
                )
                continue
            sparse = getattr(member, "sparse", None)
            if (
                member.type != tarfile.REGTYPE
                or not member.isfile()
                or member.linkname
                or sparse
            ):
                _issue(
                    issues,
                    "archive-member-type",
                    member_location,
                    "only nonsparse regular files are permitted; links and special files are forbidden",
                )
                continue
            if (
                member.mode != 0o644
                or member.uid != 0
                or member.gid != 0
                or member.mtime != 0
                or member.uname
                or member.gname
                or member.pax_headers
            ):
                _issue(
                    issues,
                    "archive-member-metadata",
                    member_location,
                    "members require mode=0644, uid/gid/mtime=0, and empty names/pax headers",
                )
            descriptor = expected_descriptors.get(member.name)
            if descriptor is None:
                _issue(
                    issues,
                    "archive-member-unexpected",
                    member_location,
                    f"member is not declared by the summary: {member.name!r}",
                )
                continue
            if member.size != descriptor.get("bytes"):
                _issue(
                    issues,
                    "archive-member-size",
                    member_location,
                    f"expected {descriptor.get('bytes')}, found {member.size}",
                )
            if member.name not in member_by_name:
                member_by_name[member.name] = member
        missing = sorted(set(expected_descriptors) - set(names))
        if missing:
            _issue(
                issues,
                "archive-member-missing",
                location,
                f"declared members are absent: {missing}",
            )
        if set(names) != set(expected_descriptors):
            _issue(
                issues,
                "archive-member-set",
                location,
                "tar member names must exactly equal the declared replay member set",
            )
        for member_name in sorted(expected_descriptors):
            descriptor = expected_descriptors[member_name]
            selected_member = member_by_name.get(member_name)
            if selected_member is None:
                continue
            try:
                member_stream = archive.extractfile(selected_member)
            except (EOFError, OSError, tarfile.TarError, zlib.error) as error:
                _issue(issues, "archive-member-read", member_name, str(error))
                continue
            if member_stream is None:
                _issue(
                    issues,
                    "archive-member-read",
                    member_name,
                    "unable to read regular member",
                )
                continue
            digest = hashlib.sha256()
            byte_count = 0
            try:
                with member_stream:
                    for chunk in iter(lambda: member_stream.read(1024 * 1024), b""):
                        byte_count += len(chunk)
                        digest.update(chunk)
            except (EOFError, OSError, tarfile.TarError, zlib.error) as error:
                _issue(issues, "archive-member-read", member_name, str(error))
                continue
            if byte_count != descriptor.get("bytes"):
                _issue(
                    issues,
                    "archive-member-bytes",
                    member_name,
                    f"expected {descriptor.get('bytes')}, found {byte_count}",
                )
            if digest.hexdigest() != descriptor.get("sha256"):
                _issue(
                    issues,
                    "archive-member-hash",
                    member_name,
                    f"expected {descriptor.get('sha256')}, found {digest.hexdigest()}",
                )
        for run_index, run in enumerate(runs):
            if isinstance(run, dict):
                try:
                    _verify_embedded_run(
                        archive,
                        member_by_name,
                        summary=summary,
                        run=run,
                        run_index=run_index,
                        issues=issues,
                    )
                except (EOFError, OSError, tarfile.TarError, zlib.error) as error:
                    _issue(
                        issues,
                        "archive-run-read",
                        f"{location}.runs[{run_index}]",
                        str(error),
                    )


def _validate_external_files(
    external_files: Sequence[tuple[str, Path]],
    declared: dict[str, dict[str, Any]],
    universal_summary: dict[str, Any] | None,
    issues: list[VerificationIssue],
) -> int:
    """Verify caller-supplied external bytes without network access."""

    seen: set[str] = set()
    verified = 0
    for index, (name, supplied_path) in enumerate(external_files):
        issue_count_before = len(issues)
        location = f"external_files[{index}]"
        if not isinstance(name, str):
            _issue(
                issues,
                "external-file-name",
                location,
                "external artifact names must be strings",
            )
            continue
        relative = _safe_relative_path(name)
        if relative is None or _has_hidden_component(relative):
            _issue(
                issues,
                "external-file-name",
                location,
                f"unsafe external artifact name {name!r}",
            )
            continue
        if name in seen:
            _issue(
                issues,
                "external-file-duplicate",
                location,
                f"external artifact {name!r} was supplied more than once",
            )
            continue
        seen.add(name)
        metadata = declared.get(name)
        if metadata is None:
            _issue(
                issues,
                "external-file-undeclared",
                location,
                f"external artifact {name!r} is not declared by the manifest",
            )
            continue
        path = Path(supplied_path).expanduser().absolute()
        current = Path(path.anchor)
        has_symlink_component = False
        for part in path.parts[1:]:
            current /= part
            if current.is_symlink():
                has_symlink_component = True
                break
        if has_symlink_component:
            _issue(
                issues,
                "external-file-symlink",
                str(path),
                "supplied external files must not be symbolic links",
            )
            continue
        if not path.is_file():
            _issue(
                issues,
                "external-file-missing",
                str(path),
                "supplied external artifact is not a regular file",
            )
            continue
        expected_bytes = metadata.get("bytes")
        actual_bytes = path.stat().st_size
        if expected_bytes != actual_bytes:
            _issue(
                issues,
                "external-file-bytes",
                str(path),
                f"expected {expected_bytes}, found {actual_bytes}",
            )
        expected_hash = metadata.get("sha256")
        actual_hash = _sha256(path)
        if expected_hash != actual_hash:
            _issue(
                issues,
                "external-file-hash",
                str(path),
                f"expected {expected_hash}, found {actual_hash}",
            )
        replay = universal_summary.get("replay_archive") if universal_summary else None
        if (
            universal_summary is not None
            and isinstance(replay, dict)
            and replay.get("external_artifact") == name
        ):
            try:
                _verify_replay_archive(path, universal_summary, issues)
            except _UNTRUSTED_SEMANTIC_ERRORS as error:
                _issue(
                    issues,
                    "archive-semantic-error",
                    str(path),
                    f"fail-closed semantic validation: {type(error).__name__}: {error!r}",
                )
        if len(issues) == issue_count_before and len(issues) < _MAX_VERIFICATION_ISSUES:
            verified += 1
    return verified


def _parse_checksums(path: Path, issues: list[VerificationIssue]) -> dict[str, str]:
    result: dict[str, str] = {}
    try:
        with path.open("rb") as handle:
            payload = handle.read(_MAX_CHECKSUM_FILE_BYTES + 1)
    except OSError as error:
        _issue(issues, "checksums-read", str(CHECKSUMS_PATH), str(error))
        return result
    if len(payload) > _MAX_CHECKSUM_FILE_BYTES:
        _issue(
            issues,
            "checksums-size",
            str(CHECKSUMS_PATH),
            f"checksum file exceeds {_MAX_CHECKSUM_FILE_BYTES} bytes",
        )
        return result
    start = 0
    line_number = 0
    while start < len(payload):
        line_number += 1
        newline = payload.find(b"\n", start)
        if newline < 0:
            end = len(payload)
            next_start = end
        else:
            end = newline
            next_start = newline + 1
        raw_line = payload[start:end]
        physical_bytes = next_start - start
        start = next_start
        location = f"{CHECKSUMS_PATH}:{line_number}"
        if physical_bytes > _MAX_CHECKSUM_LINE_BYTES:
            _issue(
                issues,
                "checksums-line-size",
                location,
                f"physical line exceeds {_MAX_CHECKSUM_LINE_BYTES} bytes including LF",
            )
            continue
        if raw_line.endswith(b"\r"):
            raw_line = raw_line[:-1]
        try:
            line = raw_line.decode("utf-8")
        except UnicodeDecodeError as error:
            _issue(
                issues,
                "checksums-encoding",
                location,
                f"checksum line is not valid UTF-8: {error}",
            )
            return result
        if not line or line.startswith("#"):
            continue
        match = re.fullmatch(r"([0-9a-f]{64})  (.+)", line)
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
    expected_roots = list(_CANONICAL_MANAGED_ROOTS)
    if not _json_equal(managed_roots, expected_roots):
        _issue(
            issues,
            "managed-root-config",
            "managed_roots",
            f"operational roots must be exactly {expected_roots!r}",
        )
        return found
    root = root.resolve(strict=False)
    for root_name in managed_roots:
        relative_root = _safe_relative_path(root_name)
        if (
            relative_root is None
            or len(relative_root.parts) != 1
            or root_name not in _CANONICAL_MANAGED_ROOTS
        ):
            _issue(
                issues,
                "managed-root-config",
                "managed_roots",
                f"unsafe operational root {root_name!r}",
            )
            return found
        managed = root.joinpath(*relative_root.parts)
        if managed.is_symlink() or not managed.is_dir():
            _issue(
                issues,
                "managed-root",
                root_name,
                "managed root must be a real directory",
            )
            continue
        try:
            managed.resolve(strict=False).relative_to(root)
        except ValueError:
            _issue(
                issues,
                "managed-root-config",
                root_name,
                "managed root resolves outside the repository",
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


def verify_repository(
    root: Path,
    *,
    external_files: Sequence[tuple[str, Path]] = (),
    expected_code_repository: str = DEFAULT_EXPECTED_CODE_REPOSITORY,
) -> VerificationReport:
    issues: list[VerificationIssue] = []
    root = root.resolve()
    if not isinstance(expected_code_repository, str) or not _format_matches(
        expected_code_repository, "uri"
    ):
        _issue(
            issues,
            "expected-code-repository",
            "$verifier.expected_code_repository",
            "expected code repository must be an explicit HTTP(S) repository URI",
        )
        return VerificationReport(str(root), str(MANIFEST_PATH), 0, tuple(issues))
    manifest_file = _resolve_regular_file(
        root, MANIFEST_PATH, str(MANIFEST_PATH), issues
    )
    if manifest_file is None:
        return VerificationReport(str(root), str(MANIFEST_PATH), 0, tuple(issues))
    try:
        manifest = _load_json(manifest_file)
    except (
        OSError,
        UnicodeError,
        json.JSONDecodeError,
        ValueError,
        RecursionError,
    ) as error:
        _issue(issues, "manifest-json", str(MANIFEST_PATH), str(error))
        return VerificationReport(str(root), str(MANIFEST_PATH), 0, tuple(issues))
    if not isinstance(manifest, dict):
        _issue(
            issues, "manifest-type", str(MANIFEST_PATH), "manifest must be an object"
        )
        return VerificationReport(str(root), str(MANIFEST_PATH), 0, tuple(issues))

    raw_schema_reference = manifest.get("$schema")
    schema_reference = (
        _safe_relative_path(raw_schema_reference)
        if isinstance(raw_schema_reference, str)
        else None
    )
    if schema_reference not in TRUSTED_MANIFEST_SCHEMAS:
        permitted = ", ".join(
            repr(path.as_posix()) for path in sorted(TRUSTED_MANIFEST_SCHEMAS)
        )
        _issue(
            issues,
            "manifest-schema-reference",
            str(MANIFEST_PATH),
            f"$schema must be one of the exact trusted references: {permitted}",
        )
        return VerificationReport(str(root), str(MANIFEST_PATH), 0, tuple(issues))
    schema = _load_trusted_schema(root, schema_reference, "$schema", issues)
    if schema is None:
        return VerificationReport(str(root), str(MANIFEST_PATH), 0, tuple(issues))
    _validate_instance(manifest, schema, "$manifest", issues)
    if len(issues) >= _MAX_VERIFICATION_ISSUES:
        return VerificationReport(str(root), str(MANIFEST_PATH), 0, tuple(issues))

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

    raw_external_artifacts = manifest.get("external_artifacts", [])
    external_artifacts = (
        raw_external_artifacts if isinstance(raw_external_artifacts, list) else []
    )
    external_names = [
        raw_name
        for artifact in external_artifacts
        if isinstance(artifact, dict)
        and isinstance(raw_name := artifact.get("name"), str)
    ]
    external_urls = [
        raw_url
        for artifact in external_artifacts
        if isinstance(artifact, dict)
        and isinstance(raw_url := artifact.get("url"), str)
    ]
    if external_names != sorted(external_names):
        _issue(
            issues,
            "external-artifact-order",
            "external_artifacts",
            "external artifacts must be sorted by name",
        )
    if len(external_names) != len(set(external_names)):
        _issue(
            issues,
            "external-artifact-duplicate",
            "external_artifacts",
            "external artifact names must be unique",
        )
    if external_urls != sorted(external_urls):
        _issue(
            issues,
            "external-url-order",
            "external_artifacts",
            "external artifact URLs must be sorted",
        )
    if len(external_urls) != len(set(external_urls)):
        _issue(
            issues,
            "external-url-duplicate",
            "external_artifacts",
            "external artifact URLs must be unique",
        )
    path_collisions = sorted(set(paths) & set(external_names))
    if path_collisions:
        _issue(
            issues,
            "artifact-namespace-collision",
            "external_artifacts",
            f"local paths and external names collide: {path_collisions}",
        )
    external_by_name: dict[str, dict[str, Any]] = {}
    for index, artifact in enumerate(external_artifacts):
        if not isinstance(artifact, dict):
            continue
        raw_name = artifact.get("name")
        relative_name = (
            _safe_relative_path(raw_name) if isinstance(raw_name, str) else None
        )
        if relative_name is None:
            continue
        if _has_hidden_component(relative_name):
            _issue(
                issues,
                "external-artifact-hidden",
                f"external_artifacts[{index}].name",
                "external artifact names may not contain hidden components",
            )
            continue
        canonical_name = relative_name.as_posix()
        if canonical_name not in external_by_name:
            external_by_name[canonical_name] = artifact

    release = manifest.get("release", {})
    release_status = release.get("status") if isinstance(release, dict) else None
    release_repository = (
        release.get("code_repository") if isinstance(release, dict) else None
    )
    release_commit = release.get("code_commit") if isinstance(release, dict) else None
    if release_repository != expected_code_repository:
        _issue(
            issues,
            "release-code-repository",
            "release.code_repository",
            f"must exactly equal trusted repository {expected_code_repository!r}",
        )
    if isinstance(release_status, str) and release_status in {
        "candidate",
        "published",
    }:
        if not _is_nonzero_git_commit(release.get("code_commit")):
            _issue(
                issues,
                "release-provenance",
                "release.code_commit",
                "candidate and published releases require a nonzero 40-hex commit",
            )

    declared_managed_roots = manifest.get("managed_roots")
    managed_roots = (
        list(_CANONICAL_MANAGED_ROOTS)
        if _json_equal(declared_managed_roots, list(_CANONICAL_MANAGED_ROOTS))
        else []
    )
    expected_hashes: dict[str, str] = {}
    result_record_locations: dict[str, str] = {}
    universal_summary_location: str | None = None
    universal_summary_record: dict[str, Any] | None = None
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
            elif raw_record_schema not in {
                path.as_posix() for path in TRUSTED_RESULT_SCHEMAS
            }:
                permitted = ", ".join(
                    path.as_posix() for path in sorted(TRUSTED_RESULT_SCHEMAS)
                )
                _issue(
                    issues,
                    "result-schema",
                    f"{location}.schema",
                    f"result artifacts must use a trusted result schema: {permitted}",
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
            except (
                OSError,
                UnicodeError,
                json.JSONDecodeError,
                ValueError,
                RecursionError,
            ) as error:
                _issue(issues, "artifact-json", str(relative), str(error))
                continue
            _validate_instance(record, record_schema, str(relative), issues)
            if record_schema_relative == RESULT_SCHEMA_PATH:
                _validate_result_semantics(
                    record,
                    str(relative),
                    expected_code_repository,
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
            elif record_schema_relative == UNIVERSAL_SUMMARY_SCHEMA_PATH:
                if role != "result":
                    _issue(
                        issues,
                        "summary-role",
                        f"{location}.role",
                        "universal census summaries must use the result role",
                    )
                if not _is_json_media_type(artifact.get("media_type")):
                    _issue(
                        issues,
                        "summary-media-type",
                        f"{location}.media_type",
                        "universal census summaries require a JSON media type",
                    )
                if universal_summary_location is not None:
                    _issue(
                        issues,
                        "summary-duplicate",
                        str(relative),
                        f"a universal census summary is already declared at {universal_summary_location}",
                    )
                else:
                    universal_summary_location = str(relative)
                    if isinstance(record, dict):
                        universal_summary_record = record
                try:
                    _validate_universal_summary_semantics(
                        record,
                        str(relative),
                        expected_code_repository,
                        release_commit,
                        external_by_name,
                        issues,
                    )
                except _UNTRUSTED_SEMANTIC_ERRORS as error:
                    _issue(
                        issues,
                        "summary-semantic-error",
                        str(relative),
                        (
                            "fail-closed semantic validation: "
                            f"{type(error).__name__}: {error!r}"
                        ),
                    )
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

    external_files_verified = _validate_external_files(
        external_files, external_by_name, universal_summary_record, issues
    )

    return VerificationReport(
        str(root),
        str(MANIFEST_PATH),
        len(artifacts),
        tuple(issues),
        external_artifact_count=len(external_artifacts),
        external_files_verified=external_files_verified,
    )


def _external_file_argument(value: str) -> tuple[str, Path]:
    name, separator, raw_path = value.partition("=")
    if not separator or not name or not raw_path:
        raise argparse.ArgumentTypeError("expected NAME=PATH")
    return name, Path(raw_path)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="repository root")
    parser.add_argument(
        "--json", action="store_true", help="emit machine-readable report"
    )
    parser.add_argument(
        "--expected-code-repository",
        default=DEFAULT_EXPECTED_CODE_REPOSITORY,
        metavar="URL",
        help=(
            "trusted generating code repository required exactly in the manifest and "
            "result provenance; override explicitly only when reusing the verifier"
        ),
    )
    parser.add_argument(
        "--external-file",
        action="append",
        default=[],
        type=_external_file_argument,
        metavar="NAME=PATH",
        help=(
            "verify supplied bytes for one declared external artifact; repeatable and "
            "never downloads from the network"
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    report = verify_repository(
        args.root,
        external_files=args.external_file,
        expected_code_repository=args.expected_code_repository,
    )
    if args.json:
        print(json.dumps(asdict(report), indent=2, sort_keys=True))
    elif report.ok:
        print(
            "OK: "
            f"{report.artifact_count} local artifact(s), "
            f"{report.external_artifact_count} external binding(s), and "
            f"{report.external_files_verified} supplied external file(s) verified "
            f"under {report.root}"
        )
    else:
        print(f"FAILED: {len(report.issues)} verification issue(s)", file=sys.stderr)
        for issue in report.issues:
            print(
                f"  [{issue.code}] {issue.location}: {issue.message}", file=sys.stderr
            )
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
