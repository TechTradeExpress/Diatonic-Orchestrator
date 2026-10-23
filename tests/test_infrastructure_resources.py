"""M1.4 portable schemas, syntax boundaries and strict-loader integration."""

from copy import deepcopy
from ipaddress import IPv4Address
from pathlib import Path
from typing import Any

import pytest
from pydantic import TypeAdapter, ValidationError

from diatonic.compiler.loader import load_yaml_files
from diatonic.model import (
    Hypervisor,
    Image,
    Network,
    Resource,
    ResourceBase,
    Stage,
    VirtualMachine,
    parse_resource,
)

SPECS = {
    "Network": {
        "vlan_id": 10,
        "ipv4": {"cidr": "192.0.2.0/24", "gateway": "192.0.2.1"},
    },
    "Hypervisor": {"management": {"address": "192.0.2.10"}},
    "Image": {
        "os": {
            "family": "linux",
            "distribution": "debian",
            "version": "13",
            "architecture": "amd64",
        },
    },
    "VirtualMachine": {
        "cpu": {"cores": 4},
        "memory": {"mib": 4096},
        "placement": {"target": "Hypervisor/missing"},
        "disks": [{"name": "root", "size_gib": 32}],
        "interfaces": [
            {
                "name": "primary",
                "network": "Network/missing",
                "ipv4": {"mode": "static", "address": "192.0.2.20/24"},
            }
        ],
        "image": {"ref": "Image/missing"},
    },
}


def document(kind: str) -> dict[str, Any]:
    return {
        "api_version": "iac/v0alpha1",
        "kind": kind,
        "metadata": {"name": "example"},
        "spec": deepcopy(SPECS[kind]),
    }


def parent_at(data: Any, path: tuple[str | int, ...]) -> Any:
    for key in path[:-1]:
        data = data[key]
    return data


# Include every newly introduced leaf and required nested object.
REQUIRED_PATHS = [
    ("Network", ("spec",)),
    ("Network", ("spec", "vlan_id")),
    ("Network", ("spec", "ipv4")),
    ("Network", ("spec", "ipv4", "cidr")),
    ("Network", ("spec", "ipv4", "gateway")),
    ("Hypervisor", ("spec",)),
    ("Hypervisor", ("spec", "management")),
    ("Hypervisor", ("spec", "management", "address")),
    ("Image", ("spec",)),
    ("Image", ("spec", "os")),
    *[
        ("Image", ("spec", "os", field))
        for field in ("family", "distribution", "version", "architecture")
    ],
    ("VirtualMachine", ("spec", "placement", "target")),
    ("VirtualMachine", ("spec", "disks", 0, "name")),
    ("VirtualMachine", ("spec", "disks", 0, "size_gib")),
    ("VirtualMachine", ("spec", "interfaces", 0, "name")),
    ("VirtualMachine", ("spec", "interfaces", 0, "network")),
    ("VirtualMachine", ("spec", "interfaces", 0, "ipv4", "mode")),
    ("VirtualMachine", ("spec", "interfaces", 0, "ipv4", "address")),
    ("VirtualMachine", ("spec", "image", "ref")),
]

OBJECT_PATHS = [
    ("Network", ("spec",)),
    ("Network", ("spec", "ipv4")),
    ("Hypervisor", ("spec",)),
    ("Hypervisor", ("spec", "management")),
    ("Image", ("spec",)),
    ("Image", ("spec", "os")),
    ("VirtualMachine", ("spec", "placement")),
    ("VirtualMachine", ("spec", "disks", 0)),
    ("VirtualMachine", ("spec", "interfaces", 0)),
    ("VirtualMachine", ("spec", "interfaces", 0, "ipv4")),
    ("VirtualMachine", ("spec", "image")),
]


@pytest.mark.parametrize("model", [Network, Hypervisor, Image, VirtualMachine])
def test_dispatch_identity_and_serialization(model: Any) -> None:
    data = document(model.__name__)
    parsed = parse_resource(data)
    assert type(parsed) is model
    assert isinstance(parsed, ResourceBase)
    assert parsed.identity == f"{model.__name__}/example"
    assert parsed == model.model_validate(data)
    assert parsed == TypeAdapter(Resource).validate_python(data)
    assert parsed.model_dump(exclude_unset=True) == data
    assert parsed.lifecycle is None


