#!/usr/bin/env python3

from typing import Callable, List


class MQTTParamMgr:
    pass


class MQTTSwitchMgr(MQTTParamMgr):
    def __init__(self, name: str, human_name: str, process_msg: Callable, publish: Callable, get_state: Callable, get_available: Callable):
        self.name = name
        self.human_name = human_name
        self.process_msg = process_msg
        self.publish = publish
        self.get_state = get_state
        self.get_available = get_available

        self.state_topic = f"scharge/{self.name}/state"
        self.command_topic = f"scharge/{self.name}/set"
        self.availability_topic = f"scharge/{self.name}/available"

    def get_state_msg(self):
        if self.get_state():
            return "ON"
        else:
            return "OFF"

    async def publish_state(self):
        await self.publish(self.state_topic, self.get_state_msg())

    def get_availability_msg(self):
        if self.get_available():
            return "online"
        else:
            return "offline"

    def get_description(self):
        return (
                f"scharge_{self.name}",
                {
                    "p": "switch",
                    "name": f"{self.human_name}",
                    "unique_id": f"scharge_{self.name}",
                    "device_class": "switch",
                    "state_topic": self.state_topic,
                    "state_on": "ON",
                    "state_off": "OFF",
                    "command_topic": self.command_topic,
                    "payload_on": "ON",
                    "payload_off": "OFF",
                    "availability_topic": self.availability_topic,
                    "payload_available": "online",
                    "payload_not_available": "offline",
                    "availability_mode": "latest",
                    "optimistic": True,
                    "qos": 0,
                    "retain": False,
                }
               )


class MQTTNumberMgr(MQTTParamMgr):
    def __init__(self, name: str, human_name: str, minimum: float | int, maximum: float | int, step: float | int, process_msg: Callable, publish: Callable, get_state: Callable, get_available: Callable):
        self.name = name
        self.human_name = human_name
        self.minimum = minimum
        self.maximum = maximum
        self.step = step
        self.process_msg = process_msg
        self.publish = publish
        self.get_state = get_state
        self.get_available = get_available

        self.state_topic = f"scharge/{self.name}/state"
        self.command_topic = f"scharge/{self.name}/set"
        self.availability_topic = f"scharge/{self.name}/available"

    def get_state_msg(self):
        return self.get_state()

    async def publish_state(self):
        await self.publish(self.state_topic, self.get_state_msg())

    def get_availability_msg(self):
        if self.get_available():
            return "online"
        else:
            return "offline"

    def get_description(self):
        return (
                f"scharge_{self.name}",
                {
                    "p": "number",
                    "name": f"{self.human_name}",
                    "unique_id": f"scharge_{self.name}",
                    "entity_category": "config",
                    "device_class": "current",
                    "unit_of_measurement": "A",
                    "state_topic": self.state_topic,
                    "min": self.minimum,
                    "max": self.maximum,
                    "step": self.step,
                    "command_topic": self.command_topic,
                    "payload_reset": "reset",
                    "availability_topic": self.availability_topic,
                    "payload_available": "online",
                    "payload_not_available": "offline",
                    "availability_mode": "latest",
                    "optimistic": True,
                    "qos": 0,
                    "retain": True,
                }
               )


class MQTTNumberDiagMgr(MQTTParamMgr):
    def __init__(self, name: str, human_name: str, device_class: str, unit: str, publish: Callable, get_state: Callable, get_available: Callable):
        self.name = name
        self.human_name = human_name
        self.device_class = device_class
        self.unit = unit
        self.publish = publish
        self.get_state = get_state
        self.get_available = get_available

        self.state_topic = f"scharge/{self.name}/state"
        self.command_topic = f"scharge/{self.name}/set"
        self.availability_topic = f"scharge/{self.name}/available"

    async def publish_state(self):
        await self.publish(self.state_topic, self.get_state_msg())

    def get_state_msg(self):
        return self.get_state()

    def get_availability_msg(self):
        if self.get_available():
            return "online"
        else:
            return "offline"

    def get_description(self):
        return (
                f"scharge_{self.name}",
                {
                    "p": "sensor",
                    "name": f"{self.human_name}",
                    "unique_id": f"scharge_{self.name}",
                    "device_class": self.device_class,
                    "entity_category": "diagnostic",
                    "unit_of_measurement": self.unit,
                    "state_topic": self.state_topic,
                    "command_topic": self.command_topic,
                    "availability_topic": self.availability_topic,
                    "payload_available": "online",
                    "payload_not_available": "offline",
                    "availability_mode": "latest",
                    "expire_after": 10,
                    "qos": 0,
                }
               )


