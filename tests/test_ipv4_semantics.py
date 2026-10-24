"""Network-scoped address semantics and CLI pipeline integration."""

from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
import yaml
from typer.testing import CliRunner

import diatonic.cli as cli
from diatonic.compiler.loader import LoadedDocument, load_yaml_files
from diatonic.compiler.normalize import normalize_resources
from diatonic.compiler.references import ResourceResolutionError, resolve_resources
from diatonic.compiler.semantics import SemanticValidationError, validate_ipv4_semantics

ROOT = Path(__file__).parents[1]
runner = CliRunner()


def network(name="net", cidr="192.0.2.0/24", gateway="192.0.2.1") -> dict[str, Any]:
    return {
        "api_version": "iac/v0alpha1",
        "kind": "Network",
        "metadata": {"name": name},
        "spec": {"vlan_id": 10, "ipv4": {"cidr": cidr, "gateway": gateway}},
    }


def interface(address: str | None = "192.0.2.20/24", net="net", name="primary"):
    result = {"name": name, "network": f"Network/{net}"}
    if address is not None:
        result["ipv4"] = {"mode": "static", "address": address}
    return result


def vm(name="app", interfaces=None) -> dict[str, Any]:
    spec = {"cpu": {"cores": 1}, "memory": {"mib": 512}}
    if interfaces is not None:
        spec["interfaces"] = interfaces
    return {
        "api_version": "iac/v0alpha1",
        "kind": "VirtualMachine",
        "metadata": {"name": name},
        "spec": spec,
    }


def documents(resources: list[dict[str, Any]]) -> list[LoadedDocument]:
    return [
        LoadedDocument(
            data, Path(f"{data['kind']}-{data['metadata']['name']}.yml"), 1, 3, 2
        )
        for data in resources
    ]


def failure(resources: list[dict[str, Any]]):
    index = resolve_resources(documents(resources))
    before = {
        key: entry.resource.model_dump() for key, entry in index.resources.items()
    }
    with pytest.raises(SemanticValidationError) as exc:
        validate_ipv4_semantics(index)
    assert {
        key: entry.resource.model_dump() for key, entry in index.resources.items()
    } == before
    return exc.value.diagnostic


@pytest.mark.parametrize(
    ("cidr", "gateway"),
    [
        ("192.0.2.0/24", "192.0.2.1"),
        ("192.0.2.0/24", "192.0.2.0"),
        ("192.0.2.0/24", "192.0.2.255"),
        ("192.0.2.0/31", "192.0.2.0"),
        ("192.0.2.0/31", "192.0.2.1"),
        ("192.0.2.7/32", "192.0.2.7"),
        ("0.0.0.0/0", "203.0.113.1"),
    ],
)
def test_gateway_membership_accepts_boundaries(cidr: str, gateway: str) -> None:
    assert (
        validate_ipv4_semantics(
            resolve_resources(documents([network(cidr=cidr, gateway=gateway)]))
        )
        is None
    )


@pytest.mark.parametrize(
    ("cidr", "gateway"),
    [
        ("192.0.2.0/24", "198.51.100.1"),
        ("192.0.2.0/31", "192.0.2.2"),
        ("192.0.2.7/32", "192.0.2.8"),
    ],
)
def test_gateway_outside_subnet_has_network_context(cidr: str, gateway: str) -> None:
    diagnostic = failure([network(cidr=cidr, gateway=gateway)])
    assert diagnostic.code == "gateway_outside_subnet"
    assert diagnostic.resource_identity == "Network/net"
    assert diagnostic.network_identity == "Network/net"
    assert diagnostic.cidr == cidr
    assert diagnostic.address == gateway
    assert diagnostic.field_path == ("spec", "ipv4", "gateway")
    assert (diagnostic.source.line, diagnostic.source.column) == (3, 2)


@pytest.mark.parametrize(
    "address",
    [
        "192.0.2.20/24",
        "192.0.2.20/16",
        "192.0.2.20/32",
        "192.0.2.0/24",
        "192.0.2.255/24",
    ],
)
def test_static_membership_uses_host_only_without_extra_reserved_address_policy(
    address,
):
    index = resolve_resources(
        documents([vm(interfaces=[interface(address)]), network()])
    )
    validate_ipv4_semantics(index)
    assert (
        index.resources["VirtualMachine/app"].resource.spec.interfaces[0].ipv4.address
        == address
    )


def test_slash31_vm_other_endpoint_is_allowed() -> None:
    index = resolve_resources(
        documents(
            [
                network(cidr="192.0.2.0/31", gateway="192.0.2.0"),
                vm(interfaces=[interface("192.0.2.1/32")]),
            ]
        )
    )
    validate_ipv4_semantics(index)


