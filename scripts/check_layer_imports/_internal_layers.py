#!/usr/bin/env python3
"""Internal layer model of a first-party package (ADR-001-R5).

``layer_imports.yaml`` lists, for each container package, its layers from
bottom to top. Each layer names direct children of the container: a module or
a subpackage. A child may import a child of its own layer or of a lower layer.
It must not import a higher layer or the container package itself. Every
direct child must be in exactly one layer, so a new child fails closed until
the model classifies it.
"""

import ast
import sys
from pathlib import Path

import yaml


def load_internal_layers(config_path: Path) -> dict[str, list[dict[str, object]]]:
    """Return ``container -> [{"name": str, "members": [str]}]``, bottom layer first."""
    with open(Path(config_path).resolve()) as f:
        config = yaml.safe_load(f)
    return config.get("internal_layers", {}) or {}


def layer_index(layers: list[dict[str, object]]) -> dict[str, int]:
    """Map each member to the position of its layer; raise on a duplicate member."""
    index: dict[str, int] = {}
    for position, layer in enumerate(layers):
        for member in layer["members"]:
            if member in index:
                raise ValueError(f"member {member!r} is in more than one layer")
            index[member] = position
    return index


def container_children(container_dir: Path) -> set[str]:
    """Return the direct child modules and packages of a container directory."""
    children: set[str] = set()
    for path in container_dir.iterdir():
        if path.is_dir() and (path / "__init__.py").exists():
            children.add(path.name)
        elif path.suffix == ".py" and path.name != "__init__.py":
            children.add(path.stem)
    return children


def _module_name(path: Path, platform_root: Path) -> str:
    """Return the dotted module name of a file below the platform root."""
    parts = list(path.relative_to(platform_root).with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _resolve(node: ast.ImportFrom, module: str, is_package: bool) -> str:
    """Return the absolute module path of a ``from`` import."""
    if not node.level:
        return node.module or ""
    package = module.split(".") if is_package else module.split(".")[:-1]
    base = package[: len(package) - (node.level - 1)] if node.level > 1 else package
    return ".".join(base + ([node.module] if node.module else []))


def import_edges(path: Path, platform_root: Path) -> list[tuple[str, tuple[str, ...]]]:
    """Return ``(module, names)`` for each import in one file.

    ``names`` is empty for ``import module`` and holds the imported names of
    ``from module import names``.
    """
    module = _module_name(path, platform_root)
    tree = ast.parse(path.read_text())
    edges: list[tuple[str, tuple[str, ...]]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            edges.extend((alias.name, ()) for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = _resolve(node, module, path.name == "__init__.py")
            edges.append((base, tuple(alias.name for alias in node.names)))
    return edges


def _child_of(module: str, container: str) -> str | None:
    """Return the direct child of ``container`` that contains ``module``."""
    if not module.startswith(container + "."):
        return None
    return module[len(container) + 1 :].split(".")[0]


def _edge_targets(module: str, names: tuple[str, ...], container: str, children: set[str]) -> set[str | None]:
    """Return the container children that one import reaches; ``None`` means the container itself."""
    if module != container:
        return {_child_of(module, container)} - {None}
    if not names:
        return {None}
    return {name if name in children else None for name in names}


def _file_violations(
    path: Path, platform_root: Path, container: str, source: str, index: dict[str, int], children: set[str]
) -> set[str]:
    """Return the upward and container imports of one file inside the container."""
    violations: set[str] = set()
    for module, names in import_edges(path, platform_root):
        for child in _edge_targets(module, names, container, children):
            if child is None:
                violations.add(f"{source} imports the {container} package")
            elif child != source and child in children and index.get(child, -1) > index[source]:
                violations.add(f"{source} -> {child}")
    return violations


def analyze_container(platform_root: Path, container: str, layers: list[dict[str, object]]) -> list[str]:
    """Return the internal layer violations of one container package."""
    container_dir = platform_root.joinpath(*container.split("."))
    index = layer_index(layers)
    children = container_children(container_dir)
    violations = {f"unclassified child {child!r}" for child in children - index.keys()}
    violations |= {f"stale member {member!r}" for member in index.keys() - children}
    for path in sorted(container_dir.rglob("*.py")):
        relative = path.relative_to(container_dir)
        source = relative.parts[0].removesuffix(".py")
        if source == "__init__" or source not in index:
            continue
        try:
            violations |= _file_violations(path, platform_root, container, source, index, children)
        except (OSError, SyntaxError) as exc:
            print(f"WARNING: skipped unreadable or unparseable file {path}: {exc}", file=sys.stderr)
    return sorted(violations)


def analyze_internal_layers(platform_root: Path, model: dict[str, list[dict[str, object]]]) -> dict[str, list[str]]:
    """Return ``container -> violations`` for every container with a violation."""
    result: dict[str, list[str]] = {}
    for container, layers in model.items():
        violations = analyze_container(platform_root, container, layers)
        if violations:
            result[container] = violations
    return result


def apply_internal_layer_violations(stats: dict[str, object], internal: dict[str, list[str]]) -> None:
    """Roll internal layer violations into the summary statistics."""
    for container, violations in internal.items():
        stats["violations"] = int(stats["violations"]) + len(violations)
        layer = container.split(".")[0]
        layers_with_violations = stats["layers_with_violations"]
        if layer not in layers_with_violations:
            layers_with_violations.append(layer)
        stats["violation_details"].append({"from": layer, "to": f"{container} internal layers", "modules": violations})
