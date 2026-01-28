# Odoo MQTT Bridge PoC

A simple bridge that listens to MQTT messages and updates Odoo system parameters via JSON-RPC.

## Prerequisites

- Docker & Docker Compose
- Python 3.8+

## Quick Start

### 1. Start Services

```bash
docker-compose up -d
```

This starts:
- **Odoo** on `http://localhost:8069`
- **PostgreSQL** database
- **Mosquitto** MQTT broker on port `1883`

### 2. Setup Odoo

1. Open `http://localhost:8069`
2. Create a new database named `odoo_mqtt_lab`
3. Set up a user with email `sarvar@test.com` and password `admin12345`

### 3. Run the Bridge

```bash
# Create virtual environment
python -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install requests paho-mqtt

# Run
python bridge_poc.py
```

## Configuration

Environment variables (with defaults):

| Variable | Default | Description |
|----------|---------|-------------|
| `ODOO_URL` | `http://localhost:8069` | Odoo server URL |
| `ODOO_DB` | `odoo_mqtt_lab` | Database name |
| `ODOO_USER` | `sarvar@test.com` | Odoo username |
| `ODOO_PASS` | `admin12345` | Odoo password |
| `MQTT_HOST` | `localhost` | MQTT broker host |
| `MQTT_PORT` | `1883` | MQTT broker port |

## Usage

Send a JSON message to topic `odoo/cmd/set_param`:

```bash
mosquitto_pub -h localhost -t "odoo/cmd/set_param" \
  -m '{"key": "my.param", "value": "hello"}'
```

Response will be published to `odoo/resp/set_param`:

```json
{"ok": true, "key": "my.param", "value": "hello"}
```
