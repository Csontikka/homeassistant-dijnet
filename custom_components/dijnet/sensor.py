"""Support for Dijnet."""

import logging
from typing import Self

import homeassistant.helpers.config_validation as cv
import voluptuous as vol
from homeassistant.components.sensor import (
    PLATFORM_SCHEMA,
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
)
from homeassistant.config_entries import SOURCE_IMPORT, ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import PlatformNotReady
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device_registry import DeviceEntryType
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType

from .const import CONF_DOWNLOAD_DIR, DOMAIN
from .controller import (
    DijnetController,
    DijnetError,
    InvoiceIssuer,
    get_controller,
)
from .provider_names import pair_renamed

_LOGGER = logging.getLogger(__name__)

UNIQUE_ID_SUFFIX = "_amount"

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(
    {
        vol.Required(CONF_USERNAME): cv.string,
        vol.Required(CONF_PASSWORD): cv.string,
        vol.Optional(CONF_DOWNLOAD_DIR, default=""): cv.string,
    }
)


async def async_setup_platform(
    hass: HomeAssistant,
    config: ConfigType,
    async_add_entities: AddEntitiesCallback,  # noqa: ARG001
    discovery_info: DiscoveryInfoType = None,  # noqa: ARG001
) -> None:
    """Import yaml config and initiates config flow for Dijnet integration."""
    # Check if entry config exists and skips import if it does.
    if hass.config_entries.async_entries(DOMAIN):
        _LOGGER.warning(
            "Setting up Dijnet integration from yaml is deprecated."
            "Please remove configuration from yaml."
        )
        return

    hass.async_create_task(
        hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": SOURCE_IMPORT},
            data=config,
        )
    )


