# M1.1: Resource envelope implementation notes

The normative Resource Model is `docs/resource-model/v0alpha1.md`. This note
records deliberately conservative implementation behavior; it does **not**
change the public Resource Model contract.

- `ResourceBase` validates only the common envelope, not the set of supported
  resource kinds or the content of kind-specific `spec`. Typed kinds and their
  discriminators follow in the next M1 increment.
- `metadata.name` and the segments of `Kind/name` reject empty strings,
  whitespace and `/`, preserving exact case. Other naming constraints are not
  imposed while the versioned contract lacks a stricter grammar.
- `depends_on` references receive **syntax** validation only. Existence,
  correct kind and duplicates across documents require a compiler index and
  are deferred to the dedicated reference-resolution M1 step.
- The Resource Model defines no default lifecycle ownership, desired state or
  `prevent_destroy` value. Accordingly omitted fields remain `None`, rather
  than silently enabling management or destruction. Execution semantics for
  omission remain a design question for later milestones.
- `spec` and platform-specific `extensions` are checked for JSON-compatible
  structure at the envelope layer, without Terraform or vendor-specific
  validation. Concrete kind models narrow `spec` later.
