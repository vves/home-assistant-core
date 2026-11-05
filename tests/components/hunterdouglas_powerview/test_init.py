"""Tests for the Hunter Douglas PowerView integration setup."""

from unittest.mock import AsyncMock, MagicMock, call, patch

from aiopvapi.helpers.aiorequest import PvApiConnectionError
import pytest
from pytest_homeassistant.common import MockConfigEntry

from homeassistant.components.hunterdouglas_powerview.const import DOMAIN
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant

from .const import MOCK_MAC


async def test_setup_not_primary_hub(hass: HomeAssistant) -> None:
    """Test setup fails when the hub is not the primary hub."""
    entry = MockConfigEntry(domain=DOMAIN, data={"host": "1.2.3.4"}, unique_id=MOCK_MAC)
    entry.add_to_hass(hass)
    hub = MagicMock(hub_address="1.2.3.4", role="Secondary")
    hub.name = "PowerView Hub"

    with patch(
        "homeassistant.components.hunterdouglas_powerview.async_connect_hub",
        AsyncMock(return_value=MagicMock(hub=hub)),
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.SETUP_ERROR
    assert entry.reason == (
        "PowerView Hub (1.2.3.4) is performing role of Secondary Hub. Only the"
        " Primary Hub can manage shades"
    )


@pytest.mark.usefixtures("mock_hunterdouglas_hub")
@pytest.mark.parametrize(("api_version", "registrations"), [(1, 0), (2, 0), (3, 1)])
async def test_register_integration_on_setup(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_register_integration: AsyncMock,
    registrations: int,
) -> None:
    """Register both new and existing Gen3 installations on every setup."""
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    assert mock_config_entry.state is ConfigEntryState.LOADED
    assert (
        mock_register_integration.await_args_list
        == [call("HomeAssistant")] * registrations
    )
    assert await hass.config_entries.async_reload(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    assert mock_register_integration.await_args_list == [call("HomeAssistant")] * (
        2 * registrations
    )


@pytest.mark.usefixtures("mock_hunterdouglas_hub")
@pytest.mark.parametrize("api_version", [3])
async def test_registration_failure_retries_setup(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_register_integration: AsyncMock,
) -> None:
    """Do not start a gateway whose required support registration failed."""
    mock_register_integration.side_effect = PvApiConnectionError("Unavailable")
    mock_config_entry.add_to_hass(hass)
    assert not await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    assert mock_config_entry.state is ConfigEntryState.SETUP_RETRY
    mock_register_integration.assert_awaited_once_with("HomeAssistant")
