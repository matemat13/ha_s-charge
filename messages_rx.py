#!/usr/bin/env python3
import json
from copy import deepcopy
from collections.abc import Iterable

class PayloadMsg:
    action = ""
    payload_template = {}

    def parse_template(self, payload, payload_template):
        payload_data = deepcopy(payload_template)
        for key in payload_template:
            if key not in payload:
                raise ValueError(f"Failed to parse expected key {key} from payload {payload} (does not exist)!")

            val = payload[key]

            if type(val) in (int, float, str, bool):
                if not type(val) == payload_template[key]:
                    raise ValueError(f"Failed to parse expected key {key} from payload {payload} (wrong type {type(val)}, expected {payload_template[key]})!")
                payload_data[key] = payload[key]

            else:
                payload_data[key] = self.parse_template(val, payload_template[key])
        return payload_data

    def __init__(self, payload):
        self.payload_data = self.parse_template(payload, self.payload_template)


# {"messageTypeId":"5","uniqueId":"3718","action":"DeviceData","payload":{"chargeBoxSN":"X","connectorMain":{"miniCurrent":6,"maxCurrent":32,"connectorStatus":0,"lockStatus":false,"PncStatus":true},"connectorVice":{"miniCurrent":6,"maxCurrent":32,"connectorStatus":0,"lockStatus":false,"PncStatus":true},"sVersion":"E3P3_H_1.1.1_R5190","hVersion":"E3P3_V1.00","loadbalance":10000,"chargeTimes":26,"cumulativeTime":71584018,"totalPower":20403,"rssi":-55,"evseType":"EU","connectorNumber":2,"evsePhase":"threephase","isHasLock":true,"isHasMeter":true}}
class DeviceData(PayloadMsg):
    action = "DeviceData"
    payload_template =  {
                           "chargeBoxSN": str,
                           "connectorMain":
                           {
                               "miniCurrent": int,
                               "maxCurrent": int,
                               "connectorStatus": int,
                               "lockStatus": bool,
                               "PncStatus": bool
                           },
                           "connectorVice":
                           {
                               "miniCurrent": int,
                               "maxCurrent": int,
                               "connectorStatus": int,
                               "lockStatus": bool,
                               "PncStatus": bool
                           },
                           "sVersion": str,
                           "hVersion": str,
                           "loadbalance": int,
                           "chargeTimes": int,
                           "cumulativeTime": int,
                           "totalPower": int,
                           "rssi": int,
                           "evseType": str,
                           "connectorNumber": int,
                           "evsePhase": str,
                           "isHasLock": bool,
                           "isHasMeter": bool
                        }

# {"messageTypeId":"5","uniqueId":"3719","action":"SynchroStatus","payload":{"chargeBoxSN":"X","connectorMain":{"connectionStatus":false,"chargeStatus":"idle","statusCode":0,"startTime":"-","endTime":"-","reserveCurrent":0},"connectorVice":{"connectionStatus":false,"chargeStatus":"idle","statusCode":0,"startTime":"-","endTime":"-","reserveCurrent":0}}}
class SynchroStatus(PayloadMsg):
    action = "SynchroStatus"
    payload_template =  {
                            "chargeBoxSN": str,
                            "connectorMain":
                            {
                                "connectionStatus": bool,
                                "chargeStatus": str,
                                "statusCode": int,
                                "startTime": str,
                                "endTime": str,
                                "reserveCurrent": int
                            },
                            "connectorVice":
                            {
                                "connectionStatus": bool,
                                "chargeStatus": str,
                                "statusCode": int,
                                "startTime": str,
                                "endTime": str,
                                "reserveCurrent": int
                            }
                        }

# {"messageTypeId":"5","uniqueId":"3720","action":"SynchroData","payload":{"chargeBoxSN":"X","connectorMain":{"voltage":"405.92","current":"0.00","power":"0.00","electricWork":"0.00","chargingTime":"0:0:0"},"connectorVice":{"voltage":"406.63","current":"0.00","power":"0.00","electricWork":"0.00","chargingTime":"0:0:0"},"meterInfo":{"voltage":"0.00","current":"0.00","power":"0.00"}}}
class SynchroData(PayloadMsg):
    action = "SynchroData"
    payload_template =  {
                            "chargeBoxSN": str,
                            "connectorMain":
                            {
                                "voltage": str,
                                "current": str,
                                "power": str,
                                "electricWork": str,
                                "chargingTime": str
                            },
                            "connectorVice":
                            {
                                "voltage": str,
                                "current": str,
                                "power": str,
                                "electricWork": str,
                                "chargingTime": str
                            },
                            "meterInfo":
                            {
                                "voltage": str,
                                "current": str,
                                "power": str
                            }
                        }

# {"messageTypeId":"5","uniqueId":"3721","action":"NWireToDics","payload":{"chargeBoxSN":"X","NWireExist":true,"NWireClosed":false}}
class NWireToDics(PayloadMsg):
    action = "NWireToDics"
    payload_template =  {
                            "chargeBoxSN": str,
                            "NWireExist": bool,
                            "NWireClosed": bool
                        }

def parse_json(json):
    if json["messageTypeId"] == "5":
        return parse_json_type_payload(json)
    else:
        return None

def parse_json_type_payload(json):
    payload = json["payload"]
    for Class in PayloadMsg.__subclasses__():
        if json["action"] == Class.action:
            return Class(payload)
    return None
