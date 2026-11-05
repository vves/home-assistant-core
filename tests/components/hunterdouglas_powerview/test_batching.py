"""Test grouped PowerView actions through Home Assistant's entity services."""

import asyncio
from collections.abc import Generator
from unittest.mock import AsyncMock, patch

from aiopvapi.events import ShadeEvent
import pytest
from pytest_homeassistant.common import MockConfigEntry, load_json_array_fixture

from homeassistant.components.cover import (
    ATTR_POSITION,
    ATTR_TILT_POSITION,
    DOMAIN as COVER_DOMAIN,
    SERVICE_CLOSE_COVER,
    SERVICE_OPEN_COVER,
    SERVICE_SET_COVER_POSITION,
    SERVICE_SET_COVER_TILT_POSITION,
)
from homeassistant.components.hunterdouglas_powerview.const import DOMAIN
from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_COLOR_TEMP_KELVIN,
    ATTR_TRANSITION,
    DOMAIN as LIGHT_DOMAIN,
)
from homeassistant.const import ATTR_ENTITY_ID, SERVICE_TURN_OFF, SERVICE_TURN_ON
from homeassistant.core import HomeAssistant

from .conftest import MockShadeEventStream

pytestmark = [
    pytest.mark.usefixtures("mock_hunterdouglas_hub"),
    pytest.mark.parametrize("api_version", [3]),
    pytest.mark.parametrize(
        "shades_json", ["gen3/home/aura_shades.json"], indirect=True
    ),
]


@pytest.fixture
def mock_position_transport(shades_json: str) -> Generator[AsyncMock]:
    """Mock the HTTP transport beneath the library's real batching queue."""
    shades = load_json_array_fixture(shades_json, DOMAIN)
    with patch(
        "aiopvapi.helpers.aiorequest.AioRequest._put",
        return_value={
            "err": 0,
            "responses": [{"id": shade["id"], "err": 0} for shade in shades],
        },
    ) as transport:
        yield transport


@pytest.mark.parametrize(
    ("action", "data", "targets", "ids", "positions"),
    [
        pytest.param(
            SERVICE_OPEN_COVER,
            {},
            ["cover.family_room_family_left", "cover.family_room_family_other"],
            {413, 414},
            {"primary": 1.0},
            id="open",
        ),
        pytest.param(
            SERVICE_CLOSE_COVER,
            {},
            ["cover.family_room_family_left", "cover.family_room_family_other"],
            {413, 414},
            {"primary": 0.0},
            id="close",
        ),
        pytest.param(
            SERVICE_SET_COVER_POSITION,
            {ATTR_POSITION: 70},
            ["cover.family_room_family_left", "cover.family_room_family_other"],
            {413, 414},
            {"primary": 0.7},
            id="position",
        ),
        pytest.param(
            SERVICE_SET_COVER_TILT_POSITION,
            {ATTR_TILT_POSITION: 70},
            ["cover.family_room_family_right", "cover.family_room_family_tilt_other"],
            {6539, 6540},
            {"tilt": 0.7},
            id="tilt",
        ),
    ],
)
async def test_cover_group(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_position_transport: AsyncMock,
    action: str,
    data: dict[str, int],
    targets: list[str],
    ids: set[int],
    positions: dict[str, float],
) -> None:
    """One standard multi-entity action produces one multi-target request."""
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    await hass.services.async_call(
        COVER_DOMAIN, action, {ATTR_ENTITY_ID: targets, **data}, blocking=True
    )
    assert mock_position_transport.await_count == 1
    call = mock_position_transport.await_args
    assert call.args == ("http://1.2.3.4/home/shades/positions",)
    assert set(map(int, call.kwargs["params"]["ids"].split(","))) == ids
    assert call.kwargs["data"] == {"positions": {**positions, "velocity": 0.0}}


@pytest.mark.parametrize(
    ("action", "data", "brightness", "temperature", "rate"),
    [
        pytest.param(
            SERVICE_TURN_ON, {ATTR_BRIGHTNESS: 128}, 128 / 255, 2700, 1, id="brightness"
        ),
        pytest.param(SERVICE_TURN_OFF, {}, 0.0, 2700, 1, id="off"),
        pytest.param(
            SERVICE_TURN_ON,
            {ATTR_COLOR_TEMP_KELVIN: 4000},
            0.5,
            4000,
            1,
            id="temperature",
        ),
        pytest.param(
            SERVICE_TURN_ON,
            {ATTR_BRIGHTNESS: 255, ATTR_COLOR_TEMP_KELVIN: 2200, ATTR_TRANSITION: 3},
            1.0,
            2200,
            3,
            id="all-settings",
        ),
    ],
)
async def test_aura_group(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_position_transport: AsyncMock,
    action: str,
    data: dict[str, int],
    brightness: float,
    temperature: int,
    rate: int,
) -> None:
    """All Aura lights with the same complete light command move together."""
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    targets = hass.states.async_entity_ids(LIGHT_DOMAIN)
    assert len(targets) == 3
    before = {target: hass.states.get(target) for target in targets}
    await hass.services.async_call(
        LIGHT_DOMAIN, action, {ATTR_ENTITY_ID: targets, **data}, blocking=True
    )
    assert mock_position_transport.await_count == 1
    call = mock_position_transport.await_args
    assert set(map(int, call.kwargs["params"]["ids"].split(","))) == {109, 281, 291}
    assert call.kwargs["data"] == {
        "positions": {
            "light": {
                "brightness": brightness,
                "temperature": temperature,
                "rateInSeconds": rate,
            }
        }
    }
    assert {target: hass.states.get(target) for target in targets} == before


