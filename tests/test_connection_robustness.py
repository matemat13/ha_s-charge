#!/usr/bin/env python3
"""Tests for the WebSocket connection staying usable.

Both failures here are the confirmed root causes of the first entry in
known-issues.md ("sometimes the integration does not automatically connect and
has to be restarted"). They are about the connection surviving, not about
parsing: the charger is the only source of data, so a connection that dies
without setting `disconnected_evt` strands the integration until it restarts.

Run with an interpreter that has `websockets` installed:

    ./tests/test_connection_robustness.py
"""

import asyncio
import json
import logging
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import websockets

from scharge_server import SChargeConn

SERIAL = "TEST12345678"

# Payload shapes copied from the real messages documented in messages_rx.py.
DEVICE_DATA = {
    "chargeBoxSN": SERIAL,
    "connectorMain": {"miniCurrent": 6, "maxCurrent": 32, "connectorStatus": 0,
                      "lockStatus": False, "PncStatus": True},
    "connectorVice": {"miniCurrent": 6, "maxCurrent": 32, "connectorStatus": 0,
                      "lockStatus": False, "PncStatus": True},
    "sVersion": "E3P3_H_1.1.1_R5190", "hVersion": "E3P3_V1.00",
    "loadbalance": 10000, "chargeTimes": 26, "cumulativeTime": 71584018,
    "totalPower": 20403, "rssi": -55, "evseType": "EU", "connectorNumber": 2,
    "evsePhase": "threephase", "isHasLock": True, "isHasMeter": True,
}


def synchro_status(charge_status="idle"):
    connector = {"connectionStatus": False, "chargeStatus": charge_status,
                 "statusCode": 0, "startTime": "-", "endTime": "-",
                 "reserveCurrent": 0}
    return {"chargeBoxSN": SERIAL,
            "connectorMain": dict(connector), "connectorVice": dict(connector)}


def synchro_data(voltage="405.92"):
    connector = {"voltage": voltage, "current": "0.00", "power": "0.00",
                 "electricWork": "0.00", "chargingTime": "0:0:0"}
    return {"chargeBoxSN": SERIAL,
            "connectorMain": dict(connector), "connectorVice": dict(connector),
            "meterInfo": {"voltage": "0.00", "current": "0.00", "power": "0.00"}}


NWIRE = {"chargeBoxSN": SERIAL, "NWireExist": True, "NWireClosed": False}


def envelope(action, payload, unique_id):
    return json.dumps({"messageTypeId": "5", "uniqueId": str(unique_id),
                       "action": action, "payload": payload})


def quiet_logger():
    # charger_state warns on an unrecognised status, which several tests
    # deliberately provoke. Silence it so the run's output stays clean.
    logging.getLogger("charger_state").setLevel(logging.CRITICAL)

    logger = logging.getLogger("test_scharge")
    logger.setLevel(logging.CRITICAL)
    logger.addHandler(logging.NullHandler())
    return logger


class ServerHarness:
    """Runs SChargeConn's WebSocket server without the UDP broadcast.

    The broadcast is deliberately left out: it would go out over the real LAN
    and invite the actual charger to connect to the test.
    """

    def __init__(self, message_timeout_s=None):
        self.conn = SChargeConn(SERIAL, "127.0.0.1", None, logger=quiet_logger())
        if message_timeout_s is not None:
            self.conn.message_timeout_s = message_timeout_s

    async def __aenter__(self):
        self.conn.rcv_port_evt = asyncio.Event()
        self.conn.connected_ws_evt = asyncio.Event()
        self.task = asyncio.create_task(self.conn.server_loop())
        await asyncio.wait_for(self.conn.rcv_port_evt.wait(), timeout=5)
        self.port = self.conn.rcv_port
        return self

    async def __aexit__(self, *exc):
        self.task.cancel()
        try:
            await self.task
        except (asyncio.CancelledError, Exception):
            pass


class FakeCharger:
    """A charger that speaks just enough of the protocol to drive the server."""

    def __init__(self, websocket):
        self.ws = websocket
        self.acked = set()
        self.next_id = 1000

    async def send(self, action, payload):
        self.next_id += 1
        try:
            await self.ws.send(envelope(action, payload, self.next_id))
        except websockets.exceptions.ConnectionClosed:
            # Let the test's assertion report the failure, rather than blowing
            # up here with a less informative error.
            pass
        return self.next_id

    async def collect_acks(self, seconds=1.0):
        """Drain incoming frames, recording which uniqueIds got acked."""
        async def drain():
            async for raw in self.ws:
                msg = json.loads(raw)
                if msg.get("messageTypeId") == "6":
                    self.acked.add(int(msg["uniqueId"]))
        try:
            await asyncio.wait_for(drain(), timeout=seconds)
        except (asyncio.TimeoutError, websockets.exceptions.ConnectionClosed):
            pass

    async def initialize(self):
        for action, payload in (("DeviceData", DEVICE_DATA),
                                ("SynchroStatus", synchro_status()),
                                ("SynchroData", synchro_data()),
                                ("NWireToDics", NWIRE)):
            await self.send(action, payload)
        await self.collect_acks(1.0)