@pytest.mark.parametrize(("kind", "path"), REQUIRED_PATHS)
def test_required_fields(kind: str, path: tuple[str | int, ...]) -> None:
    data = document(kind)
    del parent_at(data, path)[path[-1]]
    with pytest.raises(ValidationError) as exc:
        parse_resource(data)
    assert exc.value.errors()[0]["type"] == "missing"
    assert exc.value.errors()[0]["loc"] == (kind, *path)


@pytest.mark.parametrize(("kind", "path"), OBJECT_PATHS)
@pytest.mark.parametrize("value", [[], "invalid", 1, True])
def test_malformed_nested_objects(
    kind: str,
    path: tuple[str | int, ...],
    value: object,
) -> None:
    data = document(kind)
    parent_at(data, path)[path[-1]] = value
    with pytest.raises(ValidationError):
        parse_resource(data)


@pytest.mark.parametrize(("kind", "path"), OBJECT_PATHS)
def test_unknown_nested_fields(kind: str, path: tuple[str | int, ...]) -> None:
    data = document(kind)
    parent_at(data, (*path, "unknown"))["unknown"] = True
    with pytest.raises(ValidationError) as exc:
        parse_resource(data)
    assert exc.value.errors()[0]["type"] == "extra_forbidden"


@pytest.mark.parametrize("kind", ["Network", "Hypervisor", "Image"])
@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("api_version", "iac/v0alpha2"),
        ("unknown", True),
        ("metadata", {"name": "bad/name"}),
        ("lifecycle", {"prevent_destroy": "yes"}),
    ],
)
def test_new_resources_preserve_envelope_validation(
    kind: str,
    field: str,
    value: object,
) -> None:
    data = document(kind)
    data[field] = value
    with pytest.raises(ValidationError):
        parse_resource(data)


@pytest.mark.parametrize("kind", ["Network", "Hypervisor", "Image"])
def test_new_resources_preserve_shared_envelope_data(kind: str) -> None:
    data = document(kind)
    data.update(
        metadata={
            "name": "example",
            "description": "Portable resource",
            "labels": {"site": "lab"},
            "annotations": {"owner": "operator"},
        },
        lifecycle={"phases": {"observe": "external"}},
        depends_on=["Stage/workloads"],
        extensions={"example_platform": {"feature": True}},
    )
    parsed = parse_resource(data)
    assert parsed.model_dump(exclude_unset=True) == data
    assert parsed.lifecycle is not None
    assert parsed.lifecycle.prevent_destroy is None
    assert parsed.lifecycle.desired_state is None


@pytest.mark.parametrize("model", [Network, Hypervisor, Image])
def test_concrete_models_reject_wrong_kind(model: Any) -> None:
    data = document(model.__name__)
    data["kind"] = "Unsupported"
    with pytest.raises(ValidationError) as exc:
        model.model_validate(data)
    assert exc.value.errors()[0]["type"] == "literal_error"


@pytest.mark.parametrize("field", ["vlan_id", "size_gib"])
@pytest.mark.parametrize("value", ["10", 10.0, True, False, None, 0, -1])
def test_numeric_fields_are_strict_and_positive(field: str, value: object) -> None:
    data = document("Network" if field == "vlan_id" else "VirtualMachine")
    if field == "vlan_id":
        data["spec"][field] = value
    else:
        data["spec"]["disks"][0][field] = value
    with pytest.raises(ValidationError):
        parse_resource(data)


@pytest.mark.parametrize("value", [1, 4094])
def test_vlan_bounds_valid(value: int) -> None:
    data = document("Network")
    data["spec"]["vlan_id"] = value
    assert Network.model_validate(data).spec.vlan_id == value


@pytest.mark.parametrize("value", [4095, 4096])
def test_reserved_and_out_of_range_vlan_rejected(value: int) -> None:
    data = document("Network")
    data["spec"]["vlan_id"] = value
    with pytest.raises(ValidationError):
        parse_resource(data)


IP_PATHS = [
    ("Network", ("spec", "ipv4", "cidr")),
    ("Network", ("spec", "ipv4", "gateway")),
    ("Hypervisor", ("spec", "management", "address")),
    ("VirtualMachine", ("spec", "interfaces", 0, "ipv4", "address")),
]


