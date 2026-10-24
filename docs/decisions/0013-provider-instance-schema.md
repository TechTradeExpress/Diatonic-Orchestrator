# ADR-0013: Portable Provider instance declarations

## Authority and scope

Resource Model v0.1 §§3.3–3.5, 5–6 and 12.1–12.3 distinguishes a driver
implementation ID from a named Provider instance, ProviderBinding and capability.
M2.5 implements the Provider declaration shape illustrated in §12.2. It adds no
provider selection or execution. This ADR settles narrow schema choices where
that illustration leaves omission semantics open; the normative document and
`iac/v0alpha1` / `iac-provider/v0alpha1` namespaces remain unchanged.

## Typed schema and requiredness

`diatonic.model.Provider` extends `ResourceBase` with exact
`kind: Literal["Provider"]` and required `spec: ProviderSpec`. `ProviderSpec`
extends the existing `StrictModel`:

- Required `driver: ResourceName` uses strict, non-empty single-segment string
  validation: no slashes or whitespace, and no numeric/bool/bytes coercion.
  `terraform.proxmox`, `native.proxmox` and arbitrary future valid identifiers are
  accepted without allowlists or parsing engine/platform/capability semantics.
- Required `config: dict[str, JsonValue]` permits `{}` but rejects omission, null
  and non-mapping top-level values. **Explicit config requiredness is an M2.5
  design decision based on the demonstrated shape**, not an omission rule fully
  specified by the normative Resource Model. An explicit mapping avoids inventing
  an implicit empty-config default. Different omission behavior requires review.

Unknown spec fields fail through the existing extra-forbid policy. Unknown keys
inside config are retained intentionally. There is no provider-specific core
configuration schema or extension registry. Existing shared strict metadata,
API version, lifecycle, explicit dependencies and `extensions.<platform>` behavior
remain intact. Portable infrastructure resource specs gain no provider fields.

The discriminated Resource union and `parse_resource` dispatch the exact Provider
kind; Provider and ProviderSpec are exported through `diatonic.model`.
ProviderBinding remains unsupported until its separately scoped M2.6 increment.

## Driver identity versus resource identity

Canonical identity remains `Kind/name`, using metadata rather than the driver:

```yaml
api_version: iac/v0alpha1
kind: Provider
metadata:
  name: primary
spec:
  driver: example.driver
  config: {}
```

This is `Provider/primary`, never `Provider/example.driver`. Another named instance
may use the same driver with independent configuration. Duplicate Provider/name
values fail existing indexing; identical names under different kinds are valid.
Driver IDs do not prove installation, availability, capabilities or connectivity.
The example driver is illustrative and need not exist.

## Opaque JSON and secret references

Config preserves deeply nested strings, booleans, finite ints/floats, nulls, lists
and string-keyed mappings. Existing strict recursive Pydantic `JsonValue`
validation and `allow_inf_nan=False` reject non-string keys, non-finite floats and
non-JSON Python values (e.g. bytes, tuples, sets, datetime, Decimal and arbitrary
objects) without conversion. Unknown nested keys and meaningful list ordering
survive model dumps, strict YAML loading and normalized IR serialization.

For example, this config fragment is data only:

```yaml
credentials:
  token:
    secret_ref: example/token
```

No secret is resolved or validated, no expressions/environment variables are
expanded, and a config key such as `ref`, `network`, `stage` or `secret_ref` does
not become a compiled reference. Canonical-looking strings inside config are
also opaque. Examples and tests use fictional references and reserved `.invalid`
endpoints, never actual credentials or infrastructure endpoints.

Models follow the existing mutable Pydantic convention. Independently validated
config mappings own independent nested containers. Existing resolver detachment
and immutable normalized IR snapshots protect completed compiler results from
later YAML/model mutations; exports return detached data and canonical JSON.
Source provenance stays separate from portable data. Normal CLI output does not
print driver/config contents, and the existing resolver's schema diagnostics omit
Pydantic input values; this is not a new secret store or a general redaction engine.

## Compiler and lifecycle compatibility

No compiler or CLI algorithm changes are necessary. Provider uses the existing
loader, resolver, IPv4 pass (which has no Provider-specific work), normalization,
classification, graph, Stage analyzer, validate CLI and graph CLI unchanged.

Only ordinary explicit depends_on and optional lifecycle.stage produce recorded
links. A reference-free Provider is an isolated vertex. An explicit dependency
**on** `Provider/primary` remains a prerequisite → dependent edge, and a Provider's
own explicit dependencies work the same way. A lifecycle Stage assignment is a
separate rank relation, not an inferred edge. The existing Stage-group ordering
policy applies when a Provider is explicitly assigned; no default assignment or
lifecycle ownership is added. This does not decide how a future operation would
process a Provider's lifecycle phases.

ProviderBinding schemas, capability vocabularies, selection, driver compatibility
metadata, discovery/dynamic imports, configuration interpretation, secret lookup,
connectivity, execution (including mocks), scheduling, planning, state/journals,
plan/apply and deletion remain outside this increment. Declaring a Provider never
initializes a driver or causes network activity. The implementation remains offline.
