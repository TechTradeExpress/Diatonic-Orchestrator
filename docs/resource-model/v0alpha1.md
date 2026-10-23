# Diatonic Orchestrator — Resource Model v0.1 and Technology Decision

> **Status:** Draft / design proposal  
> **Resource Model API:** `iac/v0alpha1`  
> **Project license:** MIT  
> **Project name:** Diatonic Orchestrator (`TechTradeExpress/diatonic-orchestrator`)  
> **CLI:** `diatonic`  
> **Python package:** `diatonic-orchestrator` (`diatonic` module)  
> **API namespace:** `iac/v0alpha1` (unchanged by rebranding)  
> **Date:** 2026-09-23

## 1. Purpose

The project is intended to be an open-source, provider-agnostic orchestration layer for Infrastructure as Code, with an initial focus on on-premise, homelab, SMB, edge and mixed-vendor infrastructure.

The core idea is:

> **Infrastructure should describe what a resource is and what state is desired, not which tool happens to create it.**

The tool is **not** intended to replace Terraform/OpenTofu, Ansible, Pulumi, vendor APIs or configuration-management systems. Instead, those systems are execution backends used by providers.

The project should provide:

- a portable logical resource model,
- validation and normalization of configuration,
- resource identity and references,
- lifecycle phases,
- dependency graph construction,
- stage-aware orchestration,
- capability-based provider resolution,
- provider-specific extensions without polluting the portable model,
- a common provider execution contract,
- plan/apply/observe operations spanning multiple execution engines,
- an execution journal and cross-provider outputs,
- an extensible CLI comparable in ergonomics to tools such as Laravel Artisan.

Atmos is treated as the primary benchmark. The project should not exist merely to reproduce Atmos features such as YAML configuration, workflows, validation, scaffolding or Terraform/Ansible command orchestration. Its reason to exist is the higher-level **resource → capability → provider → driver** abstraction.

---

## 2. Non-goals for v0.1

The first version should deliberately avoid becoming a new Terraform, Ansible or Kubernetes.

The MVP does **not** implement:

- a replacement Terraform state engine,
- its own SSH configuration-management engine,
- its own secret-management product,
- continuous reconciliation/controller mode,
- a custom programming or templating language,
- arbitrary loops and conditionals in configuration,
- automatic cross-hypervisor migration,
- direct native support for dozens of vendors,
- a general CI/CD engine,
- a distributed control plane,
- a database-backed inventory service.

The initial goal is to prove one architectural hypothesis:

> **Can a useful infrastructure model resolve logical resources and lifecycle phases into interchangeable providers without leaking implementation details into the core resource definitions?**

---

# 3. Architectural principles

## 3.1. Intent before implementation

A resource describes desired intent:

```yaml
api_version: iac/v0alpha1
kind: VirtualMachine

metadata:
  name: docker01

spec:
  cpu:
    cores: 4

  memory:
    mib: 4096
```

It does not describe a Terraform resource:

```yaml
# Anti-pattern
terraform:
  proxmox_vm_qemu:
    ...
```

## 3.2. Resource Model is independent from repository layout

The Resource Model is a contract.

It must not depend on whether users store resources in:

- one YAML file,
- many YAML files,
- generated YAML,
- another configuration frontend in the future.

The compiler consumes resource documents and produces one normalized internal model.

## 3.3. Core does not know execution engines

Core should never contain logic such as:

```python
if engine == "terraform":
    ...
elif engine == "ansible":
    ...
```

Core understands:

- resources,
- lifecycle phases,
- dependencies,
- capabilities,
- providers,
- provider bindings,
- normalized results.

How a provider performs an operation is a provider concern.

## 3.4. Platform and execution engine are different concepts

Examples:

**Execution engines**

- Terraform/OpenTofu
- Ansible
- Pulumi
- shell/process
- native API client

**Platforms**

- Proxmox VE
- VMware
- Hyper-V
- RouterOS
- SwOS
- Linux
- Windows
- TrueNAS

A possible driver name may combine the two:

```text
terraform.proxmox
ansible.routeros
native.proxmox
```

but the Resource Model must not treat those strings as resource types.