@pytest.mark.parametrize(("kind", "path"), IP_PATHS)
@pytest.mark.parametrize(
    "value", [1, 1.0, True, b"192.0.2.1", IPv4Address("192.0.2.1")]
)
def test_ip_fields_reject_non_string_input(
    kind: str,
    path: tuple[str | int, ...],
    value: object,
) -> None:
    data = document(kind)
    parent_at(data, path)[path[-1]] = value
    with pytest.raises(ValidationError) as exc:
        parse_resource(data)
    assert exc.value.errors()[0]["type"] == "string_type"


@pytest.mark.parametrize(
    ("kind", "path", "value"),
    [
        *[
            ("Network", ("spec", "ipv4", "cidr"), value)
            for value in (
                "192.0.2.1/24",
                "192.0.2.0",
                "192.0.2.0/33",
                "192.0.2.0/-1",
                "192.0.2.0/255.255.255.0",
                "2001:db8::/64",
                "bad/24",
                "",
            )
        ],
        *[
            ("Network", ("spec", "ipv4", "gateway"), value)
            for value in (
                "192.0.2.256",
                "192.0.2.1/24",
                "2001:db8::1",
                "host.example",
                "",
            )
        ],
        *[
            ("Hypervisor", ("spec", "management", "address"), value)
            for value in (
                "192.0.2.999",
                "192.0.2.1/24",
                "host.example",
                "https://192.0.2.1",
                "192.0.2.1:8006",
                "fe80::1%eth0",
                "",
            )
        ],
        *[
            ("VirtualMachine", ("spec", "interfaces", 0, "ipv4", "address"), value)
            for value in (
                "192.0.2.20",
                "192.0.2.20/33",
                "192.0.2.256/24",
                "192.0.2.20/255.255.255.0",
                "2001:db8::1/64",
                "",
            )
        ],
    ],
)
def test_invalid_address_syntax(
    kind: str,
    path: tuple[str | int, ...],
    value: str,
) -> None:
    data = document(kind)
    parent_at(data, path)[path[-1]] = value
    with pytest.raises(ValidationError):
        parse_resource(data)


@pytest.mark.parametrize("value", ["2001:DB8::1", "192.0.2.10"])
def test_management_ip_families_preserve_declared_text(value: str) -> None:
    data = document("Hypervisor")
    data["spec"]["management"]["address"] = value
    assert Hypervisor.model_validate(data).spec.management.address == value


@pytest.mark.parametrize("cidr", ["0.0.0.0/0", "192.0.2.1/32"])
def test_cidr_prefix_boundaries(cidr: str) -> None:
    data = document("Network")
    data["spec"]["ipv4"]["cidr"] = cidr
    assert Network.model_validate(data).spec.ipv4.cidr == cidr


REFERENCE_PATHS = [
    ("spec", "placement", "target"),
    ("spec", "interfaces", 0, "network"),
    ("spec", "image", "ref"),
]


@pytest.mark.parametrize("path", REFERENCE_PATHS)
@pytest.mark.parametrize(
    "value",
    [
        "Stage/wrong",
        "Missing",
        "A/b/c",
        "/empty",
        "A/",
        "A/with space",
        "hypervisor/host",
        1,
        True,
        None,
    ],
)
def test_reference_syntax_and_expected_kinds(
    path: tuple[str | int, ...],
    value: object,
) -> None:
    data = document("VirtualMachine")
    parent_at(data, path)[path[-1]] = value
    with pytest.raises(ValidationError) as exc:
        parse_resource(data)
    assert exc.value.errors()[0]["loc"] == ("VirtualMachine", *path)


def test_each_reference_rejects_another_infrastructure_kind() -> None:
    for path, value in zip(
        REFERENCE_PATHS,
        ["Image/other", "Hypervisor/other", "Network/other"],
        strict=True,
    ):
        data = document("VirtualMachine")
        parent_at(data, path)[path[-1]] = value
        with pytest.raises(ValidationError):
            parse_resource(data)


@pytest.mark.parametrize("field", ["family", "distribution", "version", "architecture"])
@pytest.mark.parametrize("value", [13, 13.0, True, None, b"text", ""])
def test_image_attributes_are_nonempty_strict_strings(field: str, value: object):
    data = document("Image")
    data["spec"]["os"][field] = value
    with pytest.raises(ValidationError):
        parse_resource(data)


