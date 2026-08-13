#!/usr/bin/env python3
"""Tests for the requested charging current actually taking effect.

Third entry in known-issues.md. Measured behaviour of the charger (recorded in
reverse-engineering.md §5a, raw data in artifacts/current_experiment.csv):

  * the first Start after a session ends is acked but the current in it is
    ignored -- a 6 A request ran at 30.95 A;
  * a Start re-sent while already charging does apply the current;
  * reserveCurrent never echoes the request, so it cannot be used to confirm;
  * the car settles *below* the limit by a margin that grows with the setpoint
    (8 A -> 7.17 A, 10 A -> 8.88 A), so equality against the measured current
    is not a usable check -- only the ceiling is.

Run with an interpreter that has `websockets` installed:

    ./tests/test_current_control.py
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


def synchro_status(main="idle", vice="idle"):
    def connector(status):
        return {"connectionStatus": status != "idle", "chargeStatus": status,
                "statusCode": 0, "startTime": "-", "endTime": "-",
                "reserveCurrent": 0}
    return {"chargeBoxSN": SERIAL,
            "connectorMain": connector(main), "connectorVice": connector(vice)}


def synchro_data(main_current="0.00", vice_current="0.00"):
    def connector(current):
        return {"voltage": "405.92", "current": current, "power": "0.00",
                "electricWork": "0.00", "chargingTime": "0:0:0"}
    return {"chargeBoxSN": SERIAL,
            "connectorMain": connector(main_current),
            "connectorVice": connector(vice_current),
            "meterInfo": {"voltage": "0.00", "current": "0.00", "power": "0.00"}}


NWIRE = {"chargeBoxSN": SERIAL, "NWireExist": True, "NWireClosed": False}


def quiet_logger():
    logging.getLogger("charger_state").setLevel(logging.CRITICAL)
    logger = logging.getLogger("test_current")
    logger.setLevel(logging.CRITICAL)
    logger.addHandler(logging.NullHandler())
    return logger


class ServerHarness:
    def __init__(self):
        self.conn = SChargeConn(SERIAL, "127.0.0.1", None, logger=quiet_logger())
        # Keep the tests quick.
        self.conn.reconcile_period_s = 0.2
        self.conn.current_settle_s = 0.5

    async def __aenter__(self):
        self.conn.rcv_port_evt = asyncio.Event()
        self.conn.connected_ws_evt = asyncio.Event()
        self.server_task = asyncio.create_task(self.conn.server_loop())
        await asyncio.wait_for(self.conn.rcv_port_evt.wait(), timeout=5)
        self.port = self.conn.rcv_port
        # main() would start this; the harness runs server_loop on its own.
        self.reconcile_task = asyncio.create_task(self.conn.current_reconcile_loop())
        return self

    async def __aexit__(self, *exc):
        for task in (self.reconcile_task, self.server_task):
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass


class FakeCharger:
    """Acks everything and records the Authorize commands it receives."""

    def __init__(self, websocket):
        self.ws = websocket
        self.authorizes = []
        self.next_id = 1000
        self.reader = asyncio.create_task(self._read())

    async def _read(self):
        try:
            async for raw in self.ws:
                msg = json.loads(raw)
                if msg.get("action") == "Authorize":
                    self.authorizes.append(msg["payload"])
                    # The charger acks an Authorize even when it goes on to
                    # ignore the current -- that is the whole problem.
                    await self.ws.send(json.dumps({
                        "messageTypeId": "6", "uniqueId": msg["uniqueId"],
                        "payload": {"chargeBoxSN": SERIAL, "result": True}}))
        except (websockets.exceptions.ConnectionClosed, asyncio.CancelledError):
            pass

    async def send(self, action, payload):
        self.next_id += 1
        await self.ws.send(json.dumps({
            "messageTypeId": "5", "uniqueId": str(self.next_id),
            "action": action, "payload": payload}))
        await asyncio.sleep(0.1)  # let the server process it

    async def initialize(self, status=None, data=None):
        for action, payload in (("DeviceData", DEVICE_DATA),
                                ("SynchroStatus", status or synchro_status()),
                                ("SynchroData", data or synchro_data()),
                                ("NWireToDics", NWIRE)):
            await self.send(action, payload)

    def starts_for(self, connector_id):
        return [a for a in self.authorizes
                if a["purpose"] == "Start" and a["connectorId"] == connector_id]

    async def wait_for_start(self, connector_id, timeout=3.0):
        async def poll():
            while not self.starts_for(connector_id):
                await asyncio.sleep(0.05)
        try:
            await asyncio.wait_for(poll(), timeout=timeout)
        except asyncio.TimeoutError:
            pass
        return self.starts_for(connector_id)


async def test_desired_current_is_applied_when_a_session_starts():
    """Covers both the ignored-on-first-Start case and autostart.

    Nothing today watches for a session beginning, so a charge that starts by
    itself -- plugging in, or the charger powering up -- runs at whatever
    current the charger picks.
    """
    async with ServerHarness() as harness:
        async with websockets.connect(f"ws://127.0.0.1:{harness.port}") as ws:
            charger = FakeCharger(ws)
            await charger.initialize()
            harness.conn.set_desired_current(6)

            # A session begins without us having asked for it.
            await charger.send("SynchroStatus", synchro_status(vice="charging"))

            starts = await charger.wait_for_start(2)
            assert starts, "no Start was sent when a session began"
            assert starts[-1]["current"] == 6, \
                f"expected the 6A setpoint to be applied, got {starts[-1]['current']}"


async def test_changing_the_desired_current_while_charging_is_applied():
    """Today the number entity only updates a variable; nothing is sent."""
    async with ServerHarness() as harness:
        async with websockets.connect(f"ws://127.0.0.1:{harness.port}") as ws:
            charger = FakeCharger(ws)
            await charger.initialize()
            harness.conn.set_desired_current(6)
            await charger.send("SynchroStatus", synchro_status(vice="charging"))
            await charger.wait_for_start(2)

            harness.conn.set_desired_current(10)
            async def poll():
                while not any(a["current"] == 10 for a in charger.starts_for(2)):
                    await asyncio.sleep(0.05)
            try:
                await asyncio.wait_for(poll(), timeout=3.0)
            except asyncio.TimeoutError:
                raise AssertionError(
                    "changing the desired current sent nothing to the charger")


async def test_drawing_over_the_limit_triggers_a_reapply():
    """The 6 A -> 30.95 A case: acked, but the limit was not honoured."""
    async with ServerHarness() as harness:
        async with websockets.connect(f"ws://127.0.0.1:{harness.port}") as ws:
            charger = FakeCharger(ws)
            await charger.initialize()
            harness.conn.set_desired_current(6)
            await charger.send("SynchroStatus", synchro_status(vice="charging"))
            first = await charger.wait_for_start(2)
            assert first, "no initial Start"
            sent_before = len(charger.starts_for(2))

            # The charger acked 6 A and is drawing 30.95 A anyway.
            await charger.send("SynchroData", synchro_data(vice_current="30.95"))

            async def poll():
                while len(charger.starts_for(2)) <= sent_before:
                    await asyncio.sleep(0.05)
            try:
                await asyncio.wait_for(poll(), timeout=3.0)
            except asyncio.TimeoutError:
                raise AssertionError(
                    "drawing 30.95A against a 6A limit did not trigger a re-apply")


async def test_drawing_under_the_limit_does_not_trigger_a_reapply():
    """The car settles below the limit; that is normal, not a failure.

    10 A settles at 8.88 A, which the old equality check with a 1.0 A tolerance
    would have treated as a failure and retried ten times.
    """
    async with ServerHarness() as harness:
        async with websockets.connect(f"ws://127.0.0.1:{harness.port}") as ws:
            charger = FakeCharger(ws)
            await charger.initialize()
            harness.conn.set_desired_current(10)
            await charger.send("SynchroStatus", synchro_status(vice="charging"))
            await charger.wait_for_start(2)
            sent_before = len(charger.starts_for(2))

            for _ in range(6):
                await charger.send("SynchroData", synchro_data(vice_current="8.88"))
                await asyncio.sleep(0.2)

            extra = len(charger.starts_for(2)) - sent_before
            assert extra == 0, \
                f"re-applied {extra} times while the car drew a normal 8.88A"


async def test_stopping_is_not_undone_by_reconciliation():
    """A Stop must not race the reconciler into restarting the session."""
    async with ServerHarness() as harness:
        async with websockets.connect(f"ws://127.0.0.1:{harness.port}") as ws:
            charger = FakeCharger(ws)
            await charger.initialize()
            harness.conn.set_desired_current(6)
            await charger.send("SynchroStatus", synchro_status(vice="charging"))
            await charger.wait_for_start(2)

            asyncio.create_task(harness.conn.stop_charging(2))
            await asyncio.sleep(0.2)
            sent_before = len(charger.starts_for(2))

            # The charger keeps reporting `charging` for a while after the Stop.
            for _ in range(6):
                await charger.send("SynchroStatus", synchro_status(vice="charging"))
                await asyncio.sleep(0.2)

            extra = len(charger.starts_for(2)) - sent_before
            assert extra == 0, f"reconciler sent {extra} Starts after a Stop"


TESTS = [
    test_desired_current_is_applied_when_a_session_starts,
    test_changing_the_desired_current_while_charging_is_applied,
    test_drawing_over_the_limit_triggers_a_reapply,
    test_drawing_under_the_limit_does_not_trigger_a_reapply,
    test_stopping_is_not_undone_by_reconciliation,
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
