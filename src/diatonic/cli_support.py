"""Read the unversioned, CLI-only offline driver-support JSON input."""

import json
import math
from pathlib import Path

from diatonic.compiler.capabilities import (
    DriverSupportDescriptor,
    DriverSupportError,
    DriverSupportMetadata,
)


class SupportMetadataError(ValueError):
    """Expected local input error; messages never echo file contents."""

    def __init__(self, path: Path, code: str, message: str) -> None:
        self.source_path = path
        self.code = code
        super().__init__(f"{path}: {code}: {message}")


class _InvalidJson(ValueError):
    pass


def _object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise _InvalidJson("duplicate JSON object keys are not allowed")
        result[key] = value
    return result


def _constant(value: str) -> object:
    raise _InvalidJson("non-finite JSON numbers are not allowed")


def _integer(value: str) -> object:
    raise _InvalidJson("numeric values are not valid support declarations")


def _float(value: str) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise _InvalidJson("non-finite JSON numbers are not allowed")
    return number


def load_support_metadata(path: Path) -> DriverSupportMetadata:
    """Strict local JSON adapter; identifier/duplicate rules remain M2.7's."""
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeError:
        raise SupportMetadataError(
            path, "support_metadata_decode_error", "expected UTF-8 JSON"
        ) from None
    except OSError:
        raise SupportMetadataError(
            path, "support_metadata_read_error", "cannot read support metadata file"
        ) from None
    try:
        data = json.loads(
            text,
            object_pairs_hook=_object,
            parse_constant=_constant,
            parse_float=_float,
            parse_int=_integer,
        )
    except json.JSONDecodeError as error:
        raise SupportMetadataError(
            path,
            "invalid_support_metadata",
            f"malformed JSON at line {error.lineno}, column {error.colno}",
        ) from None
    except (_InvalidJson, RecursionError) as error:
        message = (
            str(error)
            if isinstance(error, _InvalidJson)
            else "JSON nesting is too deep"
        )
        raise SupportMetadataError(path, "invalid_support_metadata", message) from None
    if (
        type(data) is not dict
        or set(data) != {"drivers"}
        or type(data["drivers"]) is not list
    ):
        raise SupportMetadataError(
            path, "invalid_support_metadata", "expected exactly a drivers array"
        )
    descriptors = []
    for entry in data["drivers"]:
        if (
            type(entry) is not dict
            or set(entry) != {"driver_id", "capabilities"}
            or type(entry["capabilities"]) is not list
        ):
            raise SupportMetadataError(
                path,
                "invalid_support_metadata",
                "each driver must contain exactly driver_id and a capabilities array",
            )
        try:
            descriptors.append(
                DriverSupportDescriptor(entry["driver_id"], entry["capabilities"])
            )
        except DriverSupportError as error:
            raise SupportMetadataError(
                path,
                error.diagnostic.code,
                "invalid driver/capability declaration; "
                "use strict identifiers and unique capabilities",
            ) from None
    try:
        return DriverSupportMetadata(tuple(descriptors))
    except DriverSupportError as error:
        raise SupportMetadataError(
            path, error.diagnostic.code, "driver declarations must be unique"
        ) from None
