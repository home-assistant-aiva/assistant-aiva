"""Tests for AIVA sensors."""

from __future__ import annotations

from types import SimpleNamespace

from custom_components.aiva.api import (
    AivaEffectiveEntity,
    AivaHomeAutomation,
    AivaHomeSettings,
)
from custom_components.aiva.coordinator import AivaCoordinatorData
from custom_components.aiva.sensor import SENSORS


def _description(key):
    return next(description for description in SENSORS if description.key == key)


def test_home_settings_sensor_is_summarized_and_safe():
    """Expose settings without exposing the full custom prompt or voice UX."""
    data = AivaCoordinatorData(
        state="Activo",
        connected=True,
        home_name="Casa Principal",
        last_sync=None,
        home_settings=AivaHomeSettings(
            language="es",
            assistant_name="AIVA",
            voice_provider="provider",
            voice_id="voice-1",
            custom_prompt="private prompt",
            country_code="AR",
            locale="es-AR",
            timezone="America/Argentina/Buenos_Aires",
            response_style="breve",
        ),
    )
    coordinator = SimpleNamespace(data=data)
    description = _description("home_settings")

    assert description.value_fn(coordinator) == "AIVA"
    attributes = description.attributes_fn(coordinator)

    assert attributes["language"] == "es"
    assert attributes["assistant_name"] == "AIVA"
    assert attributes["custom_prompt_configured"] is True
    assert "custom_prompt" not in attributes
    assert "voice_provider" not in attributes
    assert "voice_id" not in attributes


def test_effective_entities_sensor_is_bounded_summary():
    """Expose effective entity counts and a small sample."""
    data = AivaCoordinatorData(
        state="Activo",
        connected=True,
        home_name="Casa Principal",
        last_sync=None,
        effective_entities=(
            AivaEffectiveEntity(
                entity_id="light.living",
                display_name="Luz living",
                effective_area="Living",
                is_allowed=True,
                is_visible=True,
                requires_confirmation=False,
                priority=10,
            ),
            AivaEffectiveEntity(
                entity_id="lock.front",
                display_name="Puerta",
                is_allowed=True,
                is_visible=False,
                requires_confirmation=True,
            ),
        ),
    )
    coordinator = SimpleNamespace(data=data)
    description = _description("effective_entities")

    assert description.value_fn(coordinator) == 2
    attributes = description.attributes_fn(coordinator)

    assert attributes["total_count"] == 2
    assert attributes["allowed_count"] == 2
    assert attributes["visible_count"] == 1
    assert attributes["requires_confirmation_count"] == 1
    assert attributes["sample"][0]["entity_id"] == "light.living"


def test_home_automations_sensor_is_bounded_summary():
    """Expose automation counts and a small sample."""
    data = AivaCoordinatorData(
        state="Activo",
        connected=True,
        home_name="Casa Principal",
        last_sync=None,
        home_automations=(
            AivaHomeAutomation(
                automation_id="auto-1",
                name="Apagar luces",
                enabled=True,
            ),
            AivaHomeAutomation(
                automation_id="auto-2",
                name="Aviso puerta",
                enabled=False,
            ),
        ),
    )
    coordinator = SimpleNamespace(data=data)
    description = _description("home_automations")

    assert description.value_fn(coordinator) == 2
    attributes = description.attributes_fn(coordinator)

    assert attributes["total_count"] == 2
    assert attributes["enabled_count"] == 1
    assert attributes["disabled_count"] == 1
    assert attributes["sample"][0]["id"] == "auto-1"