## 3.5. Portable spec plus platform extensions

The portable part contains common semantics.

Platform-specific functionality belongs under extensions:

```yaml
spec:
  cpu:
    cores: 4

  memory:
    mib: 4096

extensions:
  proxmox:
    qemu_agent: true
    balloon_mib: 2048
```

Extensions identify a **platform**, not an execution engine.

Correct:

```yaml
extensions:
  proxmox:
```

Avoid:

```yaml
extensions:
  terraform.proxmox:
```

This allows both `terraform.proxmox` and a future `native.proxmox` driver to consume the same platform extension.

---

# 4. API versioning

Resource Model versioning is separate from program versioning.

Example:

```text
CLI version:             0.1.0
Resource Model version:  iac/v0alpha1
Provider protocol:       iac-provider/v0alpha1
```

Each resource begins with:

```yaml
api_version: iac/v0alpha1
```

Expected evolution:

```text
iac/v0alpha1
iac/v0alpha2
iac/v0beta1
iac/v1
```

The compiler must reject unknown API versions rather than silently interpreting them.

---

# 5. Common resource envelope

Every resource uses the same top-level structure:

```yaml
api_version: iac/v0alpha1
kind: VirtualMachine

metadata:
  name: docker01

spec:
  ...

lifecycle:
  ...

depends_on:
  ...

extensions:
  ...
```

Required:

- `api_version`
- `kind`
- `metadata.name`
- `spec` where required by the resource kind

Optional:

- `metadata.description`
- `metadata.labels`
- `metadata.annotations`
- `lifecycle`
- `depends_on`
- `extensions`

---

# 6. Resource identity and references

The canonical logical identifier is:

```text
Kind/name
```

Examples:

```text
Network/servers
Hypervisor/pve01
Image/debian13
VirtualMachine/docker01
Provider/proxmox-main
Stage/workloads
```

A name does not have to be globally unique across all kinds.

References use the canonical form:

```yaml
placement:
  target: Hypervisor/pve01
```

or:

```yaml
depends_on:
  - Service/dns01
```

The compiler resolves all references before provider resolution.

Missing or ambiguous references are validation errors.

---

# 7. Metadata

Example:

```yaml
metadata:
  name: docker01
  description: Docker application host

  labels:
    site: home
    environment: production
    os_family: linux
    role: docker

  annotations:
    owner: jakub
```

## Labels

Labels are machine-readable selectors and may participate in:

- provider binding,
- filtering,
- CLI selection,
- policies,
- reporting.

Labels should be short scalar values.

## Annotations

Annotations contain informational metadata that should not normally influence provider resolution.

---

# 8. Stages

Stages provide coarse orchestration boundaries.

A stage is itself a resource:

```yaml
api_version: iac/v0alpha1
kind: Stage

metadata:
  name: workloads

spec:
  order: 40
```

Possible initial stages:

```text
10  network
20  platform
30  core
40  workloads
```

A resource references a stage through lifecycle:

```yaml
lifecycle:
  stage: workloads
```

A stage is **not** a replacement for a dependency graph.

Stages answer:

> Which broad infrastructure layer does this resource belong to?

Dependencies answer:

> What must exist before this specific resource can be processed?

---

# 9. Dependencies and DAG

Dependencies come from two sources.

## 9.1. Explicit dependencies

```yaml
depends_on:
  - Service/dns01
```

These are used when the relationship cannot be inferred from the spec.

## 9.2. Implicit dependencies from references

Example:

```yaml
spec:
  placement:
    target: Hypervisor/pve01

  interfaces:
    - network: Network/servers
```

The compiler automatically derives:

```text
VirtualMachine/docker01
    depends on Hypervisor/pve01
    depends on Network/servers
```

Users should not repeat those dependencies manually.

The compiler must:

- construct a directed acyclic graph,
- detect cycles,
- report a readable dependency path on failure,
- topologically order operations,
- respect stage ordering in addition to resource dependencies.

---

# 10. Lifecycle

Resource lifecycle is divided into phases.

For v0.1:

```text
observe
provision
configure
```

## `observe`

Reads actual state from an external system.

## `provision`

Creates, changes or removes the infrastructure resource itself.