class MQTTEnumSensorMgr(MQTTParamMgr):
    def __init__(self, name: str, human_name: str, options: List[str], publish: Callable, get_state: Callable, get_available: Callable):
        self.name = name
        self.human_name = human_name
        self.device_class = "enum"
        self.options = options
        self.publish = publish
        self.get_state = get_state
        self.get_available = get_available

        self.state_topic = f"scharge/{self.name}/state"
        self.command_topic = None
        self.availability_topic = f"scharge/{self.name}/available"

    def get_state_msg(self):
        return self.get_state()

    async def publish_state(self):
        await self.publish(self.state_topic, self.get_state_msg())

    def get_availability_msg(self):
        if self.get_available():
            return "online"
        else:
            return "offline"

    def get_description(self):
        return (
                f"scharge_{self.name}",
                {
                    "p": "sensor",
                    "name": f"{self.human_name}",
                    "unique_id": f"scharge_{self.name}",
                    "device_class": self.device_class,
                    "options": self.options,
                    "state_topic": self.state_topic,
                    "availability_topic": self.availability_topic,
                    "payload_available": "online",
                    "payload_not_available": "offline",
                    "availability_mode": "latest",
                    "expire_after": 10,
                    "qos": 0,
                }
               )


class MQTTSensorMgr(MQTTParamMgr):
    def __init__(self, name: str, human_name: str, device_class: str, unit: str, publish: Callable, get_state: Callable, get_available: Callable, state_class: str = "measurement"):
        self.name = name
        self.human_name = human_name
        self.device_class = device_class
        self.state_class = state_class
        self.unit = unit
        self.publish = publish
        self.get_state = get_state
        self.get_available = get_available

        self.state_topic = f"scharge/{self.name}/state"
        self.command_topic = None
        self.availability_topic = f"scharge/{self.name}/available"

    async def publish_state(self):
        await self.publish(self.state_topic, self.get_state_msg())

    def get_state_msg(self):
        return self.get_state()

    def get_availability_msg(self):
        if self.get_available():
            return "online"
        else:
            return "offline"

    def get_description(self):
        device_name = f"scharge_{self.name}"
        desc = {
                    "p": "sensor",
                    "name": f"{self.human_name}",
                    "unique_id": f"scharge_{self.name}",
                    "state_class": self.state_class,
                    "unit_of_measurement": self.unit,
                    "state_topic": self.state_topic,
                    "availability_topic": self.availability_topic,
                    "payload_available": "online",
                    "payload_not_available": "offline",
                    "availability_mode": "latest",
                    "expire_after": 10,
                    "qos": 0,
                }
        if self.device_class != "":
            desc["device_class"] = self.device_class
        return (device_name, desc)


class MQTTBinarySensorMgr(MQTTParamMgr):
    def __init__(self, name: str, human_name: str, device_class: str, publish: Callable, get_state: Callable, get_available: Callable):
        self.name = name
        self.human_name = human_name
        self.device_class = device_class
        self.publish = publish
        self.get_state = get_state
        self.get_available = get_available

        self.state_topic = f"scharge/{self.name}/state"
        self.command_topic = None
        self.availability_topic = f"scharge/{self.name}/available"

    async def publish_state(self):
        await self.publish(self.state_topic, self.get_state_msg())

    def get_state_msg(self):
        if self.get_state():
            return "ON"
        else:
            return "OFF"

    def get_availability_msg(self):
        if self.get_available():
            return "online"
        else:
            return "offline"

    def get_description(self):
        return (
                f"scharge_{self.name}",
                {
                    "p": "binary_sensor",
                    "name": f"{self.human_name}",
                    "unique_id": f"scharge_{self.name}",
                    "device_class": self.device_class,
                    "state_topic": self.state_topic,
                    "payload_on": "ON",
                    "payload_off": "OFF",
                    "availability_topic": self.availability_topic,
                    "payload_available": "online",
                    "payload_not_available": "offline",
                    "availability_mode": "latest",
                    "expire_after": 10,
                    "qos": 0,
                }
               )
