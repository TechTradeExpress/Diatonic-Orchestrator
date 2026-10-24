"""M1.2 typed specs, discriminated dispatch and inherited envelope validation."""

import pytest
from pydantic import TypeAdapter, ValidationError

from diatonic.model import Resource, ResourceBase, Stage, VirtualMachine, parse_resource


def document(kind: str) -> dict[str, object]:
    return {
        "api_version": "iac/v0alpha1",
        "kind": kind,
        "metadata": {"name": "example"},
        "spec": (
            {"order": 40}
            if kind == "Stage"
            else {"cpu": {"cores": 4}, "memory": {"mib": 4096}}
        ),
    }


@pytest.mark.parametrize("model", [Stage, VirtualMachine])
def test_valid_typed_resource_and_dispatch(model: type[Stage] | type[VirtualMachine]):
    data = document(model.__name__)
    parsed = parse_resource(data)
    assert type(parsed) is model
    assert isinstance(parsed, ResourceBase)
    assert parsed.identity == f"{model.__name__}/example"
    assert parsed == model.model_validate(data)
    assert parsed == TypeAdapter(Resource).validate_python(data)
    assert parsed.model_dump(exclude_unset=True) == data
    assert parsed.lifecycle is None
    if isinstance(parsed, Stage):
        assert parsed.spec.order == 40
    else:
        assert parsed.spec.cpu.cores == 4
        assert parsed.spec.memory.mib == 4096


@pytest.mark.parametrize("order", [-40, 0, 40])
def test_stage_order_does_not_impose_undocumented_bounds(order: int):
    data = document("Stage")
    data["spec"] = {"order": order}
    assert Stage.model_validate(data).spec.order == order


@pytest.mark.parametrize("kind", ["Stage", "VirtualMachine"])
@pytest.mark.parametrize("field", ["api_version", "kind", "metadata", "spec"])
def test_required_resource_fields(kind: str, field: str):
    data = document(kind)
    del data[field]
    with pytest.raises(ValidationError):
        parse_resource(data)


@pytest.mark.parametrize(
    ("kind", "spec"),
    [
        ("Stage", {}),
        ("VirtualMachine", {}),
        ("VirtualMachine", {"cpu": {"cores": 1}}),
        ("VirtualMachine", {"memory": {"mib": 1}}),
        ("VirtualMachine", {"cpu": {}, "memory": {"mib": 1}}),
        ("VirtualMachine", {"cpu": {"cores": 1}, "memory": {}}),
    ],
)
def test_required_nested_fields(kind: str, spec: object):
    data = document(kind)
    data["spec"] = spec
    with pytest.raises(ValidationError) as exc:
        parse_resource(data)
    assert all(error["type"] == "missing" for error in exc.value.errors())


@pytest.mark.parametrize("value", ["4", 4.0, True, False, None, [], {}])
@pytest.mark.parametrize("field", ["order", "cores", "mib"])
def test_integer_fields_reject_coercion(field: str, value: object):
    data = document("Stage" if field == "order" else "VirtualMachine")
    data["spec"] = (
        {"order": value}
        if field == "order"
        else {
            "cpu": {"cores": value if field == "cores" else 1},
            "memory": {"mib": value if field == "mib" else 1},
        }
    )
    with pytest.raises(ValidationError) as exc:
        parse_resource(data)
    assert exc.value.errors()[0]["type"] == "int_type"


@pytest.mark.parametrize("value", [0, -1])
@pytest.mark.parametrize("field", ["cores", "mib"])
def test_vm_allocations_must_be_positive(field: str, value: int):
    data = document("VirtualMachine")
    data["spec"] = {
        "cpu": {"cores": value if field == "cores" else 1},
        "memory": {"mib": value if field == "mib" else 1},
    }
    with pytest.raises(ValidationError) as exc:
        parse_resource(data)
    assert exc.value.errors()[0]["type"] == "greater_than"


@pytest.mark.parametrize("kind", ["Project", "ProviderBinding", "Unknown", "stage", ""])
def test_unsupported_kinds_fail_at_discriminator(kind: str):
    with pytest.raises(ValidationError) as exc:
        parse_resource(document(kind))
    assert exc.value.errors()[0]["type"] == "union_tag_invalid"


@pytest.mark.parametrize("model", [Stage, VirtualMachine])
def test_concrete_model_rejects_wrong_kind(model: type[Stage] | type[VirtualMachine]):
    data = document(model.__name__)
    data["kind"] = "Unknown"
    with pytest.raises(ValidationError):
        model.model_validate(data)


@pytest.mark.parametrize("kind", ["Stage", "VirtualMachine"])
@pytest.mark.parametrize("spec", [None, [], "invalid", 1])
def test_spec_must_be_a_mapping(kind: str, spec: object):
    data = document(kind)
    data["spec"] = spec
    with pytest.raises(ValidationError):
        parse_resource(data)


@pytest.mark.parametrize(
    "spec",
    [
        {"cpu": None, "memory": {"mib": 1}},
        {"cpu": {"cores": 1}, "memory": []},
        {"cpu": {"cores": 1, "sockets": 1}, "memory": {"mib": 1}},
        {"cpu": {"cores": 1}, "memory": {"mib": 1, "balloon": True}},
        *[
            {"cpu": {"cores": 1}, "memory": {"mib": 1}, field: {}}
            for field in ("placement", "disks", "interfaces", "image", "provider")
        ],
    ],
)
def test_vm_invalid_nested_specs_and_unknown_fields(spec: object):
    data = document("VirtualMachine")
    data["spec"] = spec
    with pytest.raises(ValidationError):
        parse_resource(data)


def test_stage_unknown_spec_fields():
    data = document("Stage")
    data["spec"] = {"order": 40, "unknown": True}
    with pytest.raises(ValidationError):
        parse_resource(data)


@pytest.mark.parametrize("kind", ["Stage", "VirtualMachine"])
@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("api_version", "iac/v0alpha2"),
        ("api_version", None),
        ("metadata", {"name": "bad/name"}),
        ("metadata", {"name": "example", "unknown": 1}),
        ("metadata", {"name": "example", "labels": {"site": 1}}),
        ("lifecycle", {"prevent_destroy": "yes"}),
        ("lifecycle", {"phases": {"observe": "unknown"}}),
        ("lifecycle", {"unknown": True}),
        ("depends_on", ["invalid"]),
        ("extensions", {"platform": {"value": object()}}),
        ("unknown", True),
    ],
)
def test_shared_envelope_rejections(kind: str, field: str, value: object):
    data = document(kind)
    data[field] = value
    with pytest.raises(ValidationError):
        parse_resource(data)


@pytest.mark.parametrize("kind", ["Stage", "VirtualMachine"])
def test_shared_envelope_preserved(kind: str):
    data = document(kind)
    data.update(
        metadata={
            "name": "example", "description": "Example resource",
            "labels": {"site": "lab"}, "annotations": {"owner": "operator"},
        },
        lifecycle={"stage": "workloads", "phases": {"observe": "external"}},
        depends_on=["Network/servers"],
        extensions={"platform": {"feature": True, "options": [1, None, "value"]}},
    )
    parsed = parse_resource(data)
    assert parsed.model_dump(exclude_unset=True) == data
    assert parsed.lifecycle is not None
    assert parsed.lifecycle.desired_state is None
    assert parsed.lifecycle.prevent_destroy is None
    assert parsed.lifecycle.phases is not None
    assert parsed.lifecycle.phases.provision is None
