#!/usr/bin/env python3
from messages_rx import *
from typing import Type, Callable

class ChargerParam:
    def __init__(self, human_name : str, parse_message_type : Type[PayloadMsg], parse_json_key : str, ha_topic : str, unit : str = "", transform : Callable = lambda x : x):
        self.human_name = human_name
        self.human_name_colon = self.human_name + ":"
        self.parse_message_type = parse_message_type
        self.parse_json_key = parse_json_key
        self.ha_topic = ha_topic
        self.unit = unit
        self.transform = transform
        self.value = None

    def update(self, message, payload_data = None):
        if type(message) == self.parse_message_type:
            if payload_data is None:
                self.value = self.transform(message.payload_data[self.parse_json_key])
            else:
                self.value = self.transform(payload_data[self.parse_json_key])

    def __format__(self, format_spec):
        return f"{self.human_name_colon:{format_spec}}{self.value}{self.unit}"

class Charger:

    class Connector:

        def __init__(self, connectorName):
            self.connectorName = connectorName

            # loaded from the DeviceData message
            self.miniCurrent = ChargerParam("minimal current", parse_message_type=DeviceData, parse_json_key="miniCurrent", ha_topic=f"{self.connectorName}.minimal_current")
            self.maxCurrent = ChargerParam("maximal current", parse_message_type=DeviceData, parse_json_key="maxCurrent", ha_topic=f"{self.connectorName}.maximal_current")
            self.connectorStatus = ChargerParam("connector status", parse_message_type=DeviceData, parse_json_key="connectorStatus", ha_topic=f"{self.connectorName}.connector_status")
            self.lockStatus = ChargerParam("lock status", parse_message_type=DeviceData, parse_json_key="lockStatus", ha_topic=f"{self.connectorName}.lock_status")
            self.PncStatus = ChargerParam("Plug&Charge status", parse_message_type=DeviceData, parse_json_key="PncStatus", ha_topic=f"{self.connectorName}.pnc_status")

            # loaded from the SynchroStatus message
            self.connectionStatus = ChargerParam("connection status", parse_message_type=SynchroStatus, parse_json_key="connectionStatus", ha_topic=f"{self.connectorName}.connection_status")
            self.statusCode = ChargerParam("status code", parse_message_type=SynchroStatus, parse_json_key="statusCode", ha_topic=f"{self.connectorName}.status_code")
            self.chargeStatus = ChargerParam("charge status", parse_message_type=SynchroStatus, parse_json_key="chargeStatus", ha_topic=f"{self.connectorName}.charge_status")
            self.startTime = ChargerParam("charge start time", parse_message_type=SynchroStatus, parse_json_key="startTime", ha_topic=f"{self.connectorName}.charge_start_time")
            self.endTime = ChargerParam("charge end time", parse_message_type=SynchroStatus, parse_json_key="endTime", ha_topic=f"{self.connectorName}.charge_end_time")
            self.reserveCurrent = ChargerParam("charge reserved current", parse_message_type=SynchroStatus, parse_json_key="reserveCurrent", ha_topic=f"{self.connectorName}.charge_reserved_current", unit="A")

            # loaded from the SynchroData message
            self.voltage = ChargerParam("charge voltage", parse_message_type=SynchroData, parse_json_key="voltage", ha_topic=f"{self.connectorName}.charge_voltage", unit="V")
            self.current = ChargerParam("charge current", parse_message_type=SynchroData, parse_json_key="current", ha_topic=f"{self.connectorName}.charge_current", unit="A")
            self.power = ChargerParam("charge power", parse_message_type=SynchroData, parse_json_key="power", ha_topic=f"{self.connectorName}.charge_power", unit="kW")
            self.electricWork = ChargerParam("charge energy", parse_message_type=SynchroData, parse_json_key="electricWork", ha_topic=f"{self.connectorName}.charge_energy", unit="kWh")
            self.chargingTime = ChargerParam("charge duration", parse_message_type=SynchroData, parse_json_key="chargingTime", ha_topic=f"{self.connectorName}.charge_duration")

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

        def __str__(self):
            ret = ""
            for param in self.params:
                ret += f"{param:<31}\n"
            return ret

        def update(self, message):
            if type(message) == DeviceData or type(message) == SynchroStatus or type(message) == SynchroData:
                connector_data = message.payload_data[self.connectorName]
                for param in self.params:
                    param.update(message, connector_data)

    class MeterInfo:

        def __init__(self):
            self.voltage = ChargerParam("voltage", parse_message_type=SynchroData, parse_json_key="voltage", ha_topic=f"voltage", unit="V")
            self.current = ChargerParam("current", parse_message_type=SynchroData, parse_json_key="current", ha_topic=f"current", unit="A")
            self.power = ChargerParam("power", parse_message_type=SynchroData, parse_json_key="power", ha_topic=f"power", unit="kW")

            self.params = [
                            self.voltage,
                            self.current,
                            self.power,
                          ]

        def __str__(self):
            ret = ""
            for param in self.params:
                ret += f"{param:<31}\n"
            return ret

        def update(self, message):
            if type(message) == SynchroData:
                meterInfo_data = message.payload_data["meterInfo"]
                for param in self.params:
                    param.update(message, meterInfo_data)

    def __init__(self, chargeBoxSN):
        self.chargeBoxSN = chargeBoxSN

        self.connectorMain = Charger.Connector("connectorMain")
        self.connectorVice = Charger.Connector("connectorVice")

        # loaded from the DeviceData message
        self.sVersion = ChargerParam("software version", parse_message_type=DeviceData, parse_json_key="sVersion", ha_topic="software_vesion")
        self.hVersion = ChargerParam("hardware version", parse_message_type=DeviceData, parse_json_key="hVersion", ha_topic="hardware_vesion")
        self.chargeTimes = ChargerParam("number of charges", parse_message_type=DeviceData, parse_json_key="chargeTimes", ha_topic="number_of_charges")
        self.cumulativeTime = ChargerParam("cumulative charge duration", parse_message_type=DeviceData, parse_json_key="cumulativeTime", ha_topic="cumulative_charge_duration", unit="h", transform=lambda x : x / (1e3 * 60 * 60))
        self.totalPower = ChargerParam("total power", parse_message_type=DeviceData, parse_json_key="totalPower", ha_topic="total_power", unit="?")
        self.rssi = ChargerParam("connection RSSI", parse_message_type=DeviceData, parse_json_key="rssi", ha_topic="connection_rssi", unit="dB")
        self.evseType = ChargerParam("EVSE type", parse_message_type=DeviceData, parse_json_key="evseType", ha_topic="evse_type")
        self.evsePhase = ChargerParam("EVSE number of phases", parse_message_type=DeviceData, parse_json_key="evsePhase", ha_topic="evse_number_of_phases")
        self.loadbalance = ChargerParam("load balancing", parse_message_type=DeviceData, parse_json_key="loadbalance", ha_topic="load_balancing")
        self.isHasLock = ChargerParam("has locking", parse_message_type=DeviceData, parse_json_key="isHasLock", ha_topic="has_locking")
        self.isHasMeter = ChargerParam("has meter", parse_message_type=DeviceData, parse_json_key="isHasMeter", ha_topic="has_meter")
        self.connectorNumber = ChargerParam("number of connectors", parse_message_type=DeviceData, parse_json_key="connectorNumber", ha_topic="number_of_connectors")

        # loaded from the NWireToDics message
        self.NWireExist = ChargerParam("NWire exists", parse_message_type=NWireToDics, parse_json_key="NWireExist", ha_topic="nwire_exists")
        self.NWireClosed = ChargerParam("NWire closed", parse_message_type=NWireToDics, parse_json_key="NWireClosed", ha_topic="nwire_closed")

        # loaded from the SynchroData message
        self.meterInfo = Charger.MeterInfo()

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
        return f"Charger SN{self.chargeBoxSN}\n" \
               f"{self.sVersion:<31}\n" \
               f"{self.hVersion:<31}\n" \
               f"{self.chargeTimes:<31}\n" \
               f"{self.cumulativeTime:<31}\n" \
               f"{self.totalPower:<31}\n" \
               f"{self.rssi:<31}\n" \
               f"{self.evseType:<31}\n" \
               f"{self.evsePhase:<31}\n" \
               f"{self.connectorNumber:<31}\n" \
               f"{self.loadbalance:<31}\n" \
               f"{self.isHasLock:<31}\n" \
               f"{self.isHasMeter:<31}\n" \
               f"{self.NWireExist:<31}\n" \
               f"{self.NWireClosed:<31}\n\n" \
               f"Main connector:\n" \
               f"{self.connectorMain}\n" \
               f"Vice connector:\n" \
               f"{self.connectorVice}\n" \
               f"Meter info:\n" \
               f"{self.meterInfo}\n"

    def update(self, message):
        # ignore data for other chargers
        if self.chargeBoxSN != message.payload_data["chargeBoxSN"]:
            return

        for param in self.params:
            param.update(message)