async def test_unknown_charge_status_keeps_connection_alive():
    """A chargeStatus the enum doesn't know must not kill the connection.

    `fault` and `reserve` are real values -- the app ships an icon for each
    (see reverse-engineering.md). ChargeStatusEnum defines neither, so
    ChargerParam.update raises ValueError, which escapes process_websocket and
    takes the whole connection down.
    """
    async with ServerHarness() as harness:
        async with websockets.connect(f"ws://127.0.0.1:{harness.port}") as ws:
            charger = FakeCharger(ws)
            await charger.initialize()

            await charger.send("SynchroStatus", synchro_status("fault"))
            await charger.collect_acks(1.0)

            # If the connection survived, this later message is still acked.
            probe_id = await charger.send("SynchroData", synchro_data("401.00"))
            await charger.collect_acks(1.0)

            assert probe_id in charger.acked, (
                "connection died after an unknown chargeStatus -- "
                "later messages are no longer processed"
            )


async def test_clean_close_is_detected_as_a_disconnect():
    """A clean WebSocket close must set disconnected_evt.

    websockets' async iterator swallows ConnectionClosedOK and returns
    normally, so the `except ConnectionClosedError` in process_websocket never
    runs. server_loop then waits on disconnected_evt forever and the UDP
    handshake is never restarted, so the charger can never reconnect.
    """
    async with ServerHarness() as harness:
        ws = await websockets.connect(f"ws://127.0.0.1:{harness.port}")
        charger = FakeCharger(ws)
        await charger.initialize()
        await ws.close()  # a clean close, code 1000

        try:
            await asyncio.wait_for(harness.conn.disconnected_evt.wait(), timeout=3)
        except asyncio.TimeoutError:
            raise AssertionError(
                "clean close was not detected -- disconnected_evt never set, "
                "so the server will wait forever instead of reconnecting"
            )


async def test_fault_status_is_reported():
    """`fault` is a real charger state and must reach the charger state.

    Isolating the exception keeps the connection up, but on its own it leaves
    chargeStatus stuck on its previous value -- so Home Assistant would show a
    faulted charger as idle.
    """
    async with ServerHarness() as harness:
        async with websockets.connect(f"ws://127.0.0.1:{harness.port}") as ws:
            charger = FakeCharger(ws)
            await charger.initialize()

            await charger.send("SynchroStatus", synchro_status("fault"))
            await charger.collect_acks(1.0)

            status = harness.conn.charger_state.connectorMain.chargeStatus.value
            assert status == "fault", f"expected 'fault', charger state says {status!r}"


async def test_unrecognised_status_becomes_unknown():
    """A status we've never seen must map to a value, not be dropped.

    The status list in reverse-engineering.md is a lower bound, and the MQTT
    enum sensor can only publish values it declared as options -- so anything
    unrecognised has to land on a declared fallback.
    """
    async with ServerHarness() as harness:
        async with websockets.connect(f"ws://127.0.0.1:{harness.port}") as ws:
            charger = FakeCharger(ws)
            await charger.initialize()

            await charger.send("SynchroStatus", synchro_status("somethingnew"))
            await charger.collect_acks(1.0)

            status = harness.conn.charger_state.connectorMain.chargeStatus.value
            assert status == "unknown", f"expected 'unknown', got {status!r}"


async def test_a_silent_charger_is_treated_as_disconnected():
    """A connection that dies without a TCP reset must still be noticed.

    If the charger loses power or its WiFi drops, the socket can stay open
    indefinitely from our side. websockets' own keepalive timeout is disabled
    (ping_timeout=inf in server_loop), so nothing detects this until TCP gives
    up minutes later -- and meanwhile the UDP handshake is never rebroadcast,
    so the charger cannot get back in.

    The charger sends a Heartbeat roughly every 12 s on top of its data
    messages (see reverse-engineering.md), so silence is a reliable signal.
    """
    async with ServerHarness(message_timeout_s=1.0) as harness:
        async with websockets.connect(f"ws://127.0.0.1:{harness.port}") as ws:
            charger = FakeCharger(ws)
            await charger.initialize()

            # Say nothing from here on, while holding the socket open.
            try:
                await asyncio.wait_for(harness.conn.disconnected_evt.wait(), timeout=8)
            except asyncio.TimeoutError:
                raise AssertionError(
                    "a silent charger was never detected -- the server would "
                    "hold a dead connection instead of rebroadcasting"
                )


TESTS = [
    test_unknown_charge_status_keeps_connection_alive,
    test_clean_close_is_detected_as_a_disconnect,
    test_fault_status_is_reported,
    test_unrecognised_status_becomes_unknown,
    test_a_silent_charger_is_treated_as_disconnected,
]


async def main():
    failures = 0
    for test in TESTS:
        try:
            await asyncio.wait_for(test(), timeout=30)
        except AssertionError as e:
            failures += 1
            print(f"FAIL  {test.__name__}\n      {e}")
        except Exception as e:
            failures += 1
            print(f"ERROR {test.__name__}\n      {type(e).__name__}: {e}")
        else:
            print(f"PASS  {test.__name__}")

    print(f"\n{len(TESTS) - failures}/{len(TESTS)} passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
