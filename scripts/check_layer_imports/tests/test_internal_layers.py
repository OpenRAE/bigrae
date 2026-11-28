"""Tests for the internal layer model check (ADR-001-R5)."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from _internal_layers import (
    analyze_container,
    analyze_internal_layers,
    apply_internal_layer_violations,
    container_children,
    import_edges,
    layer_index,
    load_internal_layers,
)

LAYER_IMPORTS_YAML = Path(__file__).resolve().parent.parent / "layer_imports.yaml"
PLATFORM_ROOT = Path(__file__).resolve().parents[3] / "shifter" / "shifter_platform"

LAYERS = [
    {"name": "low", "members": ["base", "records"]},
    {"name": "mid", "members": ["kernel"]},
    {"name": "high", "members": ["orchestration"]},
]


def _write(root: Path, relative: str, text: str = "") -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


@pytest.fixture
def container(tmp_path: Path) -> Path:
    """A synthetic ``app.svc`` container whose layers match ``LAYERS``."""
    _write(tmp_path, "app/__init__.py")
    _write(tmp_path, "app/svc/__init__.py")
    _write(tmp_path, "app/svc/base.py")
    _write(tmp_path, "app/svc/records/__init__.py")
    _write(tmp_path, "app/svc/records/store.py", "from app.svc import base\n")
    _write(tmp_path, "app/svc/kernel.py", "from app.svc.records.store import x\n")
    _write(tmp_path, "app/svc/orchestration/__init__.py")
    _write(tmp_path, "app/svc/orchestration/run.py", "from app.svc.kernel import go\nfrom ..records import store\n")
    return tmp_path


class TestLayerIndex:
    def test_maps_members_to_layer_positions(self):
        assert layer_index(LAYERS) == {"base": 0, "records": 0, "kernel": 1, "orchestration": 2}

    def test_rejects_a_member_in_two_layers(self):
        with pytest.raises(ValueError, match="more than one layer"):
            layer_index([{"name": "a", "members": ["x"]}, {"name": "b", "members": ["x"]}])


class TestImportEdges:
    def test_resolves_relative_imports(self, container: Path):
        edges = import_edges(container / "app/svc/orchestration/run.py", container)
        assert edges == [("app.svc.kernel", ("go",)), ("app.svc.records", ("store",))]


class TestAnalyzeContainer:
    def test_downward_and_same_layer_imports_pass(self, container: Path):
        assert analyze_container(container, "app.svc", LAYERS) == []

    def test_upward_import_is_a_violation(self, container: Path):
        _write(container, "app/svc/base.py", "from app.svc.kernel import go\n")
        assert analyze_container(container, "app.svc", LAYERS) == ["base -> kernel"]

    def test_upward_relative_import_is_a_violation(self, container: Path):
        _write(container, "app/svc/records/store.py", "from ..orchestration import run\n")
        violations = analyze_container(container, "app.svc", LAYERS)
        assert "records -> orchestration" in violations

    def test_import_of_the_container_package_is_a_violation(self, container: Path):
        _write(container, "app/svc/kernel.py", "from app.svc import helper\n")
        assert analyze_container(container, "app.svc", LAYERS) == ["kernel imports the app.svc package"]

    def test_bare_import_of_the_container_package_is_a_violation(self, container: Path):
        _write(container, "app/svc/kernel.py", "import app.svc\n")
        assert analyze_container(container, "app.svc", LAYERS) == ["kernel imports the app.svc package"]

    def test_importing_a_lower_child_module_through_the_container_passes(self, container: Path):
        _write(container, "app/svc/kernel.py", "from app.svc import base, records\n")
        assert analyze_container(container, "app.svc", LAYERS) == []

    def test_importing_a_higher_child_module_through_the_container_is_a_violation(self, container: Path):
        _write(container, "app/svc/base.py", "from app.svc import orchestration\n")
        assert analyze_container(container, "app.svc", LAYERS) == ["base -> orchestration"]

    def test_unclassified_child_fails_closed(self, container: Path):
        _write(container, "app/svc/extra.py")
        assert "unclassified child 'extra'" in analyze_container(container, "app.svc", LAYERS)

    def test_stale_member_is_reported(self, container: Path):
        (container / "app/svc/base.py").unlink()
        assert "stale member 'base'" in analyze_container(container, "app.svc", LAYERS)

    def test_directory_without_initializer_is_not_a_child(self, container: Path):
        _write(container, "app/svc/fixtures/data.py")
        assert "fixtures" not in container_children(container / "app/svc")


class TestStats:
    def test_violations_roll_into_summary_under_the_top_layer(self):
        stats = {"violations": 0, "layers_with_violations": [], "violation_details": []}
        apply_internal_layer_violations(stats, {"engine.services": ["a -> b"]})
        assert stats["violations"] == 1
        assert stats["layers_with_violations"] == ["engine"]
        assert stats["violation_details"][0]["from"] == "engine"


class TestRepositoryModel:
    def test_engine_containers_are_modelled(self):
        assert {"engine", "engine.services"} <= set(load_internal_layers(LAYER_IMPORTS_YAML))

    def test_repository_tree_satisfies_the_model(self):
        model = load_internal_layers(LAYER_IMPORTS_YAML)
        assert analyze_internal_layers(PLATFORM_ROOT, model) == {}
