# M1.8: Network-scoped IPv4 semantic validation

`diatonic.compiler.semantics.validate_ipv4_semantics(index: ResourceIndex) -> None`
is a pure library step after the existing resolver and before normalization. It
uses stdlib `ipaddress` on already schema-validated and reference-resolved data;
the index, resource values, loader, schemas and IR remain unchanged. The CLI calls
this step and retains success 0, expected validation failure 1 and usage error 2.
Neither `iac/v0alpha1` nor `iac-provider/v0alpha1` changes.

## Rules and boundaries

1. A Network gateway must belong to its declared IPv4 CIDR.
2. Each static VM interface host (`IPv4Interface(address).ip`) must belong to the
   exact logical Network it references. Its own prefix length need not match the
   Network prefix; the contract does not require that restriction.
3. Static host assignments must be unique within one logical `Network/name`,
   including different interfaces of one VM and different VMs/files. Comparison
   uses numeric host addresses, so differing prefixes do not hide duplicates.
4. A static host cannot equal its referenced Network's declared gateway.

Absent/null optional IPv4 blocks and VMs without interfaces are skipped. No
defaults or addresses are invented. Membership includes CIDR boundaries as
defined by `ipaddress`, including /31 and /32. No arbitrary network/broadcast,
reserved-address or usable-host policy is added. A /32 gateway can pass membership,
but a VM using that address still conflicts with the declared gateway.

Identical addresses in different logical Network resources are permitted, even
with identical or overlapping CIDRs or VLAN IDs. This layer does not know L2/L3
connectivity, VRFs, site isolation or topology. Hypervisor management addresses
are not included in static VM duplicate detection. Lifecycle ownership and desired
state do not suppress checks on declared addresses; no execution policy is inferred.

## Determinism and diagnostics

Validation fails fast. First check Networks in sorted, case-sensitive identity
order. Then check VMs in sorted identity order and interfaces in declared list
order. For an interface, membership precedes gateway reservation, which precedes
duplicate detection. The first assignment in that canonical traversal is the
related declaration for a duplicate; input/file order never chooses the winner.
Only the first issue is returned, without mutation or partially normalized IR.

`SemanticValidationError.diagnostic` is a frozen `IPv4Diagnostic` with stable code:

- `gateway_outside_subnet` — field `spec.ipv4.gateway` on the Network.
- `address_outside_subnet` — field `spec.interfaces[i].ipv4.address` on the VM.
- `gateway_address_conflict` — same VM field; related Network gateway declaration.
- `duplicate_static_ipv4` — same VM field; related first VM/interface assignment.

Diagnostics retain owner identity, field path, source path/document index and
available document-root coordinates, logical Network identity, CIDR and declared
address text. Conflicts also retain the other owner, field path, address and root
source via `IPv4Declaration`. Numeric host context is included in messages while
the original strings remain unmodified. CLI rendering uses literal Rich Text,
prints both conflicting origins and never invents exact field coordinates.

Callers must provide a successful, unmodified M1.5 index. Missing or wrongly typed
references remain the resolver/schema layer's errors; this step does not rebuild
or repair indexes or redo syntax validation. It is opt-in for direct library
callers: the existing resolver and normalizer keep their individual contracts.
The full CLI pipeline always invokes it before normalization.

No DAG/cycles, scheduling, providers, IPAM, DHCP/allocation, global subnet-overlap
checks, state, plan/apply or lifecycle/destruction policy is implemented. Those
semantics require explicit later designs rather than inferred restrictions here.
