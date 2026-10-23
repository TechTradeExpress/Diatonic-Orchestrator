"""Strict YAML decoding with provenance kept outside resource data."""

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

import yaml
from yaml.error import Mark, MarkedYAMLError
from yaml.events import AliasEvent
from yaml.nodes import MappingNode, Node, ScalarNode, SequenceNode


@dataclass(frozen=True)
class LoadedDocument:
    """Decoded mapping and its 1-based root location; data remains mutable."""

    data: dict[str, object]
    source_path: Path
    document_index: int
    line: int
    column: int


class YamlLoadError(ValueError):
    """Controlled diagnostic; unavailable document/location fields are None."""

    def __init__(
        self,
        source_path: Path,
        code: str,
        reason: str,
        document_index: int | None = None,
        line: int | None = None,
        column: int | None = None,
    ) -> None:
        self.source_path = source_path
        self.code = code
        self.reason = reason
        self.document_index = document_index
        self.line = line
        self.column = column
        location = str(source_path)
        if line is not None:
            location += f":{line}:{column}"
        if document_index is not None:
            location += f" (document {document_index})"
        super().__init__(f"{location}: {code}: {reason}")


class _PolicyError(MarkedYAMLError):
    def __init__(self, code: str, reason: str, mark: Mark) -> None:
        self.code = code
        super().__init__(problem=reason, problem_mark=mark)


class _StrictSafeLoader(yaml.SafeLoader):
    def construct_object(self, node: Node, deep: bool = False) -> object:
        try:
            return super().construct_object(node, deep=deep)
        except (ValueError, KeyError, IndexError, AttributeError, OverflowError) as exc:
            # SafeLoader's scalar constructors can leak built-in exceptions for
            # invalid explicit tags or out-of-range timestamps.
            if not isinstance(node, ScalarNode):
                raise
            raise _PolicyError(
                "invalid_scalar", f"invalid scalar for YAML tag {node.tag}",
                node.start_mark,
            ) from exc

    def compose_node(self, parent: Node | None, index: object) -> Node:
        if self.check_event(AliasEvent):
            event = self.peek_event()
            raise _PolicyError(
                "alias_not_allowed",
                "YAML aliases are not supported; write the value explicitly",
                event.start_mark,
            )
        return super().compose_node(parent, index)


def _check_mapping_keys(root: Node) -> None:
    # Aliases are rejected during composition, so this is an acyclic tree.
    # Inspect every mapping, including those nested inside sequences/tagged nodes.
    pending = [root]
    while pending:
        node = pending.pop()
        if isinstance(node, MappingNode):
            seen: set[str] = set()
            children = []
            for key, value in node.value:
                if key.tag == "tag:yaml.org,2002:merge":
                    raise _PolicyError(
                        "merge_not_allowed", "YAML merge keys are not supported",
                        key.start_mark,
                    )
                if (
                    not isinstance(key, ScalarNode)
                    or key.tag != "tag:yaml.org,2002:str"
                ):
                    raise _PolicyError(
                        "invalid_mapping_key", "mapping keys must be strings",
                        key.start_mark,
                    )
                if key.value in seen:
                    raise _PolicyError(
                        "duplicate_key", f"duplicate mapping key {key.value!r}",
                        key.start_mark,
                    )
                seen.add(key.value)
                children.append(value)
            pending.extend(reversed(children))
        elif isinstance(node, SequenceNode):
            pending.extend(reversed(node.value))


def load_yaml_file(path: str | Path) -> list[LoadedDocument]:
    """Read UTF-8 (optional BOM), returning all documents or the first error.

    No schema validation, discovery, merge expansion or alias expansion occurs.
    Root locations refer to the mapping node, after any document marker/comments.
    """
    source_path = Path(path)
    try:
        text = source_path.read_text(encoding="utf-8-sig")
    except UnicodeError as exc:
        raise YamlLoadError(source_path, "decode_error", str(exc)) from exc
    except OSError as exc:
        raise YamlLoadError(source_path, "read_error", str(exc)) from exc

    documents: list[LoadedDocument] = []
    loader = None
    document_index = 1
    try:
        loader = _StrictSafeLoader(text)
        while loader.check_data():
            node = loader.get_node()
            if isinstance(node, ScalarNode) and node.tag == "tag:yaml.org,2002:null":
                raise _PolicyError(
                    "empty_document", "empty/null YAML documents are not allowed",
                    node.start_mark,
                )
            if not isinstance(node, MappingNode):
                raise _PolicyError(
                    "invalid_root", "document root must be a mapping", node.start_mark,
                )
            _check_mapping_keys(node)
            data = loader.construct_document(node)
            # Safe YAML tags such as !!set are mapping nodes but decode to non-dicts.
            if not isinstance(data, dict):
                raise _PolicyError(
                    "invalid_root", "document root must decode to a mapping",
                    node.start_mark,
                )
            documents.append(LoadedDocument(
                data=data, source_path=source_path, document_index=document_index,
                line=node.start_mark.line + 1, column=node.start_mark.column + 1,
            ))
            document_index += 1
        if not documents:
            raise YamlLoadError(
                source_path, "empty_document", "file contains no YAML documents",
                document_index=1, line=1, column=1,
            )
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None)
        raise YamlLoadError(
            source_path,
            getattr(exc, "code", "invalid_yaml"),
            getattr(exc, "problem", None) or str(exc),
            document_index=document_index,
            line=mark.line + 1 if mark else None,
            column=mark.column + 1 if mark else None,
        ) from exc
    except RecursionError as exc:
        raise YamlLoadError(
            source_path, "excessive_nesting", "YAML exceeds parser nesting capacity",
            document_index=document_index,
        ) from exc
    finally:
        if loader is not None:
            loader.dispose()
    return documents


def load_yaml_files(paths: Iterable[str | Path]) -> list[LoadedDocument]:
    """Preserve caller path order (including repeats), then in-file document order.

    Empty input returns an empty list. Fail fast without returning partial results.
    """
    return [document for path in paths for document in load_yaml_file(path)]