## `configure`

Configures the resource after provisioning.

Example managed VM:

```yaml
lifecycle:
  stage: workloads
  desired_state: present

  phases:
    observe: managed
    provision: managed
    configure: managed

  prevent_destroy: true
```

Example physical hypervisor:

```yaml
lifecycle:
  stage: platform
  desired_state: present

  phases:
    observe: managed
    provision: external
    configure: external

  prevent_destroy: true
```

Initial phase ownership values:

```text
managed
external
disabled
```

Meaning:

- `managed` — the orchestrator must resolve and execute a provider,
- `external` — the resource or phase exists outside the tool's ownership,
- `disabled` — the phase is intentionally not applicable.

`desired_state` initially supports:

```text
present
absent
```

Destructive behavior must respect `prevent_destroy`.

---

# 11. Capabilities

A capability represents an operation a provider driver can perform.

Examples:

```text
virtual_machine.observe
virtual_machine.provision
virtual_machine.configure

network.observe
network.provision

hypervisor.observe
hypervisor.configure

network_device.observe
network_device.configure
```

A resource lifecycle phase maps to a required capability.

Example:

```text
VirtualMachine/docker01
phase: provision

→ required capability:
virtual_machine.provision
```

Providers declare supported capabilities.

Validation must fail before execution when a managed phase has no compatible provider.

---

# 12. Provider architecture

Three concepts must remain separate.

## 12.1. Provider driver

A driver is an implementation.

Examples:

```text
terraform.proxmox
native.proxmox
ansible.linux
ansible.routeros
```

## 12.2. Provider instance

A `Provider` resource configures one driver for one environment.

Example:

```yaml
api_version: iac/v0alpha1
kind: Provider

metadata:
  name: proxmox-main

spec:
  driver: terraform.proxmox

  config:
    endpoint: https://pve01.techtradeexpress.com:8006

    credentials:
      token:
        secret_ref: proxmox/main
```

Multiple provider instances can use the same driver:

```text
Provider/proxmox-home → terraform.proxmox
Provider/proxmox-lab  → terraform.proxmox
```

## 12.3. Provider binding

Resources should not normally embed a concrete provider.

Instead, a binding maps a capability and selector to a provider.

```yaml
api_version: iac/v0alpha1
kind: ProviderBinding

metadata:
  name: home-vm-provisioning

spec:
  capability: virtual_machine.provision

  match:
    kind: VirtualMachine

    labels:
      site: home

  provider: Provider/proxmox-main

  priority: 100
```

Resolution:

```text
VirtualMachine/docker01
        │
        │ requires
        ▼
virtual_machine.provision
        │
        ▼
ProviderBinding
        │
        ▼
Provider/proxmox-main
        │
        ▼
terraform.proxmox
```

If no provider matches:

```text
UNRESOLVED PROVIDER
```

If multiple providers match at equal effective priority:

```text
AMBIGUOUS PROVIDER
```

The resolver must never pick an arbitrary provider.

---

# 13. Provider interface

The logical provider interface for v0.1 should support:

```text
validate
observe
plan
apply
destroy
```

Not every provider has to implement every operation.

A provider manifest should advertise support explicitly.

Example:

```text
terraform.proxmox

validate  yes
observe   yes
plan      yes
apply     yes
destroy   yes
```

Possible Ansible adapter:

```text
ansible.linux

validate  yes
observe   partial
plan      partial
apply     yes
destroy   no
```

The core must not imply equivalent guarantees where they do not exist.

For example, Ansible check mode must not be presented as semantically identical to a Terraform plan.

---

# 14. Provider result contract

All providers return a normalized result independent of their execution engine.

Example:

```json
{
  "resource": "VirtualMachine/docker01",
  "phase": "provision",
  "provider": "Provider/proxmox-main",
  "changed": true,
  "external_id": "101",
  "outputs": {
    "ipv4": "192.168.10.20"
  },
  "diagnostics": []
}
```

The core should understand this structure without knowing whether the provider used:

- Terraform,
- Ansible,
- a REST API,
- PowerShell,
- SSH,
- another binary.

---

# 15. Provider protocol

The public provider boundary should be **language-neutral**.

