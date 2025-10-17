#!/usr/bin/env python3
import json
from datetime import datetime


class JsonMsg:
    def encode_raw(self, raw_json):
        return json.dumps(raw_json, separators=(',', ':'))


class UDPHandShake(JsonMsg):
    messageTypeId = "5"
    action = "UDPHandShake"
    label = "APP"

    def __init__(self, timeout_time_unix : float, chargeBoxSN : int, ip_address : int, port : int):
        self.timeout_time_unix = timeout_time_unix
        self.chargeBoxSN = chargeBoxSN
        self.ip_address = ip_address
        self.port = port

    def encode(self):
        timestamp = int(self.timeout_time_unix * 1000)
        raw_json =  {
                    "messageTypeId": self.messageTypeId,
                    "uniqueId": f"{timestamp}",
                    "action": self.action,
                    "payload":
                        {
                        "label": self.label,
                        "chargeBoxSN": f"{self.chargeBoxSN}",
                        "iPAddress": f"{self.ip_address}:{self.port}"
                        }
                    }
        return super().encode_raw(raw_json)

# {"messageTypeId":"5","uniqueId":"1761830821364","action":"HandShake","payload":{"userId":"1","chargeBoxSN":"x","currentTime":"2025-10-30T14:27:01Z","connectionKey":"x"}}
class HandShake(JsonMsg):
    messageTypeId = "5"
    action = "HandShake"

    def __init__(self, current_time_unix : float, userId : int, chargeBoxSN : int, connectionKey : int):
        self.userId = userId
        self.chargeBoxSN = chargeBoxSN
        self.current_time_unix = current_time_unix
        self.connectionKey = connectionKey

    def encode(self):
        timestamp = int(self.current_time_unix * 1000)
        dt = datetime.fromtimestamp(self.current_time_unix)
        formatted_time = dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        raw_json =  {
                    "messageTypeId": self.messageTypeId,
                    "uniqueId": f"{timestamp}",
                    "action": self.action,
                    "payload":
                        {
                        "userId": self.userId,
                        "chargeBoxSN": f"{self.chargeBoxSN}",
                        "currentTime": formatted_time,
                        "connectionKey": f"{self.connectionKey}"
                        }
                    }
        return super().encode_raw(raw_json)

# {"messageTypeId":"6","uniqueId":"3238","payload":{"chargeBoxSN":"X"}}
class Ack(JsonMsg):
    messageTypeId = "6"

    def __init__(self, chargeBoxSN : int, uniqueId : int):
        self.chargeBoxSN = chargeBoxSN
        self.uniqueId = uniqueId

    def encode(self):
        raw_json =  {
                    "messageTypeId": self.messageTypeId,
                    "uniqueId": f"{self.uniqueId}",
                    "payload":
                        {
                        "chargeBoxSN": f"{self.chargeBoxSN}",
                        }
                    }
        return super().encode_raw(raw_json)

# {"messageTypeId":"5","uniqueId":"1761830827953","action":"Authorize","payload":{"userId":"1","chargeBoxSN":"x","purpose":"Start","current":8,"connectorId":2}}
class Authorize(JsonMsg):
    messageTypeId = "5"
    action = "Authorize"

    def __init__(self, current_time_unix : float, userId : int, chargeBoxSN : int, purpose : str, current : int, connectorId : int):
        self.current_time_unix = current_time_unix
        self.userId = userId
        self.chargeBoxSN = chargeBoxSN
        self.purpose = purpose
        self.current = current
        self.connectorId = connectorId

    def encode(self):
        timestamp = int(self.current_time_unix * 1000)
        raw_json =  {
                    "messageTypeId": self.messageTypeId,
                    "uniqueId": f"{timestamp}",
                    "action": self.action,
                    "payload":
                        {
                        "userId": self.userId,
                        "chargeBoxSN": f"{self.chargeBoxSN}",
                        "purpose": self.purpose,
                        "current": self.current,
                        "connectorId": self.connectorId
                        }
                    }
        return super().encode_raw(raw_json)
