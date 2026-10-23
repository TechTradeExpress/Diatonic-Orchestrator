# M1.3: Strict YAML loading policy

The loader decodes explicit files into mappings with separate provenance. It does
not validate Resource Model kinds, API versions, fields or references, and changes
neither API namespace nor lifecycle semantics.

- Files are UTF-8 with an optional BOM. Read/decoding failures become
  `YamlLoadError` with file context. Paths are retained as supplied, not resolved.
- `load_yaml_files` preserves caller iteration order, including repeated paths;
  documents keep stream order. There is no sorting, discovery or deduplication.
  An empty path iterable yields an empty list. A failure returns no partial list.
- Each document must decode to a dictionary. Empty streams, empty/null documents
  and other root values fail; an explicitly written empty mapping is accepted.
- All mapping keys must resolve to strings. Duplicate decoded string keys are
  rejected at every depth, including mappings inside lists. Quote keys such as
  `true`, `null` or numeric values when a string is intended.
- YAML merge keys are rejected before construction, even without conflicts.
  Quoted `"<<"` remains an ordinary string key.
- Anchor declarations are accepted, but **all alias references are rejected**
  during composition, including nonrecursive aliases. This narrow initial policy
  prevents cyclic structures, shared mutable subtrees and alias expansion attacks
  without implementing a configuration composition framework. Write values
  explicitly instead. No anchor expansion semantics become part of the contract.
- PyYAML SafeLoader handles tags and scalar resolution without global changes.
  Custom/unsafe tags fail. Standard safe scalar resolution is retained (including
  YAML 1.1 booleans and timestamps); later model validation owns type constraints.
  Nested safe tagged values are not normalized into JSON by the loader.
- `LoadedDocument` freezes the record fields, not the decoded dictionary. Source
  path, document index and root line/column are separate from resource data. All
  indexes/locations are 1-based; the root starts after markers and comments.
- `YamlLoadError` exposes `code`, `reason`, `source_path`, `document_index`, `line`
  and `column`. Unavailable positions are `None` (not guessed), notably for I/O,
  decoding and parser nesting exhaustion. Syntax errors use PyYAML's problem mark.
  Loading stops at the first error. Per-field source maps and aggregation are
  deferred. This in-memory loader does not impose byte or document count limits.
