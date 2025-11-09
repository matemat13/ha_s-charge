#!/usr/bin/with-contenv bashio
CONFIG_PATH=/data/options.json

CHARGER_SERIAL=$(bashio::config "charger_serial_number")
# IP_ADDRESS=192.168.1.109
# IP_ADDRESS="homeassistant.local"
IP_ADDRESS="auto"
PORT=$(bashio::config "websocket_receive_port")
MQTT_HOST=$(bashio::services mqtt "host")
MQTT_USER=$(bashio::services mqtt "username")
MQTT_PASSWORD=$(bashio::services mqtt "password")
MQTT_SERVER="$MQTT_USER@$MQTT_HOST:1883"

source ./scharge_venv/bin/activate
./mqtt_client.py "$CHARGER_SERIAL" "$IP_ADDRESS" "$PORT" "$MQTT_SERVER" "$MQTT_PASSWORD"
# ./scharge_server.py "$CHARGER_SERIAL" "$IP_ADDRESS"
