"""Test Yeelight."""
from datetime import timedelta
from unittest.mock import AsyncMock, patch

from yeelight import BulbException, BulbType

from homeassistant.components.yeelight import (
    CONF_NIGHTLIGHT_SWITCH,
    CONF_NIGHTLIGHT_SWITCH_TYPE,
    DATA_CONFIG_ENTRIES,
    DATA_DEVICE,
    DOMAIN,
    NIGHTLIGHT_SWITCH_TYPE_LIGHT,
)
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import (
    CONF_DEVICES,
    CONF_HOST,
    CONF_ID,
    CONF_NAME,
    STATE_UNAVAILABLE,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util

from . import (
    CONFIG_ENTRY_DATA,
    ENTITY_AMBILIGHT,
    ENTITY_BINARY_SENSOR,
    ENTITY_BINARY_SENSOR_TEMPLATE,
    ENTITY_LIGHT,
    ENTITY_NIGHTLIGHT,
    ID,
    IP_ADDRESS,
    MODULE,
    SHORT_ID,
    _mocked_bulb,
    _patch_discovery,
    _patch_discovery_interval,
    _patch_discovery_timeout,
)

from tests.common import MockConfigEntry, async_fire_time_changed


async def test_ip_changes_fallback_discovery(hass: HomeAssistant):
    """Test Yeelight ip changes and we fallback to discovery."""
    config_entry = MockConfigEntry(
        domain=DOMAIN, data={CONF_ID: ID, CONF_HOST: "5.5.5.5"}, unique_id=ID
    )
    config_entry.add_to_hass(hass)

    mocked_bulb = _mocked_bulb(True)
    mocked_bulb.bulb_type = BulbType.WhiteTempMood
    mocked_bulb.async_listen = AsyncMock(side_effect=[BulbException, None, None, None])

    with patch(f"{MODULE}.AsyncBulb", return_value=mocked_bulb), _patch_discovery():
        assert await hass.config_entries.async_setup(config_entry.entry_id)
        await hass.async_block_till_done()
        await hass.async_block_till_done()

    binary_sensor_entity_id = ENTITY_BINARY_SENSOR_TEMPLATE.format(
        f"yeelight_color_{SHORT_ID}"
    )

    type(mocked_bulb).async_get_properties = AsyncMock(None)

    await hass.data[DOMAIN][DATA_CONFIG_ENTRIES][config_entry.entry_id][
        DATA_DEVICE
    ].async_update()
    await hass.async_block_till_done()
    await hass.async_block_till_done()

    entity_registry = er.async_get(hass)
    assert entity_registry.async_get(binary_sensor_entity_id) is not None

    with patch(f"{MODULE}.AsyncBulb", return_value=mocked_bulb), _patch_discovery():
        # The discovery should update the ip address
        async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=2))
        await hass.async_block_till_done()
        assert config_entry.data[CONF_HOST] == IP_ADDRESS

    # Make sure we can still reload with the new ip right after we change it
    with patch(f"{MODULE}.AsyncBulb", return_value=mocked_bulb), _patch_discovery():
        await hass.config_entries.async_reload(config_entry.entry_id)
        await hass.async_block_till_done()

    assert entity_registry.async_get(binary_sensor_entity_id) is not None


async def test_ip_changes_id_missing_cannot_fallback(hass: HomeAssistant):
    """Test Yeelight ip changes and we fallback to discovery."""
    config_entry = MockConfigEntry(domain=DOMAIN, data={CONF_HOST: "5.5.5.5"})
    config_entry.add_to_hass(hass)

    mocked_bulb = _mocked_bulb(True)
    mocked_bulb.bulb_type = BulbType.WhiteTempMood
    mocked_bulb.async_listen = AsyncMock(side_effect=[BulbException, None, None, None])

    with patch(f"{MODULE}.AsyncBulb", return_value=mocked_bulb):
        assert not await hass.config_entries.async_setup(config_entry.entry_id)
        await hass.async_block_till_done()

    assert config_entry.state is ConfigEntryState.SETUP_RETRY