async def test_different_shade_conversion(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_position_transport: AsyncMock,
) -> None:
    """A bottom-up and top-down shade cannot share a converted position command."""
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    await hass.services.async_call(
        COVER_DOMAIN,
        SERVICE_SET_COVER_POSITION,
        {
            ATTR_ENTITY_ID: [
                "cover.family_room_family_left",
                "cover.bedroom_3_lounge_room_right",
            ],
            ATTR_POSITION: 70,
        },
        blocking=True,
    )
    assert mock_position_transport.await_count == 2
    assert {
        call.kwargs["data"]["positions"]["primary"]
        for call in mock_position_transport.await_args_list
    } == {0.7, 0.3}


async def test_mixed_cover_and_light_commands(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_position_transport: AsyncMock,
) -> None:
    """Simultaneous panel and light actions retain separate command bodies."""
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    await asyncio.gather(
        hass.services.async_call(
            COVER_DOMAIN,
            SERVICE_OPEN_COVER,
            {
                ATTR_ENTITY_ID: [
                    "cover.family_room_family_left",
                    "cover.family_room_family_other",
                ]
            },
            blocking=True,
        ),
        hass.services.async_call(
            LIGHT_DOMAIN,
            SERVICE_TURN_ON,
            {
                ATTR_ENTITY_ID: hass.states.async_entity_ids(LIGHT_DOMAIN),
                ATTR_BRIGHTNESS: 128,
            },
            blocking=True,
        ),
    )
    assert mock_position_transport.await_count == 2
    assert {
        frozenset(call.kwargs["data"]["positions"])
        for call in mock_position_transport.await_args_list
    } == {frozenset({"primary", "velocity"}), frozenset({"light"})}


async def test_preserve_individual_light_temperatures(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_position_transport: AsyncMock,
    mock_event_stream: MockShadeEventStream,
) -> None:
    """A brightness action preserves each light's reported temperature."""
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    mock_event_stream.queue.put_nowait(
        ShadeEvent.from_data(
            {
                "evt": "motion-stopped",
                "id": 291,
                "isoDate": "2026-11-05T16:38:31.643Z",
                "currentPositions": {"light": {"brightness": 50, "temperature": 4000}},
            }
        )
    )
    await hass.async_block_till_done()
    await hass.services.async_call(
        LIGHT_DOMAIN,
        SERVICE_TURN_ON,
        {
            ATTR_ENTITY_ID: hass.states.async_entity_ids(LIGHT_DOMAIN),
            ATTR_BRIGHTNESS: 128,
        },
        blocking=True,
    )
    assert mock_position_transport.await_count == 2
    assert {
        (
            frozenset(map(int, call.kwargs["params"]["ids"].split(","))),
            call.kwargs["data"]["positions"]["light"]["temperature"],
        )
        for call in mock_position_transport.await_args_list
    } == {(frozenset({109, 281}), 2700), (frozenset({291}), 4000)}


@pytest.mark.parametrize(
    ("brightness", "requests"),
    [
        pytest.param(131, 1, id="within-one-percent"),
        pytest.param(134, 2, id="outside-one-percent"),
    ],
)
async def test_similar_light_brightness(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_position_transport: AsyncMock,
    brightness: int,
    requests: int,
) -> None:
    """Match light brightness after converting HA's 0-255 scale to percentages."""
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    targets = hass.states.async_entity_ids(LIGHT_DOMAIN)
    await asyncio.gather(
        hass.services.async_call(
            LIGHT_DOMAIN,
            SERVICE_TURN_ON,
            {ATTR_ENTITY_ID: targets[0], ATTR_BRIGHTNESS: 128},
            blocking=True,
        ),
        hass.services.async_call(
            LIGHT_DOMAIN,
            SERVICE_TURN_ON,
            {ATTR_ENTITY_ID: targets[1], ATTR_BRIGHTNESS: brightness},
            blocking=True,
        ),
    )
    assert mock_position_transport.await_count == requests
