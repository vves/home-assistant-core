"""Coordinate data for powerview devices."""

import asyncio
from datetime import timedelta
import logging
from typing import TYPE_CHECKING, override

from aiopvapi.events import ShadeEventState, ShadeEventStream
from aiopvapi.helpers.aiorequest import PvApiMaintenance
from aiopvapi.hub import Hub
from aiopvapi.resources.shade_data import PowerviewShadeData
from aiopvapi.shades import Shades

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import HUB_EXCEPTIONS

if TYPE_CHECKING:
    from .model import PowerviewConfigEntry

_LOGGER = logging.getLogger(__name__)


class PowerviewShadeUpdateCoordinator(DataUpdateCoordinator[PowerviewShadeData]):
    """DataUpdateCoordinator to gather data from a powerview hub."""

    config_entry: PowerviewConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: PowerviewConfigEntry,
        shades: Shades,
        hub: Hub,
    ) -> None:
        """Initialize DataUpdateCoordinator to gather data for specific Hub."""
        self.shades = shades
        self.hub = hub
        self.is_push = hub.api_version == 3
        self.event_state: ShadeEventState | None = None
        # The hub tends to crash if there are multiple radio operations at the same time
        # but it seems to handle all other requests that do not use RF without issue
        # so we have a lock to prevent multiple radio operations at the same time
        self.radio_operation_lock = asyncio.Lock()
        if self.is_push:
            shades.request.enable_position_batching(self.radio_operation_lock)
            config_entry.async_on_unload(shades.request.disable_position_batching)
        super().__init__(
            hass,
            _LOGGER,
            config_entry=config_entry,
            name=f"powerview hub {hub.hub_address}",
            update_interval=None if self.is_push else timedelta(seconds=60),
        )

    async def async_start_event_stream(self) -> None:
        """Connect the Gen3 stream before completing entry setup."""
        connected: asyncio.Future[None] = self.hass.loop.create_future()
        task = self.config_entry.async_create_background_task(
            self.hass,
            self._async_listen(connected),
            f"PowerView events {self.hub.hub_address}",
        )
        try:
            await connected
        except asyncio.CancelledError:
            task.cancel()
            raise

    async def _async_listen(self, connected: asyncio.Future[None]) -> None:
        """Receive state changes and resnapshot before reconnecting."""
        reconnect = False
        delay = 1
        while True:
            try:
                if reconnect:
                    await self._async_update_data()
                self.event_state = ShadeEventState(self.data)
                async with ShadeEventStream(self.shades.request) as stream:
                    self.async_set_updated_data(self.data)
                    if not connected.done():
                        connected.set_result(None)
                    async for event in stream.events():
                        delay = 1
                        if self.event_state.apply(event):
                            self.async_set_updated_data(self.data)
            except (UpdateFailed, *HUB_EXCEPTIONS) as error:
                if not connected.done():
                    connected.set_exception(error)
                    return
                self.async_set_update_error(UpdateFailed(str(error)))
            reconnect = True
            await asyncio.sleep(delay)
            delay = min(delay * 2, 60)

    @override
    async def _async_update_data(self) -> PowerviewShadeData:
        """Fetch data from shade endpoint."""

        try:
            shade_entries = await self.shades.get_shades()
        except PvApiMaintenance as error:
            # hub is undergoing maintenance, pause polling
            raise UpdateFailed(error) from error
        except HUB_EXCEPTIONS as error:
            raise UpdateFailed(
                f"Powerview Hub {self.hub.hub_address} did not return any data: {error}"
            ) from error

        if not shade_entries:
            raise UpdateFailed("No new shade data was returned")

        # only update if shade_entries is valid
        self.data.store_group_data(shade_entries)
        if self.is_push:
            for shade_id in shade_entries.processed:
                self.data.update_from_group_data(shade_id)

        return self.data