async def test_setup_discovery(hass: HomeAssistant):
    """Test setting up Yeelight by discovery."""
    config_entry = MockConfigEntry(domain=DOMAIN, data=CONFIG_ENTRY_DATA)
    config_entry.add_to_hass(hass)

    mocked_bulb = _mocked_bulb()
    with _patch_discovery(), patch(f"{MODULE}.AsyncBulb", return_value=mocked_bulb):
        assert await hass.config_entries.async_setup(config_entry.entry_id)
        await hass.async_block_till_done()

    assert hass.states.get(ENTITY_BINARY_SENSOR) is not None
    assert hass.states.get(ENTITY_LIGHT) is not None

    # Unload
    assert await hass.config_entries.async_unload(config_entry.entry_id)
    assert hass.states.get(ENTITY_BINARY_SENSOR).state == STATE_UNAVAILABLE
    assert hass.states.get(ENTITY_LIGHT).state == STATE_UNAVAILABLE

    # Remove
    assert await hass.config_entries.async_remove(config_entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get(ENTITY_BINARY_SENSOR) is None
    assert hass.states.get(ENTITY_LIGHT) is None


async def test_setup_import(hass: HomeAssistant):
    """Test import from yaml."""
    mocked_bulb = _mocked_bulb()
    name = "yeelight"
    with patch(f"{MODULE}.AsyncBulb", return_value=mocked_bulb), _patch_discovery():
        assert await async_setup_component(
            hass,
            DOMAIN,
            {
                DOMAIN: {
                    CONF_DEVICES: {
                        IP_ADDRESS: {
                            CONF_NAME: name,
                            CONF_NIGHTLIGHT_SWITCH_TYPE: NIGHTLIGHT_SWITCH_TYPE_LIGHT,
                        }
                    }
                }
            },
        )
        await hass.async_block_till_done()

    assert hass.states.get(f"binary_sensor.{name}_nightlight") is not None
    assert hass.states.get(f"light.{name}") is not None
    assert hass.states.get(f"light.{name}_nightlight") is not None
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    assert entry.unique_id == "0x000000000015243f"
    assert entry.data[CONF_ID] == "0x000000000015243f"


async def test_unique_ids_device(hass: HomeAssistant):
    """Test Yeelight unique IDs from yeelight device IDs."""
    config_entry = MockConfigEntry(
        domain=DOMAIN,
        data={**CONFIG_ENTRY_DATA, CONF_NIGHTLIGHT_SWITCH: True},
        unique_id=ID,
    )
    config_entry.add_to_hass(hass)

    mocked_bulb = _mocked_bulb()
    mocked_bulb.bulb_type = BulbType.WhiteTempMood
    with _patch_discovery(), patch(f"{MODULE}.AsyncBulb", return_value=mocked_bulb):
        assert await hass.config_entries.async_setup(config_entry.entry_id)
        await hass.async_block_till_done()

    entity_registry = er.async_get(hass)
    assert (
        entity_registry.async_get(ENTITY_BINARY_SENSOR).unique_id
        == f"{ID}-nightlight_sensor"
    )
    assert entity_registry.async_get(ENTITY_LIGHT).unique_id == ID
    assert entity_registry.async_get(ENTITY_NIGHTLIGHT).unique_id == f"{ID}-nightlight"
    assert entity_registry.async_get(ENTITY_AMBILIGHT).unique_id == f"{ID}-ambilight"


async def test_unique_ids_entry(hass: HomeAssistant):
    """Test Yeelight unique IDs from entry IDs."""
    config_entry = MockConfigEntry(
        domain=DOMAIN, data={**CONFIG_ENTRY_DATA, CONF_NIGHTLIGHT_SWITCH: True}
    )
    config_entry.add_to_hass(hass)

    mocked_bulb = _mocked_bulb()
    mocked_bulb.bulb_type = BulbType.WhiteTempMood

    with _patch_discovery(), patch(f"{MODULE}.AsyncBulb", return_value=mocked_bulb):
        assert await hass.config_entries.async_setup(config_entry.entry_id)
        await hass.async_block_till_done()

    entity_registry = er.async_get(hass)
    assert (
        entity_registry.async_get(ENTITY_BINARY_SENSOR).unique_id
        == f"{config_entry.entry_id}-nightlight_sensor"
    )
    assert entity_registry.async_get(ENTITY_LIGHT).unique_id == config_entry.entry_id
    assert (
        entity_registry.async_get(ENTITY_NIGHTLIGHT).unique_id
        == f"{config_entry.entry_id}-nightlight"
    )
    assert (
        entity_registry.async_get(ENTITY_AMBILIGHT).unique_id
        == f"{config_entry.entry_id}-ambilight"
    )


async def test_bulb_off_while_adding_in_ha(hass: HomeAssistant):
    """Test Yeelight off while adding to ha, for example on HA start."""
    config_entry = MockConfigEntry(
        domain=DOMAIN, data={**CONFIG_ENTRY_DATA, CONF_HOST: IP_ADDRESS}, unique_id=ID
    )
    config_entry.add_to_hass(hass)

    mocked_bulb = _mocked_bulb(True)
    mocked_bulb.bulb_type = BulbType.WhiteTempMood

    with patch(f"{MODULE}.AsyncBulb", return_value=mocked_bulb), _patch_discovery(
        no_device=True
    ), _patch_discovery_timeout(), _patch_discovery_interval():
        assert await hass.config_entries.async_setup(config_entry.entry_id)
        await hass.async_block_till_done()

    assert config_entry.state is ConfigEntryState.LOADED


async def test_async_listen_error_late_discovery(hass, caplog):
    """Test the async listen error."""
    config_entry = MockConfigEntry(domain=DOMAIN, data=CONFIG_ENTRY_DATA)
    config_entry.add_to_hass(hass)

    mocked_bulb = _mocked_bulb(cannot_connect=True)

    with _patch_discovery(), patch(f"{MODULE}.AsyncBulb", return_value=mocked_bulb):
        await hass.config_entries.async_setup(config_entry.entry_id)
        await hass.async_block_till_done()

    assert config_entry.state is ConfigEntryState.LOADED
    assert "Failed to connect to bulb at" in caplog.text


async def test_async_listen_error_has_host_with_id(hass: HomeAssistant):
    """Test the async listen error."""
    config_entry = MockConfigEntry(
        domain=DOMAIN, data={CONF_ID: ID, CONF_HOST: "127.0.0.1"}
    )
    config_entry.add_to_hass(hass)

    with _patch_discovery(
        no_device=True
    ), _patch_discovery_timeout(), _patch_discovery_interval(), patch(
        f"{MODULE}.AsyncBulb", return_value=_mocked_bulb(cannot_connect=True)
    ):
        await hass.config_entries.async_setup(config_entry.entry_id)

    assert config_entry.state is ConfigEntryState.LOADED


async def test_async_listen_error_has_host_without_id(hass: HomeAssistant):
    """Test the async listen error but no id."""
    config_entry = MockConfigEntry(domain=DOMAIN, data={CONF_HOST: "127.0.0.1"})
    config_entry.add_to_hass(hass)

    with _patch_discovery(
        no_device=True
    ), _patch_discovery_timeout(), _patch_discovery_interval(), patch(
        f"{MODULE}.AsyncBulb", return_value=_mocked_bulb(cannot_connect=True)
    ):
        await hass.config_entries.async_setup(config_entry.entry_id)

    assert config_entry.state is ConfigEntryState.SETUP_RETRY


async def test_async_setup_with_missing_id(hass: HomeAssistant):
    """Test that setting adds the missing CONF_ID from unique_id."""
    config_entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=ID,
        data={CONF_HOST: "127.0.0.1"},
        options={CONF_NAME: "Test name"},
    )
    config_entry.add_to_hass(hass)

    with _patch_discovery(), _patch_discovery_timeout(), _patch_discovery_interval(), patch(
        f"{MODULE}.AsyncBulb", return_value=_mocked_bulb(cannot_connect=True)
    ):
        await hass.config_entries.async_setup(config_entry.entry_id)

    assert config_entry.state is ConfigEntryState.LOADED
    assert config_entry.data[CONF_ID] == ID
