#!/usr/bin/env python3

import asyncio
import aiomqtt
import json

from scharge_server import *

class MQTTSwitchMgr:
    def __init__(self, mqtt_client: aiomqtt.Client, mqtt_cfg: dict, switch_method, availability):
        self.switch_method = switch_method
        self.availability = availability
        self.mqtt_client = mqtt_client
        self.mqtt_cfg = mqtt_cfg

        self.command_topic = self.mqtt_cfg["command_topic"]

    # def run(self):
    #     await self.mqtt_client.subscribe(self.mqtt_cfg["command_topic"])
    #     async for message in client.messages:
    #         self.logger.info(message.payload)

class MQTTClient:
    def __init__(self, hostname: str, port: str, username: str, password: str, scharge_conn: SChargeConn, logger: logging.Logger):
        self.hostname = hostname
        self.port = int(port)
        self.username = username
        self.password = password
        self.scharge_conn = scharge_conn
        self.logger = logger
        self.topic_mgrs = list()

    async def main(self):
        self.logger.info(f"Starting MQTT client with hostname {self.hostname}:{self.port}, user: {self.username}, password: {self.password}.")
        async with aiomqtt.Client(hostname=self.hostname, port=self.port, username=self.username, password=self.password) as client:
            # TODO: fix using Futures
            while not self.scharge_conn.charger_state.initialized():
                await asyncio.sleep(1)
            discovery_topic = f"homeassistant/device/scharge{self.scharge_conn.charge_box_serial}/config"

            msg = self.generate_discovery_payload(self.scharge_conn)
            self.logger.info(f"Publishing discovery message {msg}")
            await client.publish(discovery_topic, msg)

            await client.subscribe("homeassistant/status")
            async for message in client.messages:
                self.logger.info(message.payload)

    def generate_discovery_payload(self, sconn: SChargeConn):
        chinfo = sconn.charger_state
        ret = \
            {
              "dev":
              {
                "ids": f"scharge{chinfo.chargeBoxSN}",
                "name": "SCharge",
                "mf": "Joint Charging",
                "mdl": "EVCD2",
                "sw": f"{chinfo.sVersion.value}",
                "sn": f"{chinfo.chargeBoxSN}",
                "hw": f"{chinfo.hVersion.value}",
              },
              "o":
              {
                "name": "scharge_server",
                "sw": "1.0",
                "url": "https://github.com/matemat13/ha_s-charge"
              },
              "cmps":
              {
                "scharge_start_charging":
                {
                    "p": "switch",
                    "name": "Start Charging",
                    "unique_id": "scharge_start_charging",
                    "device_class": "switch",
                    "state_topic": "scharge/start_charging/state",
                    "command_topic": "scharge/start_charging/set",
                    "availability":
                    {
                      "topic": "scharge/start_charging/available",
                      "payload_available": "online",
                      "payload_not_available": "offline",
                    },
                    "payload_on": "ON",
                    "payload_off": "OFF",
                    "state_on": "ON",
                    "state_off": "OFF",
                    "optimistic": False,
                    "qos": 0,
                    "retain": True,
                },
                "scharge_stop_charging":
                {
                    "p": "switch",
                    "name": "Stop Charging",
                    "unique_id": "scharge_stop_charging",
                    "device_class": "switch",
                    "state_topic": "scharge/stop_charging/state",
                    "command_topic": "scharge/stop_charging/set",
                    "availability":
                    {
                      "topic": "scharge/stop_charging/available",
                      "payload_available": "online",
                      "payload_not_available": "offline",
                    },
                    "payload_on": "ON",
                    "payload_off": "OFF",
                    "state_on": "ON",
                    "state_off": "OFF",
                    "optimistic": False,
                    "qos": 0,
                    "retain": True,
                },
              },
              "state_topic": "scharge/state",
              "qos": 2
            }
        return json.dumps(ret, separators=(',', ':'))

if __name__ == "__main__":
    if len(sys.argv) < 5:
        print("Please specify the charger serial number, this computer's IP address, and the MQTT server address (user@address:port) and password!")
        print("example:")
        print("python3 mqtt_client XXXXYYYYZZZZ 192.168.0.1 mqtt_user@homeassistant.local:1883 mqtt_password")
        exit(1)

    scharge_logger = logging.getLogger("SCharge_server")
    scharge_logger.setLevel(logging.DEBUG)
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')

    fh = logging.FileHandler("/tmp/scharge-server.log")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(formatter)
    scharge_logger.addHandler(fh)

    sh = logging.StreamHandler()
    sh.setLevel(logging.INFO)
    sh.setFormatter(formatter)
    scharge_logger.addHandler(sh)

    charge_box_serial = sys.argv[1]
    rcv_ip = sys.argv[2]
    scharge_conn = SChargeConn(charge_box_serial, rcv_ip, scharge_logger)

    mqtt_logger = logging.getLogger("SCharge_mqtt")
    mqtt_logger.setLevel(logging.DEBUG)
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')

    fh = logging.FileHandler("/tmp/scharge-mqtt.log")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(formatter)
    mqtt_logger.addHandler(fh)

    sh = logging.StreamHandler()
    sh.setLevel(logging.INFO)
    sh.setFormatter(formatter)
    mqtt_logger.addHandler(sh)

    mqtt_server_address = sys.argv[3]
    mqtt_password = sys.argv[4]
    mqtt_user = mqtt_server_address.split("@")[0]
    mqtt_hostname = mqtt_server_address.split("@")[1].split(":")[0]
    mqtt_port = mqtt_server_address.split("@")[1].split(":")[1]
    mqtt_client = MQTTClient(mqtt_hostname, mqtt_port, mqtt_user, mqtt_password, scharge_conn, mqtt_logger)

    try:
        async def run_tasks():
            asyncio.create_task(scharge_conn.main())
            asyncio.create_task(mqtt_client.main())
            await asyncio.Future()
        asyncio.run(run_tasks())

    except (KeyboardInterrupt, asyncio.exceptions.CancelledError):
        mqtt_logger.info("Interrupted by user.")

    for handler in mqtt_logger.handlers:
        handler.close()
        mqtt_logger.removeFilter(handler)