Proposed approach for v0.1:

```text
core process
    │
    │ versioned JSON messages
    │ stdin/stdout
    ▼
provider process
```

Protocol namespace:

```text
iac-provider/v0alpha1
```

Reasons:

- a Python core does not force providers to be written in Python,
- Rust/Go/Python providers can coexist,
- provider crashes are isolated from the core,
- the protocol can remain stable even if the core implementation language changes,
- no Rust or Python in-process ABI becomes part of the public contract.

Built-in providers may initially run in-process for development convenience, but they should implement the same request/response semantics.

A future implementation may use JSON Lines or JSON-RPC-like envelopes. The exact transport is intentionally not frozen in Resource Model v0.1.

---

# 16. Portable specs and extensions

## Example VirtualMachine

```yaml
api_version: iac/v0alpha1
kind: VirtualMachine

metadata:
  name: docker01

  labels:
    site: home
    os_family: linux

spec:
  placement:
    target: Hypervisor/pve01

  cpu:
    cores: 4

  memory:
    mib: 4096

  disks:
    - name: root
      size_gib: 32

  interfaces:
    - name: primary
      network: Network/servers

      ipv4:
        mode: static
        address: 192.168.10.20/24

  image:
    ref: Image/debian13

lifecycle:
  stage: workloads
  desired_state: present

  phases:
    observe: managed
    provision: managed
    configure: managed

  prevent_destroy: true

extensions:
  proxmox:
    qemu_agent: true
    balloon_mib: 2048
```

The portable spec contains concepts expected to map across multiple virtualization platforms.

The extension contains platform-specific features.

Provider migration should therefore expose which parts are portable and which require platform-specific handling.

---

# 17. Initial resource kinds

The first Resource Model should remain intentionally small.

## Core/meta resources

- `Project`
- `Stage`
- `Provider`
- `ProviderBinding`

## Infrastructure resources

- `Network`
- `Hypervisor`
- `Image`
- `VirtualMachine`

This set is enough to test:

- references,
- graph construction,
- lifecycle,
- provider resolution,
- portable specs,
- extensions,
- Terraform integration,
- Ansible integration.

Possible later resource kinds:

- `BareMetalHost`
- `NetworkDevice`
- `Switch`
- `Router`
- `DhcpScope`
- `DnsZone`
- `DnsRecord`
- `FirewallPolicy`
- `StoragePool`
- `Nas`
- `BackupTarget`
- `BackupPolicy`
- `Service`
- `Ups`
- `Pdu`

They should not be added before a real use case requires them.

---

# 18. `Network` v0.1

Keep the first network model deliberately small:

```yaml
api_version: iac/v0alpha1
kind: Network

metadata:
  name: servers

spec:
  vlan_id: 10

  ipv4:
    cidr: 192.168.10.0/24
    gateway: 192.168.10.1
```

Do not turn `Network` into a monolith containing:

- DHCP,
- DNS,
- NAT,
- firewall rules,
- physical switch ports.

Those should become separate resources when needed.

---

# 19. `Hypervisor` v0.1

Example existing physical hypervisor:

```yaml
api_version: iac/v0alpha1
kind: Hypervisor

metadata:
  name: pve01

  labels:
    site: home
    platform: proxmox

spec:
  management:
    address: 192.168.10.10

lifecycle:
  stage: platform
  desired_state: present

  phases:
    observe: managed
    provision: external
    configure: external

  prevent_destroy: true
```

The portable `Hypervisor` model should not require Proxmox-specific attributes in `spec`.

---

# 20. `Image` v0.1

```yaml
api_version: iac/v0alpha1
kind: Image

metadata:
  name: debian13

spec:
  os:
    family: linux
    distribution: debian
    version: "13"
    architecture: amd64
```

A provider may map the logical image to:

```text
Proxmox template VMID 9000
VMware template
Hyper-V VHDX
cloud image
```

without changing references from virtual machines.

---

# 21. Secrets

Secret values must never be stored directly in the resource configuration.

Only references are allowed:

```yaml
credentials:
  token:
    secret_ref: proxmox/main
```

The actual secret backend is a separate concern.

