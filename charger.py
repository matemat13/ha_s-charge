#!/usr/bin/env python3
from messages_rx import *
from typing import Type

class Charger:
    class Param:
        def __init__(self, human_name : str, parse_message_type : Type[PayloadMsg], parse_json_key : str, unit : str, ha_topic : str):
            self.human_name = human_name
            self.human_name_colon = self.human_name + ":"
            self.parse_message_type = parse_message_type
            self.parse_json_key = parse_json_key
            self.unit = unit
            self.ha_topic = ha_topic
            self.value = None

        def update(self, parse_message):
            self.value = parse_message.payload_data[self.parse_json_key]

        def __format__(self, format_spec):
            return f"{self.human_name_colon:{format_spec}}{self.value}{self.unit}"

    class Connector:
        # loaded from the DeviceData message
        miniCurrent = None
        maxCurrent = None
        connectorStatus = None
        lockStatus = None
        PncStatus = None

        # loaded from the SynchroStatus message
        connectionStatus = None
        chargeStatus = None
        statusCode = None
        startTime = None
        endTime = None
        reserveCurrent = None

        # loaded from the SynchroData message
        voltage = None
        current = None
        power = None
        electricWork = None
        chargingTime = None

        def __str__(self):
            return f"connector status:          {self.connectorStatus}\n" \
                   f"minimal current:           {self.miniCurrent}\n" \
                   f"maximal current:           {self.maxCurrent}\n" \
                   f"lock status:               {self.lockStatus}\n" \
                   f"PNC status:                {self.PncStatus}\n" \
                   f"connection status:         {self.connectionStatus}\n" \
                   f"status code:               {self.statusCode}\n" \
                   f"charge status:             {self.chargeStatus}\n" \
                   f"charge start time:         {self.startTime}\n" \
                   f"charge end time:           {self.endTime}\n" \
                   f"charge reserved current:   {self.reserveCurrent}A\n" \
                   f"charge voltage:            {self.voltage}V\n" \
                   f"charge current:            {self.current}A\n" \
                   f"charge power:              {self.power}kW\n" \
                   f"charge energy:             {self.electricWork}kWh\n" \
                   f"charge duration:           {self.chargingTime}\n"

        def update(self, message, connector_data):
            if type(message) == DeviceData:
                self.miniCurrent = connector_data["miniCurrent"]
                self.maxCurrent = connector_data["maxCurrent"]
                self.connectorStatus = connector_data["connectorStatus"]
                self.lockStatus = connector_data["lockStatus"]
                self.PncStatus = connector_data["PncStatus"]

            elif type(message) == SynchroStatus:
                self.connectionStatus = connector_data["connectionStatus"]
                self.chargeStatus = connector_data["chargeStatus"]
                self.statusCode = connector_data["statusCode"]
                self.startTime = connector_data["startTime"]
                self.endTime = connector_data["endTime"]
                self.reserveCurrent = connector_data["reserveCurrent"]

            elif type(message) == SynchroData:
                self.voltage = connector_data["voltage"]
                self.current = connector_data["current"]
                self.power = connector_data["power"]
                self.electricWork = connector_data["electricWork"]
                self.chargingTime = connector_data["chargingTime"]

    class MeterInfo:
        voltage = None
        current = None
        power = None

        def __str__(self):
            return f"voltage:   {self.voltage}V\n" \
                   f"current:   {self.current}A\n" \
                   f"power:     {self.power}kW\n"

        def update(self, message, meterInfo_data):
            if type(message) == SynchroData:
                self.voltage = meterInfo_data["voltage"]
                self.current = meterInfo_data["current"]
                self.power = meterInfo_data["power"]

    chargeBoxSN = None

    connectorMain = Connector()
    connectorVice = Connector()

    # loaded from the DeviceData message
    sVersion = Param("software version", parse_message_type=DeviceData, parse_json_key="sVersion", unit="", ha_topic="software_vesion")
    hVersion = None
    loadbalance = None
    chargeTimes = None
    cumulativeTime = None
    totalPower = None
    rssi = None
    evseType = None
    connectorNumber = None
    evsePhase = None
    isHasLock = None
    isHasMeter = None

    # loaded from the SynchroData message
    meterInfo = MeterInfo()

    # loaded from the NWireToDics message
    NWireExist = None
    NWireClosed = None

    def __init__(self, chargeBoxSN):
        self.chargeBoxSN = chargeBoxSN

    def __str__(self):
        return f"Charger SN{self.chargeBoxSN}\n" \
               f"hardware version:              {self.hVersion}\n" \
               f"{self.sVersion:<31}\n" \
               f"number of charges:             {self.chargeTimes}\n" \
               f"cumulative charge duration:    {self.cumulativeTime}\n" \
               f"total power:                   {self.totalPower}kW\n" \
               f"connection RSSI:               {self.rssi}dB\n" \
               f"EV SE type:                    {self.evseType}\n" \
               f"EV SE phase:                   {self.evsePhase}\n" \
               f"number of connectors:          {self.connectorNumber}\n" \
               f"has load balancing:            {self.loadbalance}\n" \
               f"has locking:                   {self.isHasLock}\n" \
               f"has a meter:                   {self.isHasMeter}\n" \
               f"NWire exists:                  {self.NWireExist}\n" \
               f"NWire closed:                  {self.NWireClosed}\n\n" \
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

        if type(message) == DeviceData:
            self.connectorMain.update(message, message.payload_data["connectorMain"])
            self.connectorVice.update(message, message.payload_data["connectorVice"])

            self.sVersion.update(message)
            self.hVersion = message.payload_data["hVersion"]
            self.loadbalance = message.payload_data["loadbalance"]
            self.chargeTimes = message.payload_data["chargeTimes"]
            self.cumulativeTime = message.payload_data["cumulativeTime"]
            self.totalPower = message.payload_data["totalPower"]
            self.rssi = message.payload_data["rssi"]
            self.evseType = message.payload_data["evseType"]
            self.connectorNumber = message.payload_data["connectorNumber"]
            self.evsePhase = message.payload_data["evsePhase"]
            self.isHasLock = message.payload_data["isHasLock"]
            self.isHasMeter = message.payload_data["isHasMeter"]
            print(f"Charger {self.chargeBoxSN} device data updated")

        elif type(message) == SynchroStatus:
            self.connectorMain.update(message, message.payload_data["connectorMain"])
            self.connectorVice.update(message, message.payload_data["connectorVice"])
            print(f"Charger {self.chargeBoxSN} charging status updated")

        elif type(message) == SynchroData:
            self.connectorMain.update(message, message.payload_data["connectorMain"])
            self.connectorVice.update(message, message.payload_data["connectorVice"])
            self.meterInfo.update(message, message.payload_data["meterInfo"])
            print(f"Charger {self.chargeBoxSN} charging data updated")

        elif type(message) == NWireToDics:
            self.NWireExist = message.payload_data["NWireExist"]
            self.NWireClosed = message.payload_data["NWireClosed"]
            print(f"Charger {self.chargeBoxSN} NWire data updated")
