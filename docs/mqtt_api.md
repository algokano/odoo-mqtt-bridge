# MQTT API Reference

This document describes the MQTT topic structure and message formats for the Odoo-MQTT bridge. Topics and payloads may be adjusted as the project evolves.

## Overview

- **Command topics:** `warehouse/picking/{action}` — devices publish commands here
- **Response topics:** `warehouse/picking/{action}/response` — bridge publishes responses here
- **Event topics:** `warehouse/event/{event}` — bridge publishes Odoo state changes here

---

## Command Topics

### `warehouse/picking/list` — List Available Pickings

Returns all pickings in "assigned" (ready) state.

**Request:**
```json
{
  "picking_type": "outgoing"
}
```

| Field | Required | Values | Description |
|-------|----------|--------|-------------|
| `picking_type` | No | `"outgoing"`, `"incoming"`, `"internal"` | Filter by picking type. Omit to list all. |

**Response** on `warehouse/picking/list/response`:
```json
{
  "ok": true,
  "pickings": [
    {
      "id": 6,
      "name": "WH/OUT/00006",
      "partner": "Wood Corner",
      "scheduled_date": "2026-02-21 09:59:52",
      "origin": "outgoing shipment",
      "state": "assigned"
    },
    {
      "id": 2,
      "name": "WH/OUT/00002",
      "partner": "Wood Corner",
      "scheduled_date": "2026-02-24 09:59:52",
      "origin": "outgoing shipment",
      "state": "assigned"
    }
  ]
}
```

---

### `warehouse/picking/next` — Request Next Picking

Returns the next available picking (oldest scheduled date, highest priority) with all its move lines. This is the primary command for pick-by-voice or pick-by-scan workflows.

**Request:**
```json
{
  "device_id": "scanner-01",
  "picking_type": "outgoing"
}
```

| Field | Required | Description |
|-------|----------|-------------|
| `device_id` | No | Identifies the requesting device (for logging) |
| `picking_type` | No | Filter by picking type |

**Response** on `warehouse/picking/next/response`:
```json
{
  "ok": true,
  "picking": {
    "id": 6,
    "name": "WH/OUT/00006",
    "partner": "Wood Corner",
    "scheduled_date": "2026-02-21 09:59:52",
    "origin": "outgoing shipment",
    "lines": [
      {
        "move_line_id": 22,
        "product": "Desk Combination",
        "product_id": 8,
        "barcode": false,
        "location": "WH/Stock",
        "location_dest": "Partners/Customers",
        "qty_demand": 40.0,
        "qty_done": 0,
        "uom": "Units",
        "picked": false
      }
    ]
  }
}
```

**When no pickings are available:**
```json
{
  "ok": true,
  "picking": null,
  "message": "No pickings available"
}
```

---

### `warehouse/picking/confirm` — Confirm a Picked Item

Marks a move line as picked with the given quantity. Use `move_line_id` from the response of `warehouse/picking/next`.

**Request:**
```json
{
  "move_line_id": 22,
  "qty_done": 40.0
}
```

| Field | Required | Description |
|-------|----------|-------------|
| `move_line_id` | Yes | The ID of the `stock.move.line` to confirm |
| `qty_done` | Yes | The quantity that was picked |

**Response** on `warehouse/picking/confirm/response`:
```json
{
  "ok": true,
  "move_line_id": 22,
  "qty_done": 40.0,
  "picked": true
}
```

---

## Event Topics

The bridge polls Odoo every `POLL_INTERVAL` seconds (default: 10) for state changes and publishes events automatically.

### `warehouse/event/picking_ready`

Published when a picking state changes to `assigned` (ready to process).

```json
{
  "picking_id": 42,
  "name": "WH/OUT/00001",
  "picking_type": "Delivery Orders"
}
```

### `warehouse/event/picking_done`

Published when a picking state changes to `done` (completed).

```json
{
  "picking_id": 42,
  "name": "WH/OUT/00001"
}
```

---

## Error Responses

All error responses follow this format:

```json
{
  "ok": false,
  "error": "Description of what went wrong"
}
```

Examples:
- Missing required fields: `{"ok": false, "error": "move_line_id and qty_done are required"}`
- Invalid JSON payload: `{"ok": false, "error": "Invalid payload: ..."}`
- Odoo error: `{"ok": false, "error": "..."}`
- Move line not found: `{"ok": false, "error": "Move line 999 not found"}`

---

## Example Picking Workflow

A typical pick-by-scan workflow:

```
1. Scanner sends:    warehouse/picking/next       {"device_id": "scanner-01", "picking_type": "outgoing"}
2. Bridge responds:  warehouse/picking/next/response  {picking with lines...}
3. Picker scans item, scanner sends: warehouse/picking/confirm  {"move_line_id": 22, "qty_done": 40.0}
4. Bridge responds:  warehouse/picking/confirm/response  {"ok": true, "picked": true}
5. Repeat step 3 for each line in the picking.
6. When all lines are confirmed, scanner requests next picking (step 1).
```

---

## Testing with Mosquitto CLI

### Install

```bash
brew install mosquitto    # macOS
```

### Watch All Messages

```bash
mosquitto_sub -h localhost -t "warehouse/#" -v
```

### Send Commands

```bash
# List outgoing pickings
mosquitto_pub -h localhost -t "warehouse/picking/list" \
  -m '{"picking_type": "outgoing"}'

# List all pickings (no filter)
mosquitto_pub -h localhost -t "warehouse/picking/list" -m '{}'

# Get next picking with move lines
mosquitto_pub -h localhost -t "warehouse/picking/next" \
  -m '{"device_id": "scanner-01", "picking_type": "outgoing"}'

# Confirm a move line as picked
mosquitto_pub -h localhost -t "warehouse/picking/confirm" \
  -m '{"move_line_id": 22, "qty_done": 40.0}'
```

### Test Error Cases

```bash
# Missing required fields
mosquitto_pub -h localhost -t "warehouse/picking/confirm" \
  -m '{"move_line_id": 22}'

# Invalid JSON
mosquitto_pub -h localhost -t "warehouse/picking/list" -m 'not json'

# Non-existent move line
mosquitto_pub -h localhost -t "warehouse/picking/confirm" \
  -m '{"move_line_id": 99999, "qty_done": 1.0}'
```

### Watch Events Only

```bash
mosquitto_sub -h localhost -t "warehouse/event/#" -v
```
