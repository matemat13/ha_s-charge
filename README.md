# HA S-Charge

A Home Assistant integration of EV chargers using the S-Charge app.
It reads out data from the charger into a Python class and sends them to Home Assistant over MQTT.
It can also start charging with a desired current and stop charging.

## TODO

1. Clean up.

## Prequisites

Tested on Python3 3.12.3, Ubuntu 24.04 with the JNT-EVCD2-EU charger from Joint Charging (reported software version: `E3P3_H_1.1.1_R5190` and hardware version: `E3P3_V1.00`).

Also tested as an addon of Home Assistant OS on Raspberry Pi 5.

To use this program, you'll need to know your charger's serial number.
You can find this in the S-Charge app.

## Usage

### Starting the Python scripts directly

First, set up a virtual environment as
```bash
python3 -m venv scharge_venv
source scharge_venv/bin/activate
pip3 install aiomqtt websockets
```

Then, you can either start only the data websocket server that communicates with the charger using
```bash
./src/scharge_server.py <charge box serial number> <your IP address> <websocket port>
```
For the port, you can use `"auto"` to let the OS automatically select a free port.

Or start the websocket server + MQTT server as
```bash
python3 ./src/mqtt_client <charge box serial number> <your IP address> <websocket port> <mqtt user>@<mqtt destination IP>:<mqtt port> <mqtt password>
```
Again, you can use `"auto"` for the port to let the OS pick one.
So the full command can look something like this:
```bash
python3 ./src/mqtt_client XXXXYYYYZZZZ 192.168.0.1 auto mqtt_user@homeassistant.local:1883 mqtt_password
```
After the server conencts and the data is initialized (usually takes about 10s), you should see a new device in your Home Assistant with all the data.

### Using it as a Home Assistant addon

Simply copy or clone this repo into the `/root/addons/` folder of your Home Assistant server, then install the addon through `Settings` -> `Addons` -> `Addon store` -> `S-Charge to MQTT`.

Set your charger's serial number in the addon's config.

Start the addon.

Voilá - you should now see a new device through the magic of MQTT discovery that is implemented in the addon.
