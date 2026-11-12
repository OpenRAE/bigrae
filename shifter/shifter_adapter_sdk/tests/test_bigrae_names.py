"""Both public names expose the same contract classes and isolation boundary."""

import importlib
from importlib.metadata import version

import pytest


@pytest.mark.parametrize("namespace", ["bigrae_adapter_sdk", "shifter_adapter_sdk"])
def test_public_version_matches_installed_distribution(namespace):
    assert importlib.import_module(namespace).__version__ == version("bigrae-adapter-sdk")


@pytest.mark.parametrize(
    "module", ["guest", "model_access", "preparation", "runtime", "verification", "verification.contracts"]
)
def test_contract_types_are_not_duplicated(module):
    old = importlib.import_module("shifter_adapter_sdk." + module)
    new = importlib.import_module("bigrae_adapter_sdk." + module)
    for name, value in vars(old).items():
        if not name.startswith("_") and isinstance(value, type) and value.__module__.startswith("shifter_adapter_sdk"):
            assert getattr(new, name) is value
