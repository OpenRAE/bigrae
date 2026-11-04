"""Explicitly selected runner fixtures, excluded from ordinary test discovery."""

import pytest


def test_passes():
    assert 1 == 1


def test_fails():
    assert 1 == 2


@pytest.mark.skip(reason="synthetic runner fixture")
def test_skips():
    assert 1 == 2


def test_broken(missing_fixture):
    assert missing_fixture
