"""The surepetcare integration."""
from __future__ import annotations

from datetime import timedelta
import logging
from typing import Any

from surepy import Surepy
from surepy.enums import LockState
from surepy.exceptions import SurePetcareAuthenticationError, SurePetcareError
import voluptuous as vol

from homeassistant.const import CONF_PASSWORD, CONF_SCAN_INTERVAL, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.typing import ConfigType

from .const import (
    ATTR_FLAP_ID,
    ATTR_LOCK_STATE,
    CONF_FEEDERS,
    CONF_FLAPS,
    CONF_PETS,
    DOMAIN,
    SERVICE_SET_LOCK_STATE,
    SPC,
    SURE_API_TIMEOUT,
    TOPIC_UPDATE,
)

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["binary_sensor", "sensor"]
SCAN_INTERVAL = timedelta(minutes=3)

CONFIG_SCHEMA = vol.Schema(
    {
        DOMAIN: vol.Schema(
            vol.All(
                {
                    vol.Required(CONF_USERNAME): cv.string,
                    vol.Required(CONF_PASSWORD): cv.string,
                    vol.Optional(CONF_FEEDERS): vol.All(
                        cv.ensure_list, [cv.positive_int]
                    ),
                    vol.Optional(CONF_FLAPS): vol.All(
                        cv.ensure_list, [cv.positive_int]
                    ),
                    vol.Optional(CONF_PETS): vol.All(cv.ensure_list, [cv.positive_int]),
                    vol.Optional(CONF_SCAN_INTERVAL): cv.time_period,
                },
                cv.deprecated(CONF_FEEDERS),
                cv.deprecated(CONF_FLAPS),
                cv.deprecated(CONF_PETS),
                cv.deprecated(CONF_SCAN_INTERVAL),
            )
        )
    },
    extra=vol.ALLOW_EXTRA,
)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the Sure Petcare integration."""
    conf = config[DOMAIN]
    hass.data.setdefault(DOMAIN, {})

    try:
        surepy = Surepy(
            conf[CONF_USERNAME],
            conf[CONF_PASSWORD],
            auth_token=None,
            api_timeout=SURE_API_TIMEOUT,
            session=async_get_clientsession(hass),
        )
    except SurePetcareAuthenticationError:
        _LOGGER.error("Unable to connect to surepetcare.io: Wrong credentials!")
        return False
    except SurePetcareError as error:
        _LOGGER.error("Unable to connect to surepetcare.io: Wrong %s!", error)
        return False

    spc = SurePetcareAPI(hass, surepy)
    hass.data[DOMAIN][SPC] = spc

    await spc.async_update()

    async_track_time_interval(hass, spc.async_update, SCAN_INTERVAL)

    # load platforms
    for platform in PLATFORMS:
        hass.async_create_task(
            hass.helpers.discovery.async_load_platform(platform, DOMAIN, {}, config)
        )

    async def handle_set_lock_state(call):
        """Call when setting the lock state."""
        await spc.set_lock_state(call.data[ATTR_FLAP_ID], call.data[ATTR_LOCK_STATE])
        await spc.async_update()

    lock_state_service_schema = vol.Schema(
        {
            vol.Required(ATTR_FLAP_ID): vol.All(
                cv.positive_int, vol.In(spc.states.keys())
            ),
            vol.Required(ATTR_LOCK_STATE): vol.All(
                cv.string,
                vol.Lower,
                vol.In(
                    [
                        # https://github.com/PyCQA/pylint/issues/2062
                        # pylint: disable=no-member
                        LockState.UNLOCKED.name.lower(),
                        LockState.LOCKED_IN.name.lower(),
                        LockState.LOCKED_OUT.name.lower(),
                        LockState.LOCKED_ALL.name.lower(),
                    ]
                ),
            ),
        }
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_LOCK_STATE,
        handle_set_lock_state,
        schema=lock_state_service_schema,
    )

    return True


class SurePetcareAPI:
    """Define a generic Sure Petcare object."""

    def __init__(self, hass: HomeAssistant, surepy: Surepy) -> None:
        """Initialize the Sure Petcare object."""
        self.hass = hass
        self.surepy = surepy
        self.states = {}

    async def async_update(self, _: Any = None) -> None:
        """Get the latest data from Sure Petcare."""

        try:
            self.states = await self.surepy.get_entities()
        except SurePetcareError as error:
            _LOGGER.error("Unable to fetch data: %s", error)
            return

        async_dispatcher_send(self.hass, TOPIC_UPDATE)

    async def set_lock_state(self, flap_id: int, state: str) -> None:
        """Update the lock state of a flap."""

        # https://github.com/PyCQA/pylint/issues/2062
        # pylint: disable=no-member
        if state == LockState.UNLOCKED.name.lower():
            await self.surepy.sac.unlock(flap_id)
        elif state == LockState.LOCKED_IN.name.lower():
            await self.surepy.sac.lock_in(flap_id)
        elif state == LockState.LOCKED_OUT.name.lower():
            await self.surepy.sac.lock_out(flap_id)
        elif state == LockState.LOCKED_ALL.name.lower():
            await self.surepy.sac.lock(flap_id)