Potential future implementations:

- environment variables,
- SOPS,
- HashiCorp Vault,
- 1Password,
- Bitwarden.

MVP recommendation:

```text
secret_ref → environment variable resolver
```

No custom secret-management system should be built.

---

# 22. State and execution journal

The project must not duplicate Terraform state.

Terraform remains the owner of `terraform.tfstate`.

The orchestrator may maintain small execution metadata:

```json
{
  "VirtualMachine/docker01": {
    "provision": {
      "provider": "Provider/proxmox-main",
      "external_id": "101",
      "last_apply": "2026-09-23T20:00:00Z"
    }
  }
}
```

This is an:

```text
execution journal
+
cross-provider output store
```

not an authoritative infrastructure state engine.

The journal may contain:

- provider used,
- lifecycle phase,
- start/end timestamps,
- result status,
- external identifier,
- normalized outputs,
- configuration hash,
- diagnostics summary.

---

# 23. Compiler pipeline

Configuration processing should follow one deterministic pipeline:

```text
YAML source documents
        │
        ▼
parse
        │
        ▼
API/schema validation
        │
        ▼
resource normalization
        │
        ▼
reference resolution
        │
        ▼
semantic validation
        │
        ▼
implicit dependency extraction
        │
        ▼
provider binding resolution
        │
        ▼
DAG validation
        │
        ▼
normalized IR
```

Semantic validation should detect at least:

- duplicate `Kind/name`,
- unknown references,
- unknown stages,
- unresolved providers,
- ambiguous providers,
- unsupported capabilities,
- dependency cycles,
- duplicate IP addresses where determinable,
- IP outside referenced subnet,
- illegal lifecycle combinations,
- destructive action blocked by `prevent_destroy`.

Execution begins only after compilation succeeds.

---

# 24. Repository layout

The Resource Model does not mandate a layout, but the reference project layout may be:

```text
config/
├── project.yml
├── stages.yml
│
├── providers/
│   ├── proxmox.yml
│   └── ansible.yml
│
├── bindings/
│   └── defaults.yml
│
└── resources/
    ├── networks.yml
    ├── hypervisors.yml
    ├── images.yml
    └── virtual-machines.yml
```

A file may contain multiple YAML documents separated by:

```yaml
---
```

The compiler treats the directory tree as source organization only. Resource identity does not depend on file path.

---

# 25. CLI direction

The intended user experience is comparable to a project console such as Laravel Artisan.

Possible commands:

```bash
diatonic validate
diatonic doctor
diatonic graph
diatonic explain VirtualMachine/docker01

diatonic plan
diatonic apply

diatonic plan --stage workloads
diatonic apply --stage network

diatonic plan VirtualMachine/docker01
diatonic apply VirtualMachine/docker01

diatonic provider list
diatonic provider doctor

diatonic make:vm docker01
diatonic make:network servers
```

Only a small subset should be included in the MVP:

```text
diatonic validate
diatonic graph
diatonic explain
diatonic plan
diatonic apply
diatonic doctor
```

Scaffolding commands can follow after the contract stabilizes.

---

# 26. Atmos as benchmark

Atmos should remain a permanent comparison point.

Features that are **not** sufficient differentiation:

- YAML-based configuration,
- Terraform orchestration,
- Ansible orchestration,
- workflows,
- custom CLI commands,
- validation,
- scaffolding,
- dependency handling alone.

The proposed differentiation is:

```text
Atmos-like component model:

configuration
    ↓
Terraform/Ansible/etc. component
    ↓
execution engine
    ↓
platform
```

versus:

```text
Proposed model:

logical resource
    ↓
desired state
    ↓
required capability
    ↓
provider binding
    ↓
provider instance
    ↓
driver
    ↓
execution engine/platform
```

Every major feature proposal should answer:

> Why should this exist here instead of being implemented as an Atmos component/workflow?

If the answer is only convenience, the feature probably does not belong in the core.

---

# 27. Technology decision: Python vs Rust

## 27.1. What matters for this project

Raw execution speed is not the primary requirement.

Most expensive operations will occur outside the core process:

- Terraform/OpenTofu,
- Ansible,
- provider APIs,
- network calls,
- filesystem operations,
- external binaries.

