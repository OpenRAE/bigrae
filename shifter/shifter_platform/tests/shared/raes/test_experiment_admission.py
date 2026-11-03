"""The public admission adapter rejects unsupported installed dependency tuples."""

import pytest


def test_cleanup_receipts_refuse_incomplete_original_authority():
    from shared.raes.experiment_admission import validate_experiment_cleanup

    with pytest.raises(ValueError, match="invalid or unverified"):
        validate_experiment_cleanup({}, "entry", "attempt", {})


def test_unsupported_dependency_tuple_is_refused(monkeypatch):
    from shared.raes.experiment_admission import dependency_tuple

    monkeypatch.setattr("shared.raes.experiment_admission.version", lambda name: "0.0.0")
    with pytest.raises(ValueError, match="Unsupported experiment dependency tuple"):
        dependency_tuple()


@pytest.mark.parametrize("name,value", [("python", "3.13"), ("django", "6.1.0"), ("raes", "0.0.0")])
def test_reload_refuses_an_unsupported_retained_dependency_tuple(name, value):
    from shared.raes.experiment_admission import dependency_tuple, encode_retained, validate_retained

    payload = {"dependencies": {**dependency_tuple(), name: value}}
    with pytest.raises(ValueError, match="Unsupported experiment dependency tuple"):
        validate_retained(encode_retained(payload))


def test_snapshot_counts_empty_directories_against_member_bound(tmp_path):
    from shared.raes.experiment_pack_snapshot import stage_local_experiment_pack
    from shared.raes.package_loader import RaesPackageError

    root = tmp_path / "source"
    root.mkdir()
    (root / "first").mkdir()
    (root / "second").mkdir()
    with pytest.raises(RaesPackageError), stage_local_experiment_pack(root, max_bytes=100, max_entries=1):
        pytest.fail("An oversized directory tree must not be admitted")


@pytest.mark.parametrize("unsafe", ["symlink", "oversized"])
def test_snapshot_refuses_unsafe_members_before_reading_bytes(tmp_path, unsafe):
    from shared.raes.experiment_pack_snapshot import stage_local_experiment_pack
    from shared.raes.package_loader import RaesPackageError

    root = tmp_path / "source"
    root.mkdir()
    (root / "member").write_bytes(b"bounded original")
    if unsafe == "symlink":
        (root / "link").symlink_to(root / "member")
    with pytest.raises((RaesPackageError, OSError)), stage_local_experiment_pack(root, max_bytes=1, max_entries=10):
        pytest.fail("Unsafe source bytes must not reach the compiler")
