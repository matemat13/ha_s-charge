#!/usr/bin/env python3

import asyncio
import aiomqtt
import json

from scharge_server import *
from mqtt_managers import *

class MQTTClient:
    def __init__(self, hostname: str, port: str, username: str, password: str, scharge_conn: SChargeConn, logger: logging.Logger):
        self.hostname = hostname
        self.port = int(port)
        self.username = username
        self.password = password
        self.scharge_conn = scharge_conn
        self.logger = logger
        self.topic_mgrs = list()

        self.desired_current = 0

    async def main(self):
        self.logger.info(f"Starting MQTT client with hostname {self.hostname}:{self.port}, user: {self.username}, password: {self.password}.")
        async with aiomqtt.Client(hostname=self.hostname, port=self.port, username=self.username, password=self.password) as client:
            self.client = client
            # TODO: fix using Futures
            while not self.scharge_conn.charger_state.initialized():
                await asyncio.sleep(1)
            discovery_topic = f"homeassistant/device/scharge{self.scharge_conn.charge_box_serial}/config"

            self.topic_mgrs.append(
                    MQTTSwitchMgr(
                        name="charging",
                        human_name="Charging",
                        process_msg=self.process_switch_charging,
                        get_state=self.scharge_conn.charger_state.is_charging,
                        get_available=self.scharge_conn.charger_state.initialized)
                    )

            self.topic_mgrs.append(
                    MQTTNumberMgr(
                        name="set_current",
                        human_name="Set Current",
                        minimum=self.scharge_conn.charger_state.connectorMain.miniCurrent.value,
                        maximum=self.scharge_conn.charger_state.connectorMain.maxCurrent.value,
                        step=1,
                        process_msg=self.process_set_current,
                        get_state=self.scharge_conn.charger_state.is_charging,
                        get_available=self.scharge_conn.charger_state.initialized)
                    )

            self.topic_mgrs += self.scharge_conn.charger_state.register_mqtt_mgrs(self.publish)

            msg = self.generate_discovery_payload(self.scharge_conn)
            self.logger.info(f"Publishing discovery message to {discovery_topic}.")
            await self.publish(discovery_topic, msg)

            for mgr in self.topic_mgrs:
                if mgr.command_topic is not None:
                    await client.subscribe(mgr.command_topic)
                await self.publish(mgr.availability_topic, mgr.get_availability_msg())
                await self.publish(mgr.state_topic, mgr.get_state_msg())
            asyncio.create_task(self.availability_loop())
            # asyncio.create_task(self.state_loop(client))

            await client.subscribe("homeassistant/status")
            async for message in client.messages:
                self.logger.debug(f"{message.topic} << {message.payload}")
                for mgr in self.topic_mgrs:
                    if mgr.command_topic == str(message.topic):
                        await mgr.process_msg(mgr, message)

    async def availability_loop(self):
        while True:
            for mgr in self.topic_mgrs:
                await self.publish(mgr.availability_topic, mgr.get_availability_msg())
            await asyncio.sleep(3)

    async def process_switch_charging(self, mgr : MQTTSwitchMgr, msg: aiomqtt.Message):
        connectorId = 1
        if not self.scharge_conn.charger_state.connectorMain.is_connected() and self.scharge_conn.charger_state.connectorVice.is_connected():
            connectorId = 2

        if msg.payload == b"ON":
            self.logger.info(f"Starting charging from MQTT on connector {connectorId} with current {self.desired_current}A!")
            success = await self.scharge_conn.start_charging(self.desired_current, connectorId)
            if success:
                self.logger.info(f"Started charging!")
            else:
                self.logger.error(f"Failed to start charging!")
        else:
            self.logger.info(f"Stopping charging from MQTT on connector {connectorId}!")
            success = await self.scharge_conn.stop_charging(connectorId)
            if success:
                self.logger.info(f"Stopped charging!")
            else:
                self.logger.error(f"Failed to stop charging!")
        await self.publish(mgr.state_topic, mgr.get_state_msg())

    async def process_set_current(self, mgr : MQTTSwitchMgr, msg: aiomqtt.Message):
        self.desired_current = int(msg.payload)
        self.logger.info(f"Changed desired charging current to {self.desired_current}A.")
        await self.publish(mgr.state_topic, mgr.get_state_msg())

    async def publish(self, topic: str, message: str):
        self.logger.debug(f"{topic} >> {message}")
        await self.client.publish(topic, message)

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