def test_static_host_outside_referenced_subnet() -> None:
    diagnostic = failure([network(), vm(interfaces=[interface("198.51.100.20/16")])])
    assert diagnostic.code == "address_outside_subnet"
    assert diagnostic.resource_identity == "VirtualMachine/app"
    assert diagnostic.field_path == ("spec", "interfaces", 0, "ipv4", "address")
    assert diagnostic.network_identity == "Network/net"
    assert diagnostic.cidr == "192.0.2.0/24"
    assert diagnostic.address == "198.51.100.20/16"


@pytest.mark.parametrize("cidr", ["192.0.2.0/24", "192.0.2.1/32"])
def test_static_gateway_conflict_including_slash32(cidr: str) -> None:
    diagnostic = failure(
        [network(cidr=cidr), vm(interfaces=[interface("192.0.2.1/32")])]
    )
    assert diagnostic.code == "gateway_address_conflict"
    assert diagnostic.related is not None
    assert diagnostic.related.resource_identity == "Network/net"
    assert diagnostic.related.field_path == ("spec", "ipv4", "gateway")
    assert diagnostic.related.address == "192.0.2.1"


@pytest.mark.parametrize("second_prefix", [24, 16, 32])
def test_duplicate_hosts_across_vms_report_both_origins(second_prefix: int) -> None:
    resources = [
        vm("z", [interface(f"192.0.2.20/{second_prefix}")]),
        network(),
        vm("a", [interface("192.0.2.20/24")]),
    ]
    diagnostic = failure(resources)
    assert diagnostic.code == "duplicate_static_ipv4"
    assert diagnostic.resource_identity == "VirtualMachine/z"
    assert diagnostic.source.source_path == Path("VirtualMachine-z.yml")
    assert diagnostic.related is not None
    assert diagnostic.related.resource_identity == "VirtualMachine/a"
    assert diagnostic.related.source.source_path == Path("VirtualMachine-a.yml")
    assert diagnostic.related.field_path == ("spec", "interfaces", 0, "ipv4", "address")
    assert diagnostic.related.address == "192.0.2.20/24"
    assert diagnostic == failure(list(reversed(resources)))


def test_duplicate_hosts_between_interfaces_of_one_vm() -> None:
    diagnostic = failure(
        [
            network(),
            vm(
                interfaces=[
                    interface(name="one"),
                    interface(None, name="two"),
                    interface("192.0.2.20/32", name="three"),
                ]
            ),
        ]
    )
    assert diagnostic.code == "duplicate_static_ipv4"
    assert diagnostic.field_path == ("spec", "interfaces", 2, "ipv4", "address")
    assert diagnostic.related is not None
    assert diagnostic.related.resource_identity == diagnostic.resource_identity
    assert diagnostic.related.source == diagnostic.source
    assert diagnostic.related.field_path == ("spec", "interfaces", 0, "ipv4", "address")


def test_same_address_on_different_logical_networks_is_not_a_collision() -> None:
    resources = [
        network("one"),
        network("two"),
        vm(
            interfaces=[
                interface(net="one", name="one"),
                interface(net="two", name="two"),
            ]
        ),
    ]
    validate_ipv4_semantics(resolve_resources(documents(resources)))


def test_exact_network_reference_is_used_for_membership() -> None:
    diagnostic = failure(
        [
            network("one"),
            network("two", "198.51.100.0/24", "198.51.100.1"),
            vm(interfaces=[interface(net="two")]),
        ]
    )
    assert diagnostic.code == "address_outside_subnet"
    assert diagnostic.network_identity == "Network/two"


def test_optional_ipv4_and_minimal_vm_compatibility() -> None:
    resource = vm("null", [interface(None)])
    resource["spec"]["interfaces"][0]["ipv4"] = None
    resources = [
        network(),
        vm("minimal"),
        vm("empty", []),
        resource,
        vm("omitted", [interface(None)]),
    ]
    validate_ipv4_semantics(resolve_resources(documents(resources)))
    validate_ipv4_semantics(resolve_resources([]))


def test_semantic_order_networks_first_then_canonical_vms_and_list_order() -> None:
    invalid_vm = vm("a", [interface("203.0.113.7/24")])
    invalid_net = network("z", gateway="203.0.113.1")
    resources = [invalid_vm, network(), invalid_net]
    assert failure(resources).resource_identity == "Network/z"
    resources.append(network("a", gateway="203.0.113.2"))
    assert failure(resources).resource_identity == "Network/a"
    vm_resources = [
        network(),
        vm("z", [interface("198.51.100.1/24")]),
        vm(
            "a", [interface(None, name="one"), interface("198.51.100.2/24", name="two")]
        ),
    ]
    diagnostic = failure(vm_resources)
    assert diagnostic.resource_identity == "VirtualMachine/a"
    assert diagnostic.field_path == ("spec", "interfaces", 1, "ipv4", "address")
    assert diagnostic == failure(vm_resources)