def test_image_attributes_have_no_vendor_allowlist() -> None:
    data = document("Image")
    data["spec"]["os"] = {
        "family": "custom-os",
        "distribution": "Example Distribution",
        "version": "rolling-2026.10",
        "architecture": "future-architecture",
    }
    assert Image.model_validate(data).spec.os.version == "rolling-2026.10"


@pytest.mark.parametrize("mode", ["dhcp", "disabled", "STATIC", "", True, 1, None])
def test_only_documented_interface_mode_supported(mode: object) -> None:
    data = document("VirtualMachine")
    data["spec"]["interfaces"][0]["ipv4"]["mode"] = mode
    with pytest.raises(ValidationError):
        parse_resource(data)


@pytest.mark.parametrize("field", ["disks", "interfaces"])
@pytest.mark.parametrize("value", [None, {}, "invalid", ()])
def test_vm_collections_must_be_lists(field: str, value: object) -> None:
    data = document("VirtualMachine")
    data["spec"][field] = value
    with pytest.raises(ValidationError):
        parse_resource(data)


@pytest.mark.parametrize("field", ["disks", "interfaces"])
@pytest.mark.parametrize("name", ["", "with space", "with/slash", 1])
def test_disk_and_interface_names(field: str, name: object) -> None:
    data = document("VirtualMachine")
    data["spec"][field][0]["name"] = name
    with pytest.raises(ValidationError):
        parse_resource(data)


def test_minimal_vm_optional_sections_and_independent_collections() -> None:
    data = document("VirtualMachine")
    data["spec"] = {"cpu": {"cores": 1}, "memory": {"mib": 1}}
    first = VirtualMachine.model_validate(data)
    second = VirtualMachine.model_validate(data)
    assert first.spec.placement is None
    assert first.spec.image is None
    assert first.spec.disks == []
    assert first.spec.interfaces == []
    full = VirtualMachine.model_validate(document("VirtualMachine"))
    first.spec.disks.extend(full.spec.disks)
    first.spec.interfaces.extend(full.spec.interfaces)
    assert second.spec.disks == []
    assert second.spec.interfaces == []
    data["spec"].update(placement=None, image=None)
    assert VirtualMachine.model_validate(data).spec.image is None


def test_interface_can_omit_ipv4_configuration() -> None:
    data = document("VirtualMachine")
    del data["spec"]["interfaces"][0]["ipv4"]
    assert VirtualMachine.model_validate(data).spec.interfaces[0].ipv4 is None


def test_schema_validation_does_not_resolve_or_check_membership() -> None:
    # Missing reference targets are deliberate: no resource index is consulted.
    vm = parse_resource(document("VirtualMachine"))
    assert isinstance(vm, VirtualMachine)
    assert vm.spec.placement is not None
    assert vm.spec.placement.target == "Hypervisor/missing"
    network = document("Network")
    network["spec"]["ipv4"]["gateway"] = "198.51.100.1"
    assert Network.model_validate(network).spec.ipv4.gateway == "198.51.100.1"


def test_generic_envelope_cannot_bypass_typed_dispatch() -> None:
    base = ResourceBase.model_validate(document("Network"))
    with pytest.raises(ValidationError):
        parse_resource(base)


def test_loader_handoff_full_multidocument_and_minimal_examples() -> None:
    root = Path(__file__).parents[1] / "examples"
    paths = [
        root / "infrastructure" / "resources.yml",
        root / "minimal" / "stages.yml",
        root / "minimal" / "resources.yml",
    ]
    documents = load_yaml_files(paths)
    resources = [parse_resource(doc.data) for doc in documents]
    assert [type(resource) for resource in resources] == [
        Network,
        Hypervisor,
        Image,
        VirtualMachine,
        Stage,
        VirtualMachine,
    ]
    assert [doc.document_index for doc in documents] == [1, 2, 3, 4, 1, 1]
    for doc, resource in zip(documents, resources, strict=True):
        assert resource.model_dump(exclude_unset=True) == doc.data
    hypervisor = resources[1]
    assert hypervisor.lifecycle is not None
    assert hypervisor.lifecycle.phases is not None
    assert hypervisor.lifecycle.phases.provision == "external"
    assert hypervisor.lifecycle.phases.configure == "external"
    vm = resources[3]
    assert isinstance(vm, VirtualMachine)
    assert vm.spec.disks[0].size_gib == 32
    assert vm.spec.interfaces[0].ipv4 is not None
    assert vm.spec.interfaces[0].ipv4.address == "192.0.2.20/24"
