# HA S-Charge

A Home Assistant integration of EV chargers using the S-Charge app.
So far, it only reads out data from the charger into a Python class.

## TODO

1. Implement commanding of the charger.
2. Actually integrate it with Home Assistant.
3. Clean up.

## Prequisites

Tested on Python3 3.12.3, Ubuntu 24.04 with the JNT-EVCD2-EU charger from Joint Charging (reported software version: `E3P3_H_1.1.1_R5190` and hardware version: `E3P3_V1.00`).

### Python3 virtual environment

```bash
python3 -m venv scharge_venv
source scharge_venv/bin/activate
pip3 install aiomqtt websockets
```

## Usage

Run the script as

```bash
./s-charge-server.py <charge box serial number> <your IP address>
```

You can find the serial number in the app and your IP address using the

```bash
ip a
```

command.
