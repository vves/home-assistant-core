"""Support for Aura lights integrated into PowerView shades."""

from typing import Any, override

from aiopvapi.helpers.constants import ATTR_NAME
from aiopvapi.resources.light import ShadeLightState
from aiopvapi.resources.shade import ShadeDualOverlappedIlluminated

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_COLOR_TEMP_KELVIN,
    ATTR_TRANSITION,
    ColorMode,
    LightEntity,
    LightEntityFeature,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import PowerviewShadeUpdateCoordinator
from .entity import ShadeEntity
from .model import PowerviewConfigEntry, PowerviewDeviceInfo

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: PowerviewConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Aura lights for a Gen3 gateway."""
    pv_entry = entry.runtime_data
    if not pv_entry.coordinator.is_push:
        return
    async_add_entities(
        PowerViewAuraLight(
            pv_entry.coordinator,
            pv_entry.device_info,
            getattr(pv_entry.room_data.get(shade.room_id), ATTR_NAME, ""),
            shade,
        )
        for shade in pv_entry.shade_data.values()
        if isinstance(shade, ShadeDualOverlappedIlluminated)
    )


class PowerViewAuraLight(ShadeEntity, LightEntity):
    """An Aura shade's integrated light."""

    _attr_translation_key = "aura"
    _attr_color_mode = ColorMode.COLOR_TEMP
    _attr_supported_color_modes = {ColorMode.COLOR_TEMP}
    _attr_supported_features = LightEntityFeature.TRANSITION
    _attr_min_color_temp_kelvin = 2200
    _attr_max_color_temp_kelvin = 6500

    def __init__(
        self,
        coordinator: PowerviewShadeUpdateCoordinator,
        device_info: PowerviewDeviceInfo,
        room_name: str,
        shade: ShadeDualOverlappedIlluminated,
    ) -> None:
        """Initialize the Aura light."""
        super().__init__(coordinator, device_info, room_name, shade, shade.name)
        self._shade: ShadeDualOverlappedIlluminated = shade

    @property
    def light_state(self) -> ShadeLightState | None:
        """Return the latest reported light state."""
        return ShadeLightState.from_data(
            self.data.get_raw_data(self._shade.id)["positions"].get("light")
        )

    @property
    @override
    def is_on(self) -> bool | None:
        """Return whether the light is on, preserving unknown state."""
        state = self.light_state
        if state is None or state.brightness is None:
            return None
        return state.brightness > 0

    @property
    @override
    def brightness(self) -> int | None:
        """Map reported brightness percent to Home Assistant's 0-255 scale."""
        state = self.light_state
        if state is None or state.brightness is None:
            return None
        return round(state.brightness * 255 / 100)

    @property
    @override
    def color_temp_kelvin(self) -> int | None:
        """Return the reported color temperature."""
        state = self.light_state
        if state is None or state.temperature is None:
            return None
        return round(state.temperature)

    @override
    async def async_turn_on(self, **kwargs: Any) -> None:
        """Set light state, awaiting confirmation from the stream."""
        brightness = kwargs.get(ATTR_BRIGHTNESS)
        if brightness is None:
            state = self.light_state
            fraction = (state.brightness or 100) / 100 if state is not None else 1.0
        else:
            fraction = brightness / 255
        await self._async_set_light(fraction, kwargs)

    @override
    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off the light without changing its color temperature."""
        await self._async_set_light(0.0, kwargs)

    async def _async_set_light(self, brightness: float, kwargs: dict[str, Any]) -> None:
        """Send all three required Aura command fields."""
        temperature = kwargs.get(ATTR_COLOR_TEMP_KELVIN, self.color_temp_kelvin)
        if temperature is None:
            raise HomeAssistantError(
                "Aura color temperature is unknown; specify color_temp_kelvin"
            )
        await self._shade.set_light(
            brightness=brightness,
            temperature=temperature,
            rate_in_seconds=kwargs.get(ATTR_TRANSITION, 1),
        )
