# ADR-0014: ProviderBinding schemas and offline target validation

## Authority and policy status

Resource Model v0.1 §§5–6, 11–12.3 and 17 defines the ProviderBinding shape and
separates capability, selector, Provider instance and driver. ADR-0009 §5 proposes
an incremental offline architecture; ADR-0013 implements Provider instances.
Issue #30 authorizes this narrow declaration increment, not selection/execution.

The requiredness, literal selector subset and explicit priority below are internal
M2.6 decisions based on the normative example, subject to independent PR review.
They do not silently edit the normative document or either API namespace. No
capability catalogue, driver-support assumption or lifecycle default is introduced.

## Typed declaration

`ProviderBinding(ResourceBase)` has exact `kind: Literal["ProviderBinding"]` and
required `ProviderBindingSpec`. Strict discriminated dispatch and exports through
`diatonic.model` include ProviderBinding, ProviderBindingSpec, ProviderBindingMatch
and ProviderReference. All existing kinds and shared envelope fields are preserved.

All four spec fields are required, with no implicit values:

| Field | Initial schema |
| --- | --- |
| `capability` | Strict nonempty slash/whitespace-free ResourceName; opaque, no allowlist |
| `match` | Strict ProviderBindingMatch object with required `kind` |
| `provider` | Existing ResourceReference syntax plus exact Provider-kind constraint |
| `priority` | Strict signed integer, with no positivity bound or default |

Unknown resource/spec/match keys fail. ProviderReference reuses the canonical
parser and existing exact-kind validator pattern, rather than adding another
reference parser. Wrong kinds, malformed names, null and coercible non-string
values fail schema validation before target existence checking.

## Selector and priority policies

`match.kind` is a case-sensitive ResourceName, with no restriction to currently
implemented kinds or currently declared resources. `match.labels` is an optional
string-to-string mapping with a fresh `{}` default; explicit `{}` is valid and
explicit null is invalid. It is independent of the binding's own metadata labels.

The initial literal selector subset rejects nested expression objects, unknown
operator/expression fields and glob/operator characters `*?[]!=<>|&` in kind,
label keys and label values. Rejecting those characters is a conservative M2.6
syntax restriction, not a global ResourceName or metadata-label change. It avoids
silently accepting wildcard/comparison shorthand. Remaining strings are literal;
no expression parser, interpolation or glob evaluator is added. Expanding this
subset (including literal uses of those reserved characters) requires review.

Intended **future** selection is exact kind equality and exact conjunction of all
listed labels. A missing label would not match; kind-only selectors have no label
conditions. This increment performs no matching or requirement that a selected
resource exists, and does not derive capabilities from kinds/phases.

Negative, zero and positive priorities are valid; bool, float, numeric string and
null fail. Highest numeric value winning remains the **proposed future direction**
from ADR-0009, to be reviewed for M2.8. No priority comparison, winner, ambiguity
check or hidden specificity ordering occurs here. Equal priorities, even multiple
bindings to the same Provider, are valid declarations.

## Separate validation API and immutable summaries

`diatonic.compiler.provider_bindings.validate_provider_bindings(index:
ResourceIndex) -> ValidatedProviderBindings` consumes the existing resolved index.
It visits bindings in case-sensitive canonical identity order, looks up the exact
spec.provider identity, and requires a typed Provider whose identity agrees with
its index key. There is no name/kind/driver fallback. Provider configs and drivers
are never interpreted or copied into the result.

The API returns frozen/slotted records:

- `declarations`: canonical binding-identity tuple of `BindingDeclaration` values:
  owner identity, Provider identity, opaque capability, selector kind, owned
  read-only label mapping sorted by key, declared priority, and exact
  `("spec", "provider")` field path. This is a declaration summary, not selection.
- `sources`: owned read-only mapping sorted by identity, containing detached
  frozen/slotted `BindingSource` records for all bindings and referenced Providers.
  Each records path, document index and available document-root line/column.

Portable comparisons use declarations alone; full result equality includes real
provenance. Input YAML, mutable models, reference records, existing IR and graph
analyses are not modified. Later input mutation cannot alter completed summaries;
IR still preserves omission versus explicit empty labels through exclude_unset.

Inputs must be successful, unmodified resolver results. Focused guards check
binding records/identities/specs, typed Provider targets and root provenance.
Binding specs are revalidated using their existing model schema to catch mutable
field corruption; no parallel schema rules or YAML/index resolver are introduced.
Unrelated resources are not revalidated. A same-type valid edit before analysis
has no historical snapshot to compare against; callers must resolve again after
editing inputs. No freshness/state framework is added.

## Diagnostics and CLI composition

`ProviderBindingValidationError.diagnostic` is a frozen/slotted `BindingDiagnostic`:

- `missing_binding_provider`: an exact Provider identity is undeclared.
- `invalid_binding_input`: obvious inconsistent/corrupted binding or target input.

Diagnostics include owner, Provider target when available, exact spec.provider
context, detached binding-root provenance when available, and a message. Invalid
target provenance retains available binding provenance. Unknown positions remain
unspecified; root coordinates never claim exact field locations. Wrong top-level
API argument types raise TypeError. Fail fast without returning partial results;
valid inputs select the first missing target by sorted binding identity, never
filename, document order, priority or matching specificity.

Both validate and graph call this static check after existing M1 resolution/IPv4
validation and before normalization or successful output. Expected failures exit
1 on stderr only, rendered literally without config contents or tracebacks.
Usage errors remain 2. Inputs without bindings preserve previous output and checks.
No capability/driver support or connectivity requirement is added.

## Infrastructure graph boundary and deferred work

M1.5 `_declared_references`, ResourceIndex.references and M2.1 classification are
unchanged. **spec.provider is a configuration link, not a dependency.** It creates
no graph edge, Stage assignment or normalized reference entry. Provider and binding
still appear as logical vertices. Only ordinary shared depends_on contributes
edges, while lifecycle.stage remains a separate rank relation. Explicit depends_on
is allowed even when it repeats a binding's Provider target. Existing CLI reference
counts continue to count M1.5 links, excluding this separately checked relation.

M2.8 can consume the immutable summaries as declarations while separately checking
requested capabilities and supplied driver compatibility. Outstanding review gates
include capability mappings, selectors, priority direction and same-Provider/equal-
priority ties. This API supplies no selection or execution-ready object.

Provider discovery/imports, descriptors, installation, authentication, secret
lookup, interpolation, live/mock execution, scheduling, state/journals, planning,
plan/apply and deletion remain deferred. No graph/Stage algorithm or versioned
serialization changes are introduced.