The hard part of the MVP is expected to be:

- evolving the Resource Model,
- implementing validation,
- writing useful diagnostics,
- provider resolution,
- graph semantics,
- testing edge cases,
- iterating on the provider protocol.

This strongly affects the language choice.

---

## 27.2. Python

### Advantages

**Fast model iteration**

Python enables rapid changes to configuration models while the contract is still `v0alpha1`.

**Pydantic**

Pydantic 2 provides typed models, validation, serialization, custom validators and JSON Schema generation from Python type definitions.

This maps directly onto:

```text
YAML
→ parsed data
→ typed Resource Model
→ JSON Schema
→ normalized IR
```

**Plugin ecosystem**

Python packaging has a standardized entry-point mechanism for discovering separately installed plugins.

Even if the public long-term provider protocol is process-based, entry points are useful for:

- built-in extensions,
- development providers,
- command extensions,
- local tooling.

**CLI ergonomics**

Typer provides a concise type-hint-oriented CLI model and integrates well with Rich-style output.

**Infrastructure ecosystem**

Python already fits naturally beside:

- Ansible,
- YAML/JSON tooling,
- REST APIs,
- test tooling,
- subprocess orchestration.

**Testing velocity**

`pytest` plus property-based testing with Hypothesis is well suited to testing a large combination space of resource documents and resolver behavior.

### Disadvantages

**Distribution**

Python does not naturally produce one dependency-free native executable in the same way as Rust.

This can be mitigated with:

```text
uv tool install
pipx
wheels
containers
optional bundled executable later
```

**Runtime type safety**

Pydantic and static checking provide strong application-level validation, but Rust still provides stronger compile-time guarantees.

**Startup/runtime overhead**

Higher than Rust, though unlikely to matter for an orchestration CLI dominated by external operations.

---

## 27.3. Rust

### Advantages

**Strong compile-time model**

Rust enums and structs are excellent for representing a strict Resource Model.

Serde provides mature serialization/deserialization.

Schemars can generate JSON Schema from Rust types.

**CLI quality**

Clap provides a mature, strongly typed CLI implementation.

**Distribution**

A compiled CLI is operationally attractive:

```text
download binary
chmod +x
run
```

This is especially appealing for homelabs, CI runners and administrator workstations.

**Runtime robustness**

Memory safety and explicit error handling are strong properties for a long-lived infrastructure tool.

**Performance**

Parsing, graph processing and large repositories would be extremely fast.

### Disadvantages

**Slower contract iteration**

During `v0alpha1`, a large percentage of work will consist of repeatedly changing:

- enums,
- schemas,
- validators,
- provider contracts,
- diagnostics.

Rust makes those changes safer but usually more expensive to implement.

**Plugin architecture**

An in-process third-party plugin ABI is significantly more complicated than Python package discovery.

A process-based JSON protocol solves most of this problem, but once that boundary exists Rust loses one of its strongest arguments for the MVP: the core no longer needs to share types directly with providers.

**Contributor barrier**

For an infrastructure-focused open-source project, requiring Rust knowledge may reduce the pool of people able to contribute providers or core features compared with Python.

**More implementation work for UX**

High-quality configuration diagnostics, dynamic extension loading and experimentation generally require more plumbing.

---

# 28. Recommendation

## Use Python for the MVP and the entire v0.x line

Recommended baseline:

```text
Python >= 3.12
```

The choice is based on development economics, not runtime performance.

The main engineering risk is getting the abstraction wrong. Python lets the project test and change that abstraction faster.

A Rust implementation would optimize properties that are not yet the primary risk.

The project should **not** plan a Rust rewrite by default.

Instead:

> Reconsider the core language before `v1` only if real evidence shows that Python causes a distribution, performance, reliability or maintainability problem.

---

# 29. Recommended Python stack

## Core model and validation

```text
Pydantic 2.x
```

Use Pydantic models as the canonical in-code representation of Resource Model types.

Benefits:

- parsing,
- validation,
- custom semantic validators,
- JSON Schema generation,
- predictable serialization.

## YAML

Initial recommendation:

```text
PyYAML
```

