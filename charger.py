#!/usr/bin/env python3
from messages_rx import *

class Charger:
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

        def update(self, message, meterInfo_data):
            if type(message) == SynchroData:
                self.voltage = meterInfo_data["voltage"]
                self.current = meterInfo_data["current"]
                self.power = meterInfo_data["power"]

    chargeBoxSN = None

    connectorMain = Connector()
    connectorVice = Connector()

    # loaded from the DeviceData message
    sVersion = None
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

    def update(self, message):
        # ignore data for other chargers
        if self.chargeBoxSN != message.payload_data["chargeBoxSN"]:
            return

        if type(message) == DeviceData:
            self.connectorMain.update(message, message.payload_data["connectorMain"])
            self.connectorVice.update(message, message.payload_data["connectorVice"])

            self.sVersion = message.payload_data["sVersion"]
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
