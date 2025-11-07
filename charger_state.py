#!/usr/bin/env python3
from messages_rx import *
from typing import Type, Callable

from mqtt_managers import *

class ChargerParam:
    def __init__(self, human_name : str, value_type: Type, parse_message_type : Type[PayloadMsg], parse_json_key : str, ha_topic : str, unit : str = "", device_type: str = "", transform : Callable = lambda x : x):
        self.human_name = human_name
        self.human_name_colon = self.human_name + ":"
        self.parse_message_type = parse_message_type
        self.parse_json_key = parse_json_key
        self.ha_topic = ha_topic
        self.unit = unit
        self.transform = transform
        self.value = None
        self.value_type = value_type
        self.device_type = device_type
        self.cbk_on_update = None

    async def update(self, message, payload_data = None):
        if type(message) == self.parse_message_type:
            if payload_data is None:
                self.value = self.transform(self.value_type(message.payload_data[self.parse_json_key]))
            else:
                self.value = self.transform(self.value_type(payload_data[self.parse_json_key]))

            if self.cbk_on_update is not None:
                await self.cbk_on_update(self.value)

    def __format__(self, format_spec):
        return f"{self.human_name_colon:{format_spec}}{self.value}{self.unit}"

    def initialized(self):
        return self.value is not None

    def get(self):
        return self.value

    def register_mqtt_mgrs(self, f_publish, f_initialized):
        if self.device_type is not None and (self.value_type == int or self.value_type == float):
            ret = MQTTSensorMgr(
                        name=self.ha_topic,
                        human_name=self.human_name,
                        device_class=self.device_type,
                        unit=self.unit,
                        publish=f_publish,
                        get_value=self.get,
                        get_available=f_initialized
                        )
            self.cbk_on_update = ret.publish_state
            return [ret]
        else:
            return []