The tool should not rewrite user configuration in the MVP, so round-trip comment preservation is not yet necessary.

If source-preserving edits or formatter functionality becomes important later, evaluate `ruamel.yaml`.

## CLI

```text
Typer
Rich
```

Typer for command structure and arguments.

Rich for:

- tables,
- diagnostics,
- plans,
- trees,
- dependency graph text output,
- colored diffs/status.

## Graph handling

Use the Python standard library first:

```text
graphlib.TopologicalSorter
```

Implement a small project-specific graph abstraction around it.

Do not add NetworkX unless advanced graph algorithms actually become necessary.

## Provider execution

Use:

```text
asyncio.create_subprocess_exec
```

for external provider processes and execution engines.

Avoid shell interpolation.

Arguments should be passed as arrays.

## Provider discovery

Two layers are recommended.

### Internal/development plugins

Python package entry points:

```text
diatonic.providers
```

### Public stable provider boundary

Versioned process protocol:

```text
iac-provider/v0alpha1
```

using JSON over stdin/stdout.

This means a provider may be implemented in:

- Python,
- Rust,
- Go,
- another language.

## Project/package management

Recommended:

```text
pyproject.toml
uv
```

Distribution options:

```text
uv tool install <package>
pipx install <package>
pip install <package>
```

## Tests and quality

Recommended:

```text
pytest
hypothesis
ruff
mypy or pyright
```

Hypothesis is particularly valuable for:

- resource parser invariants,
- provider resolver ambiguity,
- DAG/cycle tests,
- reference validation,
- extension handling.

---

# 30. Proposed Python source layout

```text
src/
└── diatonic/
    ├── cli/
    │   ├── app.py
    │   ├── validate.py
    │   ├── graph.py
    │   ├── explain.py
    │   ├── plan.py
    │   └── apply.py
    │
    ├── model/
    │   ├── base.py
    │   ├── metadata.py
    │   ├── lifecycle.py
    │   ├── project.py
    │   ├── stage.py
    │   ├── provider.py
    │   ├── binding.py
    │   ├── network.py
    │   ├── hypervisor.py
    │   ├── image.py
    │   └── virtual_machine.py
    │
    ├── compiler/
    │   ├── loader.py
    │   ├── normalize.py
    │   ├── references.py
    │   ├── validation.py
    │   └── compiler.py
    │
    ├── graph/
    │   ├── dependency.py
    │   └── planner.py
    │
    ├── providers/
    │   ├── registry.py
    │   ├── resolver.py
    │   ├── binding.py
    │   └── executor.py
    │
    ├── protocol/
    │   ├── messages.py
    │   ├── client.py
    │   └── version.py
    │
    ├── journal/
    │   ├── model.py
    │   └── store.py
    │
    └── diagnostics/
        ├── model.py
        └── render.py
```

The package name and CLI executable are established in ADR-0001 as `diatonic-orchestrator` and `diatonic`.

---

# 31. MVP execution strategy

Do not begin by implementing real Proxmox logic.

Recommended milestones:

## Milestone 1 — Resource compiler

Implement:

- YAML loading,
- `api_version`,
- common envelope,
- initial resource models,
- canonical identities,
- reference resolution,
- validation,
- normalized IR.

No provider execution.

## Milestone 2 — DAG and resolver

Implement:

- implicit dependencies,
- explicit dependencies,
- stages,
- cycle detection,
- `Provider`,
- `ProviderBinding`,
- capabilities,
- provider resolution,
- `iac graph`,
- `iac explain`.

Still no destructive infrastructure actions.

## Milestone 3 — Fake provider protocol

Create a provider such as:

```text
mock.virtualization
```

that can:

```text
observe
plan
apply
destroy
```

without touching real infrastructure.

Use it to stabilize the provider protocol.

## Milestone 4 — First real provisioning adapter

Implement:

```text
terraform.proxmox
```

Only enough functionality to prove:

```text
VirtualMachine
→ capability
→ binding
→ provider
→ Terraform
→ normalized result
```

## Milestone 5 — Configuration adapter

Implement:

```text
ansible.linux
```

Prove sequential lifecycle execution:

