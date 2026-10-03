"""Shared pytest fixtures built from the contract fixture kit (tests/fixtures/v1)."""

from __future__ import annotations

import pytest

from src.contracts import serialization as ser
from tests.support import fixture_assumptions, fixture_baseline, load_fixture


@pytest.fixture
def baseline():
    return fixture_baseline()


@pytest.fixture
def assumptions():
    return fixture_assumptions()


@pytest.fixture
def example_config():
    return ser.action_config_from_dict(load_fixture("action_config.json"))


@pytest.fixture
def example_constraints():
    return ser.constraint_config_from_dict(load_fixture("constraints.json"))
