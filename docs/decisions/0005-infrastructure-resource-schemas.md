# M1.4: Portable infrastructure schema decisions

The normative contract is `docs/resource-model/v0alpha1.md`, especially §§16,
18–20. Its examples leave some requiredness and value domains unspecified. This
note records narrow initial validation choices for review; neither API namespace,
the shared envelope, lifecycle defaults nor YAML loading policy changes.

- New Network, Hypervisor and Image resources require `spec` and all demonstrated
  spec fields. No implicit gateway, OS attribute or management address is invented.
  Network currently describes a tagged IPv4 network: `vlan_id` is a strict integer
  in 1–4094, excluding reserved VLAN identifiers 0 and 4095. Untagged networks and
  optional gateways are not yet defined; these choices need contract clarification
  if those use cases are introduced.
- VM CPU/memory remain required. Placement and image are optional (`None` when
  absent), and disk/interface lists default to independent empty lists. Explicit
  null is accepted for optional object sections, but rejected for lists. Existing
  M1.2 minimal VM documents remain valid. A supplied placement or image object
  requires its reference; each disk requires name and size; each interface requires
  name and network. Interface IPv4 is optional with no implicit configuration.
- Disk size is a strict positive integer in whole GiB. Fractional sizes are not
  defined by the examples and remain unsupported. Disk/interface names reuse the
  existing nonempty, no-whitespace, no-slash name syntax. Local duplicate names
  and cross-resource constraints are left to later semantic validation.
- A supplied interface IPv4 object requires `mode: static` and an address. Static
  is the only documented mode; no DHCP, disabled mode or implied addressing policy
  is introduced. Additional modes require a contract decision.
- IP fields are strict strings validated with stdlib `ipaddress`, retained exactly
  as declared for serialization. IPv4 gateways accept bare IPv4 literals. Network
  CIDRs require an explicit decimal prefix length (0–32), IPv4 syntax and a network
  address without host bits; host bits are rejected rather than silently masked.
  Interface IPv4 addresses also require a prefix length and allow host bits.
  Bare addresses, dotted netmasks and IPv6 in IPv4 fields are rejected.
- Management addresses accept bare IPv4 or unscoped IPv6 literals. Hostnames,
  URLs, ports, scoped IPv6 and CIDR notation are outside this initial IP-only
  interpretation of the example. Hostname support remains an explicit future
  contract question; no DNS lookups or reachability checks occur.
- Image OS attributes are nonempty strict strings, including `version`. No
  operating-system, distribution, architecture or version allowlist is imposed.
  Numeric YAML versions must be quoted to preserve string type.
- Placement, interface network and image references reuse canonical `Kind/name`
  syntax, with exact expected kinds Hypervisor, Network and Image respectively.
  Validation never looks up existence. Generic `depends_on` keeps its existing
  syntax-only behavior. No address membership, collisions, identity index or
  lifecycle semantic checks occur at this schema stage.
- The explicit union now supports Stage, Network, Hypervisor, Image and VM only.
  Provider-specific values remain under `extensions.<platform>`; there are no
  provider or engine branches. The loader remains independent from schema parsing.

This supersedes the M1.2 note's temporary rejection of the newly implemented VM
sections. Examples under `examples/infrastructure/` demonstrate the extended
schemas with documentation IP addresses and no infrastructure execution.