```text
VirtualMachine/docker01
    provision
        ↓
    configure
```

## Milestone 6 — Network proof

Add RouterOS only after the generic model has survived virtualization and OS configuration.

This is the first strong test that the architecture is not accidentally virtualization-specific.

---

# 32. Architectural acceptance tests

The MVP should be considered successful only if these tests pass.

## Test A — execution engine replacement

The resource:

```text
VirtualMachine/docker01
```

must remain unchanged when replacing:

```text
terraform.proxmox
```

with:

```text
native.proxmox
```

provided both expose the required capabilities.

## Test B — platform replacement

Most of the portable resource should remain valid when replacing Proxmox with another virtualization platform.

Platform extensions may require change.

The tool must make that difference explicit.

## Test C — mixed-engine DAG

A graph must be able to include operations such as:

```text
Network/servers
    ↓
RouterOS configuration via Ansible
    ↓
VirtualMachine/docker01 via Terraform/Proxmox
    ↓
Linux configuration via Ansible
```

without core logic containing special cases for those products.

## Test D — provider ambiguity

When two bindings match equally, validation must fail deterministically.

## Test E — external resource

The model must represent infrastructure that exists but is not provisioned by the tool.

Example:

```text
Hypervisor/pve01

observe: managed
provision: external
configure: external
```

## Test F — no hidden state ownership

Removing the execution journal must not make Terraform lose ownership or knowledge of its resources.

The orchestrator journal is metadata, not infrastructure state.

---

# 33. Open design questions

These should remain unresolved until implementation pressure provides evidence.

1. Should `configure` be a generic lifecycle phase or eventually become capability-specific actions?
2. Should ProviderBindings support complex label expressions in v0.1, or only exact matches?
3. How should cross-provider outputs be referenced declaratively?
4. Should `extensions` schemas be registered dynamically by provider/platform plugins?
5. Should external provider processes use JSON Lines, JSON-RPC 2.0, or a custom minimal envelope?
6. How should provider process discovery work across operating systems?
7. Should execution journal storage initially be JSON files or SQLite?
8. How much of `plan` can be normalized across Terraform, Ansible and native API providers without suggesting false equivalence?
9. Should `Project` hold defaults, or should defaults be implemented through separate policy/default resources?
10. How should resource deletion be represented safely when a resource disappears from configuration?
11. How should imports/adoption of existing infrastructure work?
12. At what point should policy-as-code be introduced?

These questions should not block Milestone 1.

---

# 34. Decision summary

For the MVP:

```text
Resource Model:       iac/v0alpha1
License:              MIT
Core language:         Python
Minimum Python:        3.12
Model validation:      Pydantic 2.x
Configuration:         YAML
CLI:                   Typer + Rich
Graph:                 stdlib graphlib + project abstraction
Provider boundary:     versioned JSON process protocol
Provider discovery:    Python entry points + external executable protocol
Execution:             subprocess/asyncio
Package metadata:      pyproject.toml
Dev/package tooling:   uv
Testing:               pytest + Hypothesis
Benchmark:             Atmos
```

The architectural center is:

```text
Resource
   ↓
Desired State
   ↓
Lifecycle Phase
   ↓
Required Capability
   ↓
Provider Binding
   ↓
Provider Instance
   ↓
Driver
   ↓
Execution Engine / Platform
```

The primary success criterion is not CLI polish or the number of supported vendors.

It is:

> **A logical resource must survive replacement of its execution backend without requiring the Resource Model itself to become backend-specific.**

If that property cannot be preserved for the first few real integrations, the abstraction should be reconsidered before the project grows.

---

# 35. Technical references used for the technology decision

- Pydantic documentation: typed validation, serialization and JSON Schema generation.
- Python Packaging User Guide: standardized entry points and plugin discovery.
- Python Packaging User Guide: packaging command-line tools and `console_scripts`.
- uv documentation: isolated execution and installation of Python CLI tools.
- Rust Serde documentation: serialization/deserialization framework.
- Rust `clap` documentation: strongly typed CLI parser.
- Schemars documentation: JSON Schema generation from Rust types.
- Rust Reference: library/linkage models relevant to dynamic extension design.