async def async_setup_entry(
    hass: HomeAssistant, config_entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> bool:
    """
    Setup of Dijnet sensors for the specified config_entry.

    Args:
      hass:
        The Home Assistant instance.
      config_entry:
        The config entry which is used to create sensors.
      async_add_entities:
        The callback which can be used to add new entities to Home Assistant.

    Returns:
      The value indicates whether the setup succeeded.
    """
    _LOGGER.info("Setting up Dijnet sensors.")

    controller = get_controller(hass, config_entry.data[CONF_USERNAME])

    try:
        registered_invoice_issuers = await controller.get_issuers()
    except DijnetError as error:
        # Not a permanent failure (Dijnet or the network is down, or Dijnet
        # did not accept the session): let Home Assistant retry the platform
        # instead of leaving every entity unavailable until a restart.
        raise PlatformNotReady(str(error)) from error

    for registered_invoice_issuer in registered_invoice_issuers:
        _migrate_renamed_providers(hass, config_entry.entry_id, registered_invoice_issuer)

    for registered_invoice_issuer in registered_invoice_issuers:
        async_add_entities(
            [
                InvoiceAmountSensor(
                    controller, config_entry.entry_id, registered_invoice_issuer, provider
                )
                for provider in registered_invoice_issuer.providers
            ]
        )
        _LOGGER.debug("Sensor added (%s)", registered_invoice_issuer)

    _LOGGER.info("Setting up Dijnet sensors completed.")
    return True


def _unique_id_prefix(config_entry_id: str, invoice_issuer: InvoiceIssuer) -> str:
    """The part of a sensor unique_id that precedes the provider name."""
    return f"{config_entry_id}_{invoice_issuer.issuer}_{invoice_issuer.issuer_id}_"


def _migrate_renamed_providers(
    hass: HomeAssistant, config_entry_id: str, invoice_issuer: InvoiceIssuer
) -> None:
    """
    Keeps the existing sensor when Dijnet renames a provider.

    The provider name is part of the unique_id, so without this a rename creates
    a new sensor with a new entity_id and leaves the old one unavailable, and
    everything that refers to the old entity_id silently stops seeing invoices.
    The old registry entry gets the new unique_id instead, so its entity_id,
    history and customizations stay.

    If a sensor for the new name already exists (created by a version without
    this step), nothing is changed and a warning says so. Which of the two to keep
    cannot be told safely: the user may already have moved to the new one, and
    the registry creation time is no guide, because Home Assistant restores it
    when an entity comes back under a previously deleted unique_id.

    Args:
      hass:
        The Home Assistant instance.
      config_entry_id:
        The id of the config entry the sensors belong to.
      invoice_issuer:
        The invoice issuer with the provider names Dijnet reports now.
    """
    registry = er.async_get(hass)
    prefix = _unique_id_prefix(config_entry_id, invoice_issuer)
    reported = {f"{prefix}{provider}{UNIQUE_ID_SUFFIX}" for provider in invoice_issuer.providers}

    vanished: dict[str, er.RegistryEntry] = {}
    for entry in er.async_entries_for_config_entry(registry, config_entry_id):
        unique_id = entry.unique_id
        if (
            entry.domain == "sensor"
            and unique_id.startswith(prefix)
            and unique_id.endswith(UNIQUE_ID_SUFFIX)
            and unique_id not in reported
        ):
            vanished[unique_id[len(prefix) : -len(UNIQUE_ID_SUFFIX)]] = entry

    if not vanished:
        return

    pairs = pair_renamed(list(vanished), invoice_issuer.providers)
    for old_provider, entry in vanished.items():
        new_provider = pairs.get(old_provider)
        if new_provider is None:
            _LOGGER.warning(
                "Provider '%s' of %s is no longer reported by Dijnet and no renamed "
                "provider could be matched to it unambiguously; %s is left as it is",
                old_provider,
                invoice_issuer.display_name,
                entry.entity_id,
            )
            continue

        new_unique_id = f"{prefix}{new_provider}{UNIQUE_ID_SUFFIX}"
        duplicate_id = registry.async_get_entity_id("sensor", DOMAIN, new_unique_id)
        if duplicate_id is not None:
            _LOGGER.warning(
                "Dijnet renamed provider '%s' to '%s', but %s already exists for the new "
                "name, so %s is left unavailable. Keep one of them: remove the one you do "
                "not use, and if that is the new one, restart to move its name onto the old",
                old_provider,
                new_provider,
                duplicate_id,
                entry.entity_id,
            )
            continue

        registry.async_update_entity(entry.entity_id, new_unique_id=new_unique_id)
        _LOGGER.warning(
            "Dijnet renamed provider '%s' to '%s'; %s keeps its entity_id",
            old_provider,
            new_provider,
            entry.entity_id,
        )


class InvoiceAmountSensor(SensorEntity):
    """Represents an invoice amount sensor."""

    def __init__(
        self: Self,
        controller: DijnetController,
        config_entry_id: str,
        invoice_issuer: InvoiceIssuer,
        provider: str,
    ) -> None:
        """
        Initializes a new instance of `InvoiceAmountSensor` class.

        Args:
          controller:
            The Dijnet controller.
          config_entry_id:
            The unique id of the config entry.
          invoice_issuer:
            The invoice issuer.
          provider:
            The invoice provider.
        """
        self._controller = controller
        self._invoice_issuer = invoice_issuer
        self._state = None
        self._attr_unique_id = (
            f"{_unique_id_prefix(config_entry_id, invoice_issuer)}{provider}{UNIQUE_ID_SUFFIX}"
        )
        self._provider = provider
        self.entity_description = SensorEntityDescription(
            key="invoice_amount",
            device_class=SensorDeviceClass.MONETARY,
            native_unit_of_measurement="Ft",
            name=f"Dijnet - {provider} fizetendő összeg",
        )

    @property
    def device_info(self: Self) -> DeviceInfo:
        """Returns the device information."""
        return DeviceInfo(
            entry_type=DeviceEntryType.SERVICE,
            configuration_url="https://dijnet.hu/",
            manufacturer="Dijnet Zrt",
            identifiers={
                (DOMAIN, self._invoice_issuer.issuer + "|" + self._invoice_issuer.issuer_id)
            },
            name=self._invoice_issuer.display_name,
        )

    async def async_update(self: Self) -> None:
        """Called when the entity should update its state."""
        invoices = [
            invoice
            for invoice in await self._controller.get_unpaid_invoices()
            if invoice.display_name == self._invoice_issuer.display_name
            and invoice.provider == self._provider
        ]
        self._attr_native_value = sum([invoice.amount for invoice in invoices])
        self._attr_extra_state_attributes = {
            "unpaid_invoices": [invoice.to_dictionary() for invoice in invoices]
        }