def test_resolver_errors_still_precede_semantic_validation() -> None:
    with pytest.raises(ResourceResolutionError) as exc:
        index = resolve_resources(documents([vm(interfaces=[interface()])]))
        validate_ipv4_semantics(index)
    assert exc.value.diagnostic.code == "missing_reference"


def test_full_pipeline_is_nonmutating_and_keeps_ir_output() -> None:
    docs = load_yaml_files(
        [
            ROOT / "examples/infrastructure/resources.yml",
            ROOT / "tests/fixtures/reference-stages.yml",
        ]
    )
    before = deepcopy(docs)
    index = resolve_resources(docs)
    previous = normalize_resources(index)
    assert validate_ipv4_semantics(index) is None
    assert docs == before
    assert normalize_resources(index) == previous


@pytest.mark.parametrize("problem", ["gateway", "outside", "duplicate", "conflict"])
def test_cli_semantic_errors_and_no_file_writes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    problem: str,
) -> None:
    monkeypatch.chdir(tmp_path)
    resources = [network(), vm("a", [interface()])]
    code = {
        "gateway": "gateway_outside_subnet",
        "outside": "address_outside_subnet",
        "duplicate": "duplicate_static_ipv4",
        "conflict": "gateway_address_conflict",
    }[problem]
    if problem == "gateway":
        resources[0]["spec"]["ipv4"]["gateway"] = "198.51.100.1"
    elif problem == "outside":
        resources[1]["spec"]["interfaces"][0]["ipv4"]["address"] = "198.51.100.1/24"
    elif problem == "conflict":
        resources[1]["spec"]["interfaces"][0]["ipv4"]["address"] = "192.0.2.1/24"
    else:
        resources.append(vm("z", [interface("192.0.2.20/32")]))
    paths = []
    for i, resource in enumerate(resources):
        path = tmp_path / f"{i}.yml"
        path.write_text(yaml.safe_dump(resource), encoding="utf-8")
        paths.append(path)
    before = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    result = runner.invoke(cli.app, ["validate", *map(str, reversed(paths))])
    assert result.exit_code == 1
    assert result.stdout == ""
    assert code in result.stderr
    assert "network=Network/net" in result.stderr
    assert "cidr=192.0.2.0/24" in result.stderr
    assert "document 1, root line 1, column 1" in result.stderr
    assert "Traceback" not in result.output
    assert "Validated" not in result.output
    if problem == "duplicate":
        assert str(paths[1]) in result.stderr
        assert str(paths[2]) in result.stderr
        assert "resource=VirtualMachine/a" in result.stderr
        assert "resource=VirtualMachine/z" in result.stderr
        assert "field=spec.interfaces[0].ipv4.address" in result.stderr
        assert "conflicting declaration:" in result.stderr
    assert {p.name: p.read_bytes() for p in tmp_path.iterdir()} == before


def test_semantic_failure_stops_before_normalization(tmp_path: Path, monkeypatch):
    path = tmp_path / "network.yml"
    path.write_text(yaml.safe_dump(network(gateway="198.51.100.1")), encoding="utf-8")

    def unexpected_normalization(index):
        pytest.fail("normalization must not run after semantic failure")

    monkeypatch.setattr(cli, "normalize_resources", unexpected_normalization)
    result = runner.invoke(cli.app, ["validate", str(path)])
    assert result.exit_code == 1
    assert "gateway_outside_subnet" in result.stderr


def test_cli_valid_differing_prefix_and_literal_diagnostics(tmp_path: Path) -> None:
    resources = [
        network("[red]net"),
        vm(interfaces=[interface("192.0.2.20/32", "[red]net")]),
    ]
    path = tmp_path / "[bold]resources.yml"
    path.write_text(yaml.safe_dump_all(resources), encoding="utf-8")
    result = runner.invoke(cli.app, ["validate", str(path)])
    assert result.exit_code == 0
    assert result.stderr == ""
    assert "Validated 2 resources; resolved 1 declared reference." in result.stdout
    resources[1]["spec"]["interfaces"][0]["ipv4"]["address"] = "192.0.2.1/32"
    path.write_text(yaml.safe_dump_all(resources), encoding="utf-8")
    result = runner.invoke(cli.app, ["validate", str(path)])
    assert result.exit_code == 1
    assert str(path) in result.stderr
    assert "Network/[red]net" in result.stderr
