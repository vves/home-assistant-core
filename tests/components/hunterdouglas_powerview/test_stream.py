"""Test PowerView event delivery, recovery, and entry lifecycle."""

from datetime import timedelta
from unittest.mock import patch

from aiopvapi.events import ShadeEvent
from aiopvapi.helpers.aiorequest import PvApiConnectionError
from aiopvapi.shades import Shades
from freezegun.api import FrozenDateTimeFactory
import pytest
from pytest_homeassistant.common import MockConfigEntry, async_fire_time_changed

from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .conftest import MockShadeEventStream

pytestmark = [
    pytest.mark.usefixtures("mock_hunterdouglas_hub"),
    pytest.mark.parametrize("api_version", [3]),
]


async def test_stream_unload(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_event_stream: MockShadeEventStream,
) -> None:
    """Unloading the integration closes its stream connection."""
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    assert mock_event_stream.connections == 1
    assert await hass.config_entries.async_unload(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    assert mock_event_stream.closed == 1


async def test_stream_reconnect(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_event_stream: MockShadeEventStream,
    freezer: FrozenDateTimeFactory,
) -> None:
    """A disconnect marks entities unavailable and a reconnect resnapshots."""
    mock_config_entry.add_to_hass(hass)
    with patch(
        "aiopvapi.shades.Shades.get_shades",
        autospec=True,
        side_effect=Shades.get_shades,
    ) as snapshot:
        assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()
        entity_id = "cover.family_room_family_left"
        assert hass.states.get(entity_id).state != STATE_UNAVAILABLE
        mock_event_stream.queue.put_nowait(PvApiConnectionError("Connection lost"))
        await hass.async_block_till_done()
        assert hass.states.get(entity_id).state == STATE_UNAVAILABLE
        freezer.tick(timedelta(seconds=2))
        async_fire_time_changed(hass, dt_util.utcnow())
        await hass.async_block_till_done()
        assert mock_event_stream.connections == 2
        assert snapshot.await_count == 2
        assert hass.states.get(entity_id).state != STATE_UNAVAILABLE


async def test_reported_cover_position(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_event_stream: MockShadeEventStream,
) -> None:
    """External motion updates the shade, then stops at its reported position."""
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    entity_id = "cover.family_room_family_left"
    started = ShadeEvent.from_data(
        {
            "evt": "motion-started",
            "id": 413,
            "isoDate": "2026-10-26T16:38:30.183Z",
            "currentPositions": {"primary": 0, "secondary": 0, "tilt": 0},
            "targetPositions": {"primary": 0.75, "secondary": 0, "tilt": 0},
        }
    )
    mock_event_stream.queue.put_nowait(started)
    await hass.async_block_till_done()
    assert hass.states.get(entity_id).state == "opening"
    stopped = ShadeEvent.from_data(
        {
            "evt": "motion-stopped",
            "id": 413,
            "isoDate": "2026-10-26T16:38:31.643Z",
            "currentPositions": {"primary": 0.74, "secondary": 0, "tilt": 0},
        }
    )
    mock_event_stream.queue.put_nowait(stopped)
    await hass.async_block_till_done()
    state = hass.states.get(entity_id)
    assert state.state == "open"
    assert state.attributes["current_position"] == 74
