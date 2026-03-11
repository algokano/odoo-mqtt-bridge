# Odoo MQTT Bridge

A Python bridge that connects Odoo and MQTT for warehouse picking workflows. External devices (barcode scanners, voice picking, projection systems) communicate via MQTT; the bridge translates commands into Odoo RPC calls and publishes Odoo events back to MQTT.

```
[IoT Devices] <--MQTT--> [Bridge (Python)] <--JSON-RPC--> [Odoo 17]
```

<img width="600" alt="Screenshot 2026-01-28 at 17 38 18" src="https://github.com/user-attachments/assets/e8594e8a-863f-4e91-ba53-ea558e2848f7" />

<img width="400" alt="Screenshot 2026-01-28 at 17 38 39" src="https://github.com/user-attachments/assets/aa0712b8-37cd-4d4d-906d-4919c5171cec" />

## Prerequisites

- Docker & Docker Compose
- Python 3.8+
- (Optional) Mosquitto CLI tools for testing: `brew install mosquitto`

## Quick Start

### 1. Start Docker Services

```bash
docker-compose up -d
```

This starts:
- **Odoo 17** on `http://localhost:8069`
- **PostgreSQL 15** database
- **Mosquitto 2** MQTT broker on port `1883`

### 2. Restore the Database

The database backup is in the `data/` folder. Restore it:

```bash
# Copy dump into the postgres container
docker cp data/dump.sql $(docker-compose ps -q db):/tmp/dump.sql

# Create the database
docker-compose exec db createdb -U odoo odoo_mqtt_lab

# Restore the dump
docker-compose exec db psql -U odoo -d odoo_mqtt_lab -f /tmp/dump.sql
```

If you encounter a session permissions error in Odoo after restoring, fix it:

```bash
docker-compose exec --user root odoo bash -c "chown -R odoo:odoo /var/lib/odoo && chmod -R 700 /var/lib/odoo/sessions"
docker-compose restart odoo
```

### 3. Install the Stock Module

The restored database only has base modules. Install the stock module:

```bash
docker-compose exec odoo odoo -d odoo_mqtt_lab -i stock \
  --db_host=db --db_user=odoo --db_password=odoo \
  --stop-after-init --no-http
```

Then restart Odoo:

```bash
docker-compose restart odoo
```

### 4. Verify Odoo is Running

Open `http://localhost:8069` in your browser and log in with your Odoo credentials.

### 5. Set Up Python Environment

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 6. Configure Environment

Copy the example env file and fill in your credentials:

```bash
cp .env.example .env
```

Edit `.env` with your Odoo database name, login, and password. The `.env` file is gitignored and will not be committed.

### 7. Run the Bridge

```bash
python -m app
```

You should see:

```
2026-03-11 11:00:14 [main] INFO: Starting MQTT-Odoo bridge
2026-03-11 11:00:15 [odoo_client] INFO: Logged in to Odoo. UID = 2
2026-03-11 11:00:15 [mqtt_client] INFO: Connecting to MQTT localhost:1883
2026-03-11 11:00:15 [main] INFO: Bridge running. Polling every 10s. Press Ctrl+C to stop.
2026-03-11 11:00:15 [mqtt_client] INFO: Connected to MQTT broker
2026-03-11 11:00:15 [mqtt_client] INFO: Subscribed to warehouse/picking/#
```

## Configuration

All configuration is via environment variables:

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `ODOO_DB` | Yes | — | Odoo database name |
| `ODOO_USER` | Yes | — | Odoo login email |
| `ODOO_PASS` | Yes | — | Odoo password |
| `ODOO_URL` | No | `http://localhost:8069` | Odoo server URL |
| `MQTT_HOST` | No | `localhost` | MQTT broker host |
| `MQTT_PORT` | No | `1883` | MQTT broker port |
| `POLL_INTERVAL` | No | `10` | Seconds between Odoo event polls |
| `LOG_LEVEL` | No | `INFO` | Logging level |

See `.env.example` for a template.

## Testing All Features

### Install Mosquitto CLI Tools

```bash
brew install mosquitto
```

### Open a Listener (Terminal 1)

Watch all MQTT messages from the bridge:

```bash
mosquitto_sub -h localhost -t "warehouse/#" -v
```

### Test Commands (Terminal 2)

With the bridge running, send these commands:

#### 1. List All Outgoing Pickings

```bash
mosquitto_pub -h localhost -t "warehouse/picking/list" \
  -m '{"picking_type": "outgoing"}'
```

**Expected response** on `warehouse/picking/list/response`:
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
    }
  ]
}
```

#### 2. List All Pickings (No Filter)

```bash
mosquitto_pub -h localhost -t "warehouse/picking/list" -m '{}'
```

#### 3. Get Next Picking with Lines

```bash
mosquitto_pub -h localhost -t "warehouse/picking/next" \
  -m '{"device_id": "scanner-01", "picking_type": "outgoing"}'
```

**Expected response** on `warehouse/picking/next/response`:
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

#### 4. Confirm a Picked Item

Use a `move_line_id` from the response above:

```bash
mosquitto_pub -h localhost -t "warehouse/picking/confirm" \
  -m '{"move_line_id": 22, "qty_done": 40.0}'
```

**Expected response** on `warehouse/picking/confirm/response`:
```json
{
  "ok": true,
  "move_line_id": 22,
  "qty_done": 40.0,
  "picked": true
}
```

You can verify in Odoo UI that the move line was updated: go to Inventory > Operations > Transfers > WH/OUT/00006.

### Test Error Handling

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

### Test Odoo Events (Polling)

The bridge polls Odoo every 10 seconds for picking state changes. To test:

1. Keep `mosquitto_sub -h localhost -t "warehouse/event/#" -v` running
2. In the Odoo UI, change a picking's state (e.g., mark as Ready or Done)
3. Within 10 seconds, you should see events on `warehouse/event/picking_ready` or `warehouse/event/picking_done`

## Run Unit Tests

```bash
source .venv/bin/activate
python -m unittest tests.test_payloads -v
```

## Project Structure

```
app/
  __init__.py
  __main__.py          # python -m app entry point
  config.py            # Environment variable configuration
  main.py              # Bridge entry point with polling loop
  mqtt_client.py       # MQTT client with topic routing
  odoo_client.py       # Odoo JSON-RPC client
  handlers/
    __init__.py
    get_picking_list.py  # List assigned pickings
    request_next.py      # Get next picking + lines
    confirm_item.py      # Confirm a move line as picked
  utils/
    __init__.py
    logger.py            # Logging setup
docs/
  mqtt_api.md          # MQTT topic and payload reference
tests/
  test_payloads.py     # Unit tests for handlers
```

## MQTT API Reference

See [docs/mqtt_api.md](docs/mqtt_api.md) for full topic and payload documentation.
