"""Shared test fixtures for AIVA."""

from __future__ import annotations

import pytest
from homeassistant.components.homeassistant.exposed_entities import (
    DATA_EXPOSED_ENTITIES,
    ExposedEntities,
)
from homeassistant.setup import DATA_DEPS_REQS

from custom_components.aiva.const import DOMAIN


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Enable loading custom integrations in Home Assistant tests."""
    return enable_custom_integrations


@pytest.fixture(autouse=True)
async def setup_exposed_entities(hass):
    """Initialize exposed entities data needed by conversation in HA tests."""
    exposed_entities = ExposedEntities(hass)
    await exposed_entities.async_initialize()
    hass.data.setdefault(DATA_EXPOSED_ENTITIES, exposed_entities)


@pytest.fixture(autouse=True)
def skip_integration_dependency_setup(hass):
    """Avoid loading full HA conversation dependencies in config-flow tests."""
    hass.data.setdefault(DATA_DEPS_REQS, set()).add(DOMAIN)
