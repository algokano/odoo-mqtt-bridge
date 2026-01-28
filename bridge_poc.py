import json
import os
import uuid
import requests
import paho.mqtt.client as mqtt

ODOO_URL = os.getenv("ODOO_URL", "http://localhost:8069")
ODOO_DB = os.getenv("ODOO_DB", "odoo_mqtt_lab")
ODOO_USER = os.getenv("ODOO_USER", "sarvar@test.com") 
ODOO_PASS = os.getenv("ODOO_PASS", "admin12345") 

MQTT_HOST = os.getenv("MQTT_HOST", "localhost")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
TOPIC_IN = os.getenv("TOPIC_IN", "odoo/cmd/set_param")
TOPIC_OUT = os.getenv("TOPIC_OUT", "odoo/resp/set_param")

session = requests.Session()

def odoo_call(method, params):
    payload = {
        "jsonrpc": "2.0",
        "method": "call",
        "params": params,
        "id": str(uuid.uuid4()),
    }
    r = session.post(f"{ODOO_URL}/jsonrpc", json=payload, timeout=15)
    r.raise_for_status()
    data = r.json()
    if "error" in data:
        raise RuntimeError(data["error"])
    return data["result"]

def login():
    # Odoo login via JSON-RPC
    res = odoo_call("call", {
        "service": "common",
        "method": "login",
        "args": [ODOO_DB, ODOO_USER, ODOO_PASS],
    })
    if not res:
        raise RuntimeError("Login failed. Check ODOO_DB / ODOO_USER / ODOO_PASS.")
    return res  # uid

def set_system_param(uid, key, value):
    # call model method on ir.config_parameter: set_param(key, value)
    return odoo_call("call", {
        "service": "object",
        "method": "execute_kw",
        "args": [
            ODOO_DB,
            uid,
            ODOO_PASS,
            "ir.config_parameter",
            "set_param",
            [key, value],
        ],
    })

def on_connect(client, userdata, flags, rc):
    print("MQTT connected:", rc)
    client.subscribe(TOPIC_IN)
    print("Subscribed to:", TOPIC_IN)

def on_message(client, userdata, msg):
    try:
        payload = msg.payload.decode("utf-8")
        data = json.loads(payload)
        key = data["key"]
        value = data["value"]

        uid = userdata["uid"]
        set_system_param(uid, key, value)

        out = {"ok": True, "key": key, "value": value}
        client.publish(TOPIC_OUT, json.dumps(out))
        print("Updated Odoo param:", out)
    except Exception as e:
        err = {"ok": False, "error": str(e)}
        client.publish(TOPIC_OUT, json.dumps(err))
        print("Error:", err)

def main():
    uid = login()
    print("Logged in. UID =", uid)

    client = mqtt.Client(userdata={"uid": uid})
    client.on_connect = on_connect
    client.on_message = on_message

    print("Connecting to MQTT...", MQTT_HOST, MQTT_PORT)
    client.connect("127.0.0.1", MQTT_PORT, 60)  # use IPv4 explicitly
    client.loop_forever()

if __name__ == "__main__":
    main()
