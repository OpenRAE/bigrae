"""Tests for the engine package import boundary (ADR-001, ADR-001-R5)."""

import subprocess
import sys
from pathlib import Path
from types import ModuleType

import engine

_PLATFORM_ROOT = Path(__file__).resolve().parents[2]


class TestEngineExports:
    """The root package exports nothing; ``engine.services`` is the public interface."""

    def test_engine_error_is_exported_by_services(self):
        from engine.services import EngineError

        assert issubclass(EngineError, Exception)

    def test_root_package_exports_no_names(self):
        public = {
            name
            for name, value in vars(engine).items()
            if not name.startswith("_") and not isinstance(value, ModuleType)
        }

        assert public == set()
        assert not hasattr(engine, "__all__")

    def test_root_package_imports_without_django(self):
        """Django imports ``engine`` before the model registry is ready."""
        probe = "import sys, engine; assert not any(m.startswith('engine.') for m in sys.modules), sorted(sys.modules)"

        result = subprocess.run(  # noqa: S603 -- fixed interpreter and literal probe; no untrusted input
            [sys.executable, "-c", probe], cwd=_PLATFORM_ROOT, capture_output=True, text=True, check=False
        )

        assert result.returncode == 0, result.stderr
