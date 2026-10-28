from __future__ import annotations

from sdd_context.materials import collect_materials, parse_entry_text


def test_all_material_kinds_are_collected() -> None:
    materials = collect_materials()
    kinds = {material.kind for material in materials}
    assert {"spec", "code", "test", "task"} <= kinds
    assert len(materials) >= 30


def test_superseded_spec_is_retained_but_flagged() -> None:
    materials = collect_materials()
    old = next(material for material in materials if material.material_id.startswith("SPEC-090"))
    assert old.status == "superseded"
    assert "any string" in old.body


def test_code_material_has_real_line_span() -> None:
    materials = collect_materials()
    target = next(material for material in materials if material.material_id == "CODE-service-IssueService-list_issues")
    assert target.path.endswith("demo_project/issuehub/service.py")
    assert target.start_line < target.end_line
    assert "priority" in target.body


def test_entry_text_round_trips_metadata() -> None:
    material = next(m for m in collect_materials() if m.material_id == "SPEC-101.1")
    meta = parse_entry_text(material.text)
    assert meta["material"] == "SPEC-101.1"
    assert meta["kind"] == "spec"
    assert meta["status"] == "active"
