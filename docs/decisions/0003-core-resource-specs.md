# M1.2: Typed Stage and VirtualMachine core specs

The normative contract remains `docs/resource-model/v0alpha1.md`.

- `Stage` requires `spec.order` as a strict integer. The contract defines no
  bounds, so zero and negative values are accepted; stage scheduling is deferred.
- `VirtualMachine` currently validates only the CPU and memory core fragment:
  required positive strict integers at `spec.cpu.cores` and `spec.memory.mib`.
  This is not yet a validator for the entire public VM contract. Placement,
  interfaces, disks and image are deferred to schema completion and currently
  rejected as unknown fields, rather than accepted without validation.
- `Resource` is an explicit discriminated union of these two implemented kinds.
  `parse_resource` validates already decoded documents using a Pydantic TypeAdapter;
  it does not load YAML or resolve references. Unsupported kinds fail validation.
- Concrete resources inherit the common envelope and narrow its `kind` and
  `spec` fields. `ResourceBase` remains an envelope-only validator, including its
  generic JSON-compatible spec support. Lifecycle omissions remain unspecified.
- No API namespace or lifecycle semantics change is introduced.
