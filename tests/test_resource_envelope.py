"""M1.1: common resource-envelope contract and validation boundaries."""

import pytest
from pydantic import ValidationError

from diatonic.model import ResourceBase


def resource(**overrides: object) -> dict[str, object]:
    data: dict[str, object] = {
        "api_version": "iac/v0alpha1",
        "kind": "VirtualMachine",
        "metadata": {"name": "docker01"},
        "spec": {"cpu": {"cores": 4}, "memory": {"mib": 4096}},
    }
    data.update(overrides)
    return data


def test_resource_envelope_identity_and_version() -> None:
    parsed = ResourceBase.model_validate(resource())
    assert parsed.identity == "VirtualMachine/docker01"
    assert parsed.api_version == "iac/v0alpha1"
    assert "identity" not in parsed.model_dump()


def test_optional_fields_are_independent_containers() -> None:
    first = ResourceBase.model_validate(resource())
    second = ResourceBase.model_validate(resource())
    first.metadata.labels["site"] = "home"
    first.depends_on.append("Network/servers")
    first.extensions["proxmox"] = {"qemu_agent": True}
    assert second.metadata.labels == {}
    assert second.depends_on == []
    assert second.extensions == {}


def test_explicit_lifecycle_and_references_are_preserved() -> None:
    parsed = ResourceBase.model_validate(
        resource(
            metadata={
                "name": "docker01",
                "description": "Docker host",
                "labels": {"site": "home"},
                "annotations": {"owner": "operator"},
            },
            lifecycle={
                "stage": "workloads",
                "desired_state": "present",
                "phases": {
                    "observe": "managed",
                    "provision": "managed",
                    "configure": "external",
                },
                "prevent_destroy": True,
            },
            depends_on=["Hypervisor/pve01", "Network/servers"],
            extensions={"proxmox": {"qemu_agent": True, "balloon_mib": 2048}},
        )
    )
    assert parsed.lifecycle is not None
    assert parsed.lifecycle.phases is not None
    assert parsed.lifecycle.phases.configure == "external"
    assert parsed.depends_on == ["Hypervisor/pve01", "Network/servers"]
    assert parsed.extensions["proxmox"]["balloon_mib"] == 2048


def test_omitted_lifecycle_has_no_implicit_ownership_or_destroy_policy() -> None:
    parsed = ResourceBase.model_validate(resource())
    assert parsed.lifecycle is None
    partial = ResourceBase.model_validate(
        resource(lifecycle={"phases": {"observe": "managed"}})
    )
    assert partial.lifecycle is not None
    assert partial.lifecycle.desired_state is None
    assert partial.lifecycle.prevent_destroy is None
    assert partial.lifecycle.phases is not None
    assert partial.lifecycle.phases.provision is None


@pytest.mark.parametrize("version", ["iac/v0alpha2", "diatonic/v0alpha1", "", 1, None])
def test_unknown_or_invalid_api_version_is_rejected(version: object) -> None:
    with pytest.raises(ValidationError):
        ResourceBase.model_validate(resource(api_version=version))


@pytest.mark.parametrize("name", ["", "foo/bar", " two", "two words", "two\nwords"])
def test_invalid_metadata_name_is_rejected(name: str) -> None:
    with pytest.raises(ValidationError):
        ResourceBase.model_validate(resource(metadata={"name": name}))


@pytest.mark.parametrize("kind", ["", "bad/kind", "bad kind", 123, None])
def test_invalid_kind_syntax_is_rejected(kind: object) -> None:
    with pytest.raises(ValidationError):
        ResourceBase.model_validate(resource(kind=kind))


@pytest.mark.parametrize(
    "reference",
    ["Hypervisor", "/pve01", "Hypervisor/", "A/b/c", "A/with space", 123],
)
def test_invalid_reference_is_rejected(reference: object) -> None:
    with pytest.raises(ValidationError):
        ResourceBase.model_validate(resource(depends_on=[reference]))


@pytest.mark.parametrize("phase", ["unknown", "MANAGED", True, 42])
def test_invalid_ownership_is_rejected(phase: object) -> None:
    with pytest.raises(ValidationError):
        ResourceBase.model_validate(
            resource(lifecycle={"phases": {"provision": phase}})
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("spec", {"cpu": object()}),
        ("metadata", {"name": "docker01", "labels": {"site": 12}}),
        ("lifecycle", {"prevent_destroy": "yes"}),
        ("depends_on", "Network/servers"),
        ("extensions", {"proxmox": {"qemu_agent": object()}}),
        ("unknown_field", True),
    ],
)
def test_invalid_types_and_unknown_fields_are_rejected(
    field: str, value: object
) -> None:
    with pytest.raises(ValidationError):
        ResourceBase.model_validate(resource(**{field: value}))


def test_nested_unknown_fields_are_rejected() -> None:
    with pytest.raises(ValidationError):
        ResourceBase.model_validate(
            resource(lifecycle={"phases": {"destroy": "managed"}})
        )


def test_required_envelope_fields_are_required() -> None:
    for key in ("api_version", "kind", "metadata"):
        data = resource()
        del data[key]
        with pytest.raises(ValidationError):
            ResourceBase.model_validate(data)
