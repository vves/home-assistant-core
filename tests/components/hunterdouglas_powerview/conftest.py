"""Common fixtures for Hunter Douglas Powerview tests."""

import asyncio
from collections.abc import AsyncIterator, Generator
from typing import Self
from unittest.mock import AsyncMock, patch

from aiopvapi.events import ShadeEvent
import pytest
from pytest_homeassistant.common import (
    MockConfigEntry,
    load_json_object_fixture,
    load_json_value_fixture,
)

from homeassistant.components.hunterdouglas_powerview.const import DOMAIN

from .const import MOCK_MAC


@pytest.fixture
def mock_config_entry() -> MockConfigEntry:
    """Return a configured PowerView gateway."""
    return MockConfigEntry(
        domain=DOMAIN,
        data={"host": "1.2.3.4"},
        unique_id=MOCK_MAC,
        version=1,
        minor_version=2,
    )


class MockShadeEventStream:
    """A controllable gateway stream for integration tests."""

    def __init__(self) -> None:
        """Initialize event delivery and connection tracking."""
        self.queue: asyncio.Queue[ShadeEvent | Exception] = asyncio.Queue()
        self.connections = 0
        self.closed = 0

    async def __aenter__(self) -> Self:
        """Connect without contacting a gateway."""
        self.connections += 1
        return self

    async def __aexit__(self, *args: object) -> None:
        """Record stream cleanup."""
        self.closed += 1

    async def events(self) -> AsyncIterator[ShadeEvent]:
        """Deliver gateway events or disconnect errors."""
        while True:
            event = await self.queue.get()
            if isinstance(event, Exception):
                raise event
            yield event


@pytest.fixture(autouse=True)
def mock_event_stream() -> Generator[MockShadeEventStream]:
    """Prevent integration tests from opening real gateway streams."""
    stream = MockShadeEventStream()
    with patch(
        "homeassistant.components.hunterdouglas_powerview.coordinator.ShadeEventStream",
        return_value=stream,
    ):
        yield stream


@pytest.fixture
def mock_setup_entry() -> Generator[AsyncMock]:
    """Override async_setup_entry."""
    with patch(
        "homeassistant.components.hunterdouglas_powerview.async_setup_entry",
        return_value=None,
    ) as mock_setup_entry:
        yield mock_setup_entry


@pytest.fixture
def mock_hunterdouglas_hub(
    device_json: str,
    home_json: str,
    firmware_json: str,
    rooms_json: str,
    scenes_json: str,
    scenemembers_json: str,
    shades_json: str,
) -> Generator[None]:
    """Return a mocked Powerview Hub with all data populated."""
    with (
        patch(
            "homeassistant.components.hunterdouglas_powerview.util.Hub.request_raw_data",
            return_value=load_json_object_fixture(device_json, DOMAIN),
        ),
        patch(
            "homeassistant.components.hunterdouglas_powerview.util.Hub.request_home_data",
            return_value=load_json_object_fixture(home_json, DOMAIN),
        ),
        patch(
            "homeassistant.components.hunterdouglas_powerview.util.Hub.request_raw_firmware",
            return_value=load_json_object_fixture(firmware_json, DOMAIN),
        ),
        patch(
            "homeassistant.components.hunterdouglas_powerview.Rooms.get_resources",
            return_value=load_json_value_fixture(rooms_json, DOMAIN),
        ),
        patch(
            "homeassistant.components.hunterdouglas_powerview.Scenes.get_resources",
            return_value=load_json_value_fixture(scenes_json, DOMAIN),
        ),
        patch(
            "homeassistant.components.hunterdouglas_powerview.Shades.get_resources",
            return_value=load_json_value_fixture(shades_json, DOMAIN),
        ),
        patch(
            "homeassistant.components.hunterdouglas_powerview.cover.BaseShade.refresh",
        ),
        patch(
            "aiopvapi.scenes.SceneMembers.get_resources",
            return_value=load_json_value_fixture(scenemembers_json, DOMAIN),
        ),
    ):
        yield


@pytest.fixture
def device_json(api_version: int) -> str:
    """Return the request_raw_data fixture for a specific device."""
    if api_version == 1:
        return "gen1/userdata.json"
    if api_version == 2:
        return "gen2/userdata.json"
    if api_version == 3:
        return "gen3/gateway/primary.json"
    # Add more conditions for different api_versions if needed
    raise ValueError(f"Unsupported api_version: {api_version}")


@pytest.fixture
def home_json(api_version: int) -> str:
    """Return the request_home_data fixture for a specific device."""
    if api_version == 1:
        return "gen1/userdata.json"
    if api_version == 2:
        return "gen2/userdata.json"
    if api_version == 3:
        return "gen3/home/home.json"
    # Add more conditions for different api_versions if needed
    raise ValueError(f"Unsupported api_version: {api_version}")


@pytest.fixture
def firmware_json(api_version: int) -> str:
    """Return the request_raw_firmware fixture for a specific device."""
    if api_version == 1:
        return "gen1/fwversion.json"
    if api_version == 2:
        return "gen2/fwversion.json"
    if api_version == 3:
        return "gen3/gateway/info.json"
    # Add more conditions for different api_versions if needed
    raise ValueError(f"Unsupported api_version: {api_version}")


@pytest.fixture
def rooms_json(api_version: int) -> str:
    """Return the get_resources fixture for a specific device."""
    if api_version == 1:
        return "gen1/rooms.json"
    if api_version == 2:
        return "gen2/rooms.json"
    if api_version == 3:
        return "gen3/home/rooms.json"
    # Add more conditions for different api_versions if needed
    raise ValueError(f"Unsupported api_version: {api_version}")


@pytest.fixture
def scenes_json(api_version: int) -> str:
    """Return the get_resources fixture for a specific device."""
    if api_version == 1:
        return "gen1/scenes.json"
    if api_version == 2:
        return "gen2/scenes.json"
    if api_version == 3:
        return "gen3/home/scenes.json"
    # Add more conditions for different api_versions if needed
    raise ValueError(f"Unsupported api_version: {api_version}")


@pytest.fixture
def scenemembers_json(api_version: int) -> str:
    """Return the get_resources fixture for a specific device."""
    if api_version == 1:
        return "gen1/scenemembers.json"
    if api_version == 2:
        return "gen2/scenemembers.json"
    if api_version == 3:
        # gen3 does not have scenemembers endpoint
        return "gen3/home/scenes.json"
    # Add more conditions for different api_versions if needed
    raise ValueError(f"Unsupported api_version: {api_version}")


@pytest.fixture
def shades_json(api_version: int, request: pytest.FixtureRequest) -> str:
    """Return the get_resources fixture for a specific device."""
    if hasattr(request, "param"):
        return request.param
    if api_version == 1:
        return "gen1/shades.json"
    if api_version == 2:
        return "gen2/shades.json"
    if api_version == 3:
        return "gen3/home/shades.json"
    # Add more conditions for different api_versions if needed
    raise ValueError(f"Unsupported api_version: {api_version}")


@pytest.fixture(autouse=True)
def mock_register_integration() -> Generator[AsyncMock]:
    """Prevent setup from registering against a real gateway."""
    with patch(
        "homeassistant.components.hunterdouglas_powerview.util.Hub.register_integration"
    ) as register:
        yield register
