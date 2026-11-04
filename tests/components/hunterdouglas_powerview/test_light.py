"""Test Aura lighting through Home Assistant."""

from datetime import timedelta
from unittest.mock import AsyncMock, patch

from aiopvapi.events import ShadeEvent
from aiopvapi.shades import Shades
import pytest
from pytest_homeassistant.common import MockConfigEntry, async_fire_time_changed

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_COLOR_TEMP_KELVIN,
    ATTR_TRANSITION,
    DOMAIN as LIGHT_DOMAIN,
)
from homeassistant.const import (
    ATTR_ENTITY_ID,
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
    STATE_ON,
)
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .conftest import MockShadeEventStream

pytestmark = [
    pytest.mark.usefixtures("mock_hunterdouglas_hub"),
    pytest.mark.parametrize("api_version", [3]),
    pytest.mark.parametrize(
        "shades_json", ["gen3/home/aura_shades.json"], indirect=True
    ),
]


async def test_light_state(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_event_stream: MockShadeEventStream,
) -> None:
    """Initialize from GET and update from SSE without changing the panels."""
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    entity_id = hass.states.async_entity_ids(LIGHT_DOMAIN)[0]
    state = hass.states.get(entity_id)
    assert state.state == STATE_ON
    assert state.attributes[ATTR_BRIGHTNESS] == 128
    assert state.attributes[ATTR_COLOR_TEMP_KELVIN] == 2700
    covers = {state.entity_id: state.state for state in hass.states.async_all("cover")}
    event = ShadeEvent.from_data(
        {
            "evt": "motion-stopped",
            "id": 109,
            "isoDate": "2026-10-26T16:38:31.643Z",
            "currentPositions": {
                "primary": 0,
                "secondary": 1,
                "tilt": 0,
                "light": {"brightness": 100, "temperature": 2200},
            },
        }
    )
    mock_event_stream.queue.put_nowait(event)
    await hass.async_block_till_done()
    state = hass.states.get(entity_id)
    assert state.attributes[ATTR_BRIGHTNESS] == 255
    assert state.attributes[ATTR_COLOR_TEMP_KELVIN] == 2200
    assert {
        state.entity_id: state.state for state in hass.states.async_all("cover")
    } == covers


@pytest.mark.parametrize(
    ("action", "data", "expected"),
    [
        pytest.param(
            SERVICE_TURN_ON,
            {ATTR_BRIGHTNESS: 255, ATTR_COLOR_TEMP_KELVIN: 6500, ATTR_TRANSITION: 2},
            {"brightness": 1.0, "temperature": 6500, "rate_in_seconds": 2},
            id="turn-on",
        ),
        pytest.param(
            SERVICE_TURN_OFF,
            {},
            {"brightness": 0.0, "temperature": 2700, "rate_in_seconds": 1},
            id="turn-off",
        ),
        pytest.param(
            SERVICE_TURN_ON,
            {ATTR_COLOR_TEMP_KELVIN: 2200},
            {"brightness": 0.5, "temperature": 2200, "rate_in_seconds": 1},
            id="temperature-only",
        ),
    ],
)
async def test_light_command(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    action: str,
    data: dict[str, float],
    expected: dict[str, float],
) -> None:
    """Convert action fields and wait for reported light state."""
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    entity_id = hass.states.async_entity_ids(LIGHT_DOMAIN)[0]
    before = hass.states.get(entity_id)
    with patch(
        "homeassistant.components.hunterdouglas_powerview.light.ShadeDualOverlappedIlluminated.set_light",
        new_callable=AsyncMock,
    ) as command:
        await hass.services.async_call(
            LIGHT_DOMAIN, action, {ATTR_ENTITY_ID: entity_id, **data}, blocking=True
        )
    command.assert_awaited_once_with(**expected)
    assert hass.states.get(entity_id) == before


async def test_no_gen3_polling(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """A connected Gen3 gateway receives no scheduled position refreshes."""
    mock_config_entry.add_to_hass(hass)
    with (
        patch(
            "homeassistant.components.hunterdouglas_powerview.cover.BaseShade.refresh"
        ) as refresh,
        patch(
            "aiopvapi.shades.Shades.get_shades",
            autospec=True,
            side_effect=Shades.get_shades,
        ) as get_shades,
    ):
        assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()
        async_fire_time_changed(hass, dt_util.utcnow() + timedelta(minutes=11))
        await hass.async_block_till_done()
        refresh.assert_not_awaited()
        get_shades.assert_awaited_once()
    assert mock_config_entry.runtime_data.coordinator.update_interval is None
