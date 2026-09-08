# homeassistant-dijnet

![GitHub release (latest by date)](https://img.shields.io/github/v/release/Csontikka/homeassistant-dijnet?style=plastic)
[![HACS Custom](https://img.shields.io/badge/HACS-Custom-41BDF5.svg?style=plastic)](https://github.com/hacs/integration)
[![MIT License](https://img.shields.io/badge/License-MIT-blue.svg?style=plastic)](https://github.com/Csontikka/homeassistant-dijnet/blob/develop/LICENSE)
[![HA integration usage](https://img.shields.io/badge/dynamic/json?color=41BDF5&logo=home-assistant&label=integration%20usage&suffix=%20installs&cacheSeconds=15600&url=https://analytics.home-assistant.io/custom_integrations.json&query=$.dijnet.total&style=plastic)](https://analytics.home-assistant.io/custom_integrations.json)
[![GitHub Sponsors](https://img.shields.io/badge/GitHub-Sponsor-ea4aaa.svg?style=plastic&logo=githubsponsors)](https://github.com/sponsors/Csontikka)
[![Buy Me a Coffee](https://img.shields.io/badge/Buy%20me%20a%20coffee-donate-yellow.svg?style=plastic)](https://buymeacoffee.com/Csontikka)

[Dijnet](https://www.dijnet.hu/) integration for [Home Assistant](https://www.home-assistant.io/)

> **This is a fork.** It adds one thing to [laszlojakab/homeassistant-dijnet](https://github.com/laszlojakab/homeassistant-dijnet): the invoice state text is kept in a `payment_method` attribute instead of being discarded, so a direct debit can be told apart from an invoice that has to be paid by hand. See [Payment method](#payment-method). Everything else is upstream.
>
> The integration itself is written by [laszlojakab](https://github.com/laszlojakab). If it is useful to you, [buy him a coffee](https://www.buymeacoffee.com/laszlojakab) - the badges above only cover the upkeep of this fork.

## Installation

You can install this integration via [HACS](#hacs) or [manually](#manual).

### HACS

This integration is included in HACS. Search for the `Dijnet` integration and choose install. Reboot Home Assistant and configure the 'Dijnet' integration via the integrations page or press the blue button below.

[![Open your Home Assistant instance and start setting up a new integration.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=dijnet)

### Manual

Copy the `custom_components/dijnet` to your `custom_components` folder. Reboot Home Assistant and configure the 'Dijnet' integration via the integrations page or press the blue button below.

[![Open your Home Assistant instance and start setting up a new integration.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=dijnet)

## Features

- The integration provides services for every invoice issuer. Every invoice issuer could have multiple providers. For example DBH Zrt. invoice issuer handles invoices for FV Zrt. and FCSM Zrt. In that case the integration creates separate sensors for these providers.
- For all providers an invoice amount sensor is created. It contains the sum of unpaid amount for a provider. The details of the unpaid invoices can be read out from `unpaid_invoices` attribute of the sensor.
<!-- - For all providers a calendar entity is created. These entities are disabled by default. You can enable them by selecting 'Enable entity' toggle. The calendar entity registers an event for every incoming invoice. The event start date is the issuance date of the invoice. The event end date is the deadline of the invoice. If the invoices is paid before deadline, the end date of the event became the payment date. If the invoice is not paid until deadline the event end date will be today. -->

## Payment method

Every item of the `unpaid_invoices` attribute carries a `payment_method` field: the text
Dijnet shows in the state column of the invoice list, stored verbatim.

| value | meaning |
| --- | --- |
| `Csoportos beszedés` | direct debit, collection still pending |
| `Tovább a fizetéshez` | waiting to be paid manually |
| `Beszedés alatt` | collection in progress |
| `Rendezetlen`, `Mobiltelefonra küldve`, `Internetbanknak átadva` | other unpaid states |
| `Rendezett`, `Fizetve` | settled - these never appear in `unpaid_invoices` |

Dijnet is free to reword these, and the field is `null` for invoices restored from a
cache written by an older version, so compare defensively: an unknown or missing value
should leave an invoice **visible** rather than hide it.

### Why it is useful

An invoice collected by direct debit needs no action before its deadline - it leaves the
account on its own. After the deadline it does need attention, because a direct debit
that is still unpaid by then has failed. That difference is invisible from the amount
alone, which is why every unpaid invoice used to look equally urgent.

The examples below build on one rule:

> An unpaid invoice needs attention **unless** its `payment_method` says the
> bank is collecting it (`Csoportos beszedés` or `Beszedés alatt`) **and** its
> deadline has not passed yet.

Match those two as **substrings**, not with `==`. That is what the component
itself does (`controller._is_invoice_paid` puts both into one `collection`
case), and Dijnet is free to pad the cell with anything else.

One state does not reach these examples at all: if the text matches none of the
patterns the component knows, the invoice is logged as an error and skipped, so
it never appears in `unpaid_invoices`. Worth keeping in mind before treating an
empty list as "nothing to pay".

### Example: summary sensors

Two groups instead of one: what to pay, and what is collected automatically. List your
own provider sensors in `ids` - the integration creates one per provider, named after
the issuer and the provider.

```yaml
template:
  - sensor:
      - name: Dijnet to pay count
        unique_id: dijnet_to_pay_count
        state: >
          {% set ids = [
            'sensor.first_issuer_dijnet_first_provider_fizetendo_osszeg',
            'sensor.second_issuer_dijnet_second_provider_fizetendo_osszeg',
          ] %}
          {% set ns = namespace(count=0) %}
          {% for e in ids %}{% for inv in state_attr(e, 'unpaid_invoices') or [] %}
            {% set deadline = as_datetime(inv.deadline | default('', true)) %}
            {% set days = (deadline.date() - now().date()).days if deadline else 999 %}
            {% set pm = inv.payment_method | default('', true) %}
            {% set debit = 'Csoportos beszedés' in pm or 'Beszedés alatt' in pm %}
            {% if not (debit and days >= 0) %}{% set ns.count = ns.count + 1 %}{% endif %}
          {% endfor %}{% endfor %}
          {{ ns.count }}

      - name: Dijnet direct debit count
        unique_id: dijnet_direct_debit_count
        state: >
          {% set ids = [
            'sensor.first_issuer_dijnet_first_provider_fizetendo_osszeg',
            'sensor.second_issuer_dijnet_second_provider_fizetendo_osszeg',
          ] %}
          {% set ns = namespace(count=0) %}
          {% for e in ids %}{% for inv in state_attr(e, 'unpaid_invoices') or [] %}
            {% set deadline = as_datetime(inv.deadline | default('', true)) %}
            {% set days = (deadline.date() - now().date()).days if deadline else 999 %}
            {% set pm = inv.payment_method | default('', true) %}
            {% set debit = 'Csoportos beszedés' in pm or 'Beszedés alatt' in pm %}
            {% if debit and days >= 0 %}{% set ns.count = ns.count + 1 %}{% endif %}
          {% endfor %}{% endfor %}
          {{ ns.count }}
```

Add `_amount` variants the same way by summing `inv.amount` instead of counting, and a
`_days` sensor by taking the smallest `days` of the first group.

### Example: badges

Badges below use
[Mushroom](https://github.com/piitaya/lovelace-mushroom)'s template badge, because a
badge that changes colour with urgency needs a template. A native alternative follows.

**One badge that only appears when there is something to do.** Direct debits stay out of
the way entirely.

```yaml
type: custom:mushroom-template-badge
entity: sensor.dijnet_to_pay_count
icon: mdi:receipt
label: Dijnet
content: "{{ states('sensor.dijnet_to_pay_count') }} invoices"
color: >
  {% set days = states('sensor.dijnet_soonest_deadline_days') | int(999) %}
  {{ 'red' if days < 0 else ('orange' if days <= 3 else 'amber') }}
visibility:
  - condition: numeric_state
    entity: sensor.dijnet_to_pay_count
    above: 0
```

**A second, quieter badge for the direct debits.** Grey, and only while some collection
is still pending - so it disappears once the bank has taken the money.

```yaml
type: custom:mushroom-template-badge
entity: sensor.dijnet_direct_debit_count
icon: mdi:bank-transfer
label: Direct debit
content: "{{ states('sensor.dijnet_direct_debit_count') }} pending"
color: grey
visibility:
  - condition: numeric_state
    entity: sensor.dijnet_direct_debit_count
    above: 0
```

**Or both in one badge**, where the colour carries the meaning: blue when nothing needs
doing, amber when something does, red once a deadline has passed.

```yaml
type: custom:mushroom-template-badge
entity: sensor.dijnet_to_pay_count
icon: mdi:receipt
label: Dijnet
content: >
  {% set pay = states('sensor.dijnet_to_pay_count') | int(0) %}
  {% set debit = states('sensor.dijnet_direct_debit_count') | int(0) %}
  {% if pay > 0 %}{{ pay }} to pay{% else %}nothing to do{% endif %}
  {%- if debit > 0 %} · {{ debit }} by direct debit{% endif %}
color: >
  {% if (states('sensor.dijnet_to_pay_count') | int(0)) == 0 %}blue
  {%- else %}
  {%- set days = states('sensor.dijnet_soonest_deadline_days') | int(999) %}
  {{ 'red' if days < 0 else ('orange' if days <= 3 else 'amber') }}
  {%- endif %}
visibility:
  - condition: or
    conditions:
      - condition: numeric_state
        entity: sensor.dijnet_to_pay_count
        above: 0
      - condition: numeric_state
        entity: sensor.dijnet_direct_debit_count
        above: 0
```

**Without Mushroom.** The native badge cannot template its content, so let a template
sensor produce the text and point a plain entity badge at it:

```yaml
type: entity
entity: sensor.dijnet_to_pay_count
name: Dijnet
visibility:
  - condition: numeric_state
    entity: sensor.dijnet_to_pay_count
    above: 0
```

### Example: showing it in a card

A markdown card can list the two groups separately:

```jinja
{% set ids = ['sensor.first_issuer_dijnet_first_provider_fizetendo_osszeg'] %}
{% for e in ids %}{% for inv in state_attr(e, 'unpaid_invoices') or [] %}
  {%- set deadline = as_datetime(inv.deadline | default('', true)) %}
  {%- set days = (deadline.date() - now().date()).days if deadline else 999 %}
  {%- set pm = inv.payment_method | default('', true) %}
  {%- set debit = 'Csoportos beszedés' in pm or 'Beszedés alatt' in pm %}
- {{ inv.display_name }}: {{ inv.amount }} Ft - {{ inv.deadline }}
  {%- if debit and days >= 0 %} (direct debit, no action needed)
  {%- elif days < 0 %} **overdue**
    {%- if debit %} - the direct debit failed{% endif %}
  {%- endif %}
{% endfor %}{% endfor %}
```

## Enable debug logging

The [logger](https://www.home-assistant.io/integrations/logger/) integration lets you define the level of logging activities in Home Assistant. Turning on debug mode will show more information about the running of the integration in the homeassistant.log file.

```yaml
logger:
  default: error
  logs:
    custom_components.dijnet: debug
```
