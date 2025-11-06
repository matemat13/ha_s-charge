#!/usr/bin/env python3

import asyncio
import aiomqtt
import json

from scharge_server import *

class MQTTSwitchMgr:
    def __init__(self, name: str, human_name: str, mqtt_client: aiomqtt.Client, switch_method, availability):
        self.name = name
        self.human_name = human_name
        self.switch_method = switch_method
        self.availability = availability
        self.mqtt_client = mqtt_client

        self.state_topic = f"scharge/{self.name}/state"
        self.command_topic = f"scharge/{self.name}/set"
        self.availability_topic = f"scharge/{self.name}/available"

    def get_availability_msg(self):
        if self.availability:
            return json.dumps("ON")
        else:
            return json.dumps("OFF")

    def get_description(self):
        return (
                f"scharge_{self.name}",
                {
                    "p": "switch",
                    "name": f"{self.human_name}",
                    "unique_id": f"scharge_{self.name}",
                    "device_class": "switch",
                    "state_topic": self.state_topic,
                    "command_topic": self.command_topic,
                    "availability":
                    {
                      "topic": self.availability_topic,
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
                }
               )

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

            self.topic_mgrs.append(MQTTSwitchMgr("charging", "Charging", client, self.switch_charging, True))

            msg = self.generate_discovery_payload(self.scharge_conn)
            self.logger.info(f"Publishing discovery message {msg}")
            await client.publish(discovery_topic, msg)

            for mgr in self.topic_mgrs:
                await client.publish(mgr.availability_topic, mgr.get_availability_msg())

            await client.subscribe("homeassistant/status")
            async for message in client.messages:
                self.logger.info(message.payload)
                for mgr in self.topic_mgrs:
                    if mgr.command_topic == message.topic:
                        mgr.switch_method(message)

    async def switch_charging(self, msg: aiomqtt.Message):
        connectorId = 2
        if msg.payload == "ON":
            await self.scharge_conn.start_charging(6, connectorId)
        else:
            await self.scharge_conn.stop_charging(connectorId)

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
              },
              "state_topic": "scharge/state",
              "qos": 2
            }

        for mgr in self.topic_mgrs:
            cmp_name, cmp_desc = mgr.get_description()
            ret["cmps"][cmp_name] = cmp_desc

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