class ChargerState:

    class Connector:

        def __init__(self, connectorName, connector_human_name):
            self.connectorName = connectorName
            self.connector_human_name = connector_human_name

            # loaded from the DeviceData message
            self.miniCurrent = ChargerParam(
                    f"{self.connector_human_name} Minimal Current",
                    value_type=int,
                    device_type="current",
                    unit="A",
                    parse_message_type=DeviceData,
                    parse_json_key="miniCurrent",
                    ha_topic=f"{self.connectorName}/minimal_current"
                    )
            self.maxCurrent = ChargerParam(
                    f"{self.connector_human_name} Maximal Current",
                    value_type=int,
                    device_type="current",
                    unit="A",
                    parse_message_type=DeviceData,
                    parse_json_key="maxCurrent",
                    ha_topic=f"{self.connectorName}/maximal_current"
                    )
            self.connectorStatus = ChargerParam(
                    f"{self.connector_human_name} Connector Status",
                    value_type=int,
                    parse_message_type=DeviceData,
                    parse_json_key="connectorStatus",
                    ha_topic=f"{self.connectorName}/connector_status"
                    )
            self.lockStatus = ChargerParam(
                    f"{self.connector_human_name} Lock Status",
                    value_type=bool,
                    parse_message_type=DeviceData,
                    parse_json_key="lockStatus",
                    ha_topic=f"{self.connectorName}/lock_status"
                    )
            self.PncStatus = ChargerParam(
                    f"{self.connector_human_name} Plug&Charge Status",
                    value_type=bool,
                    parse_message_type=DeviceData,
                    parse_json_key="PncStatus",
                    ha_topic=f"{self.connectorName}/pnc_status"
                    )

            # loaded from the SynchroStatus message
            self.connectionStatus = ChargerParam(
                    f"{self.connector_human_name} Connection Status",
                    value_type=bool,
                    parse_message_type=SynchroStatus,
                    parse_json_key="connectionStatus",
                    ha_topic=f"{self.connectorName}/connection_status"
                    )
            self.statusCode = ChargerParam(
                    f"{self.connector_human_name} Status Code",
                    value_type=int,
                    parse_message_type=SynchroStatus,
                    parse_json_key="statusCode",
                    ha_topic=f"{self.connectorName}/status_code"
                    )
            self.chargeStatus = ChargerParam(
                    f"{self.connector_human_name} Charging Status",
                    value_type=str,
                    parse_message_type=SynchroStatus,
                    parse_json_key="chargeStatus",
                    ha_topic=f"{self.connectorName}/charge_status"
                    )
            self.startTime = ChargerParam(
                    f"{self.connector_human_name} Charging Start Time",
                    value_type=str,
                    parse_message_type=SynchroStatus,
                    parse_json_key="startTime",
                    ha_topic=f"{self.connectorName}/charge_start_time"
                    )
            self.endTime = ChargerParam(
                    f"{self.connector_human_name} Charging End Time",
                    value_type=str,
                    parse_message_type=SynchroStatus,
                    parse_json_key="endTime",
                    ha_topic=f"{self.connectorName}/charge_end_time"
                    )
            self.reserveCurrent = ChargerParam(
                    f"{self.connector_human_name} Reserved Current",
                    value_type=int,
                    device_type="current",
                    unit="A",
                    parse_message_type=SynchroStatus,
                    parse_json_key="reserveCurrent",
                    ha_topic=f"{self.connectorName}/charge_reserved_current",
                    )

            # loaded from the SynchroData message
            self.voltage = ChargerParam(
                    f"{self.connector_human_name} Voltage",
                    value_type=float,
                    device_type="voltage",
                    unit="V",
                    parse_message_type=SynchroData,
                    parse_json_key="voltage",
                    ha_topic=f"{self.connectorName}.charge_voltage"
                    )
            self.current = ChargerParam(
                    f"{self.connector_human_name} Current",
                    value_type=float,
                    device_type="current",
                    unit="A",
                    parse_message_type=SynchroData,
                    parse_json_key="current",
                    ha_topic=f"{self.connectorName}.charge_current")
            self.power = ChargerParam(
                    f"{self.connector_human_name} Power",
                    value_type=float,
                    device_type="power",
                    unit="kW",
                    parse_message_type=SynchroData,
                    parse_json_key="power",
                    ha_topic=f"{self.connectorName}.charge_power"
                    )
            self.electricWork = ChargerParam(
                    f"{self.connector_human_name} Charged Energy",
                    value_type=float,
                    device_type="energy",
                    unit="kWh",
                    parse_message_type=SynchroData,
                    parse_json_key="electricWork",
                    ha_topic=f"{self.connectorName}.charge_energy"
                    )
            self.chargingTime = ChargerParam(
                    f"{self.connector_human_name} Charging Duration",
                    value_type=str,
                    parse_message_type=SynchroData,
                    parse_json_key="chargingTime",
                    ha_topic=f"{self.connectorName}.charge_duration"
                    )

            self.params = [
                            self.miniCurrent,
                            self.maxCurrent,
                            self.connectorStatus,
                            self.lockStatus,
                            self.PncStatus,
                            self.connectionStatus,
                            self.statusCode,
                            self.chargeStatus,
                            self.startTime,
                            self.endTime,
                            self.voltage,
                            self.current,
                            self.reserveCurrent,
                            self.power,
                            self.electricWork,
                            self.chargingTime,
                          ]

        def __format__(self, format_spec):
            ret = f"{self.connectorName}:\n"
            for param in self.params:
                ret += f"{param:{format_spec}}\n"
            return ret

        async def update(self, message):
            if type(message) == DeviceData or type(message) == SynchroStatus or type(message) == SynchroData:
                connector_data = message.payload_data[self.connectorName]
                for param in self.params:
                    await param.update(message, connector_data)

        def initialized(self):
            return all(x.initialized() for x in self.params)

        def is_connected(self):
            return self.connectionStatus.value

        def is_charging(self):
            return self.chargeStatus.value == "charging" or self.chargeStatus.value == "wait"

        def register_mqtt_mgrs(self, f_publish, f_initialized):
            ret: list[MQTTSensorMgr] = []
            for param in self.params:
                ret += param.register_mqtt_mgrs(f_publish=f_publish, f_initialized=f_initialized)
            return ret

    class MeterInfo:

        def __init__(self):
            self.voltage = ChargerParam("voltage", value_type=float, parse_message_type=SynchroData, parse_json_key="voltage", ha_topic=f"voltage", unit="V")
            self.current = ChargerParam("current", value_type=float, parse_message_type=SynchroData, parse_json_key="current", ha_topic=f"current", unit="A")
            self.power = ChargerParam("power", value_type=float, parse_message_type=SynchroData, parse_json_key="power", ha_topic=f"power", unit="kW")

            self.params = [
                            self.voltage,
                            self.current,
                            self.power,
                          ]

        def __format__(self, format_spec):
            ret = f"Meter info:\n"
            for param in self.params:
                ret += f"{param:{format_spec}}\n"
            return ret

        async def update(self, message):
            if type(message) == SynchroData:
                meterInfo_data = message.payload_data["meterInfo"]
                for param in self.params:
                    await param.update(message, meterInfo_data)

        def initialized(self):
            return all(x.initialized() for x in self.params)

        def register_mqtt_mgrs(self, f_publish, f_initialized):
            ret: list[MQTTSensorMgr] = []
            for param in self.params:
                ret += param.register_mqtt_mgrs(f_publish=f_publish, f_initialized=f_initialized)
            return ret

    def __init__(self, chargeBoxSN):
        self.chargeBoxSN = chargeBoxSN

        self.connectorMain = ChargerState.Connector("connectorMain", "C1")
        self.connectorVice = ChargerState.Connector("connectorVice", "C2")
        self.connectors = [self.connectorMain, self.connectorVice]

        # loaded from the DeviceData message
        self.sVersion = ChargerParam("software version", value_type=str, parse_message_type=DeviceData, parse_json_key="sVersion", ha_topic="software_vesion")
        self.hVersion = ChargerParam("hardware version", value_type=str, parse_message_type=DeviceData, parse_json_key="hVersion", ha_topic="hardware_vesion")
        self.chargeTimes = ChargerParam("number of charges", value_type=int, parse_message_type=DeviceData, parse_json_key="chargeTimes", ha_topic="number_of_charges")
        self.cumulativeTime = ChargerParam("cumulative charge duration", value_type=int, parse_message_type=DeviceData, parse_json_key="cumulativeTime", ha_topic="cumulative_charge_duration", unit="h", transform=lambda x : x / (1e3 * 60 * 60))
        self.totalPower = ChargerParam("total power", value_type=int, parse_message_type=DeviceData, parse_json_key="totalPower", ha_topic="total_power", unit="?")
        self.rssi = ChargerParam("connection RSSI", value_type=int, parse_message_type=DeviceData, parse_json_key="rssi", ha_topic="connection_rssi", unit="dB")
        self.evseType = ChargerParam("EVSE type", value_type=str, parse_message_type=DeviceData, parse_json_key="evseType", ha_topic="evse_type")
        self.evsePhase = ChargerParam("EVSE number of phases", value_type=str, parse_message_type=DeviceData, parse_json_key="evsePhase", ha_topic="evse_number_of_phases")
        self.loadbalance = ChargerParam("load balancing", value_type=int, parse_message_type=DeviceData, parse_json_key="loadbalance", ha_topic="load_balancing")
        self.isHasLock = ChargerParam("has locking", value_type=bool, parse_message_type=DeviceData, parse_json_key="isHasLock", ha_topic="has_locking")
        self.isHasMeter = ChargerParam("has meter", value_type=bool, parse_message_type=DeviceData, parse_json_key="isHasMeter", ha_topic="has_meter")
        self.connectorNumber = ChargerParam("number of connectors", value_type=int, parse_message_type=DeviceData, parse_json_key="connectorNumber", ha_topic="number_of_connectors")

        # loaded from the NWireToDics message
        self.NWireExist = ChargerParam("NWire exists", value_type=bool, parse_message_type=NWireToDics, parse_json_key="NWireExist", ha_topic="nwire_exists")
        self.NWireClosed = ChargerParam("NWire closed", value_type=bool, parse_message_type=NWireToDics, parse_json_key="NWireClosed", ha_topic="nwire_closed")

        # loaded from the SynchroData message
        self.meterInfo = ChargerState.MeterInfo()

        self.params = [
                    self.sVersion,
                    self.hVersion,
                    self.chargeTimes,
                    self.cumulativeTime,
                    self.totalPower,
                    self.rssi,
                    self.evseType,
                    self.evsePhase,
                    self.isHasLock,
                    self.isHasMeter,
                    self.loadbalance,
                    self.NWireExist,
                    self.NWireClosed,
                    self.connectorNumber,
                    self.connectorMain,
                    self.connectorVice,
                    self.meterInfo,
                ]

    def __str__(self):
        initialized_txt =  "not initialized"
        if self.initialized():
            initialized_txt = "initialized"
        ret = f"Charger SN{self.chargeBoxSN} {initialized_txt}\n"
        for param in self.params:
            ret += f"{param:<31}\n"
        return ret

    async def update(self, message):
        # ignore data for other chargers
        if self.chargeBoxSN != message.payload_data["chargeBoxSN"]:
            return

        for param in self.params:
            await param.update(message)

    def initialized(self):
        return all(x.initialized() for x in self.params)

    def is_charging(self):
        return any(conn.is_charging() for conn in self.connectors)

    def get_current(self, connectorId = None):

        if connectorId is None:
            for it in range(len(self.connectors)):
                if self.connectors[it].is_charging():
                    connectorId = it+1

        if connectorId is None:
            connectorId = 1

        return self.connectors[connectorId-1].current.value

    def register_mqtt_mgrs(self, f_publish):
        ret: list[MQTTSensorMgr] = []
        for param in self.params:
            ret += param.register_mqtt_mgrs(f_publish=f_publish, f_initialized=self.initialized)
        return ret
