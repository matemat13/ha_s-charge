#!/usr/bin/env python3
"""Tests for the calculated total charged energy being monotonic.

Second entry in known-issues.md: the total sometimes goes *down*, which is
worse than cosmetic -- Home Assistant reads a decrease on a `total_increasing`
sensor as a meter reset and adds the whole new value as fresh consumption,
inflating the energy dashboard.

The cause is that the three inputs arrive in three different messages with no
ordering guarantee:

  totalPower    DeviceData      cumulative, only updated when a session ends
  chargeStatus  SynchroStatus   whether a session is running
  electricWork  SynchroData     energy of the running session

Run with an interpreter that has `websockets` installed:

    ./tests/test_total_energy.py
"""

import asyncio
import logging
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from charger_state import ChargerState
from messages_rx import parse_json

SERIAL = "TEST12345678"


def device_data(total_power):
    """total_power is in the charger's raw units of 0.01 kWh."""
    return {
        "chargeBoxSN": SERIAL,
        "connectorMain": {"miniCurrent": 6, "maxCurrent": 32, "connectorStatus": 0,
                          "lockStatus": False, "PncStatus": True},
        "connectorVice": {"miniCurrent": 6, "maxCurrent": 32, "connectorStatus": 0,
                          "lockStatus": False, "PncStatus": True},
        "sVersion": "E3P3_H_1.1.1_R5190", "hVersion": "E3P3_V1.00",
        "loadbalance": 10000, "chargeTimes": 26, "cumulativeTime": 71584018,
        "totalPower": total_power, "rssi": -55, "evseType": "EU",
        "connectorNumber": 2, "evsePhase": "threephase",
        "isHasLock": True, "isHasMeter": True,
    }


def synchro_status(main_status):
    def connector(status):
        return {"connectionStatus": status == "charging", "chargeStatus": status,
                "statusCode": 0, "startTime": "-", "endTime": "-",
                "reserveCurrent": 0}
    return {"chargeBoxSN": SERIAL,
            "connectorMain": connector(main_status),
            "connectorVice": connector("idle")}


def synchro_data(main_energy):
    def connector(energy):
        return {"voltage": "405.92", "current": "16.00", "power": "11.20",
                "electricWork": energy, "chargingTime": "1:0:0"}
    return {"chargeBoxSN": SERIAL,
            "connectorMain": connector(main_energy),
            "connectorVice": connector("0.00"),
            "meterInfo": {"voltage": "0.00", "current": "0.00", "power": "0.00"}}


async def feed(state, action, payload):
    msg = parse_json({"messageTypeId": "5", "uniqueId": "1",
                      "action": action, "payload": payload})
    await state.update(msg)


async def fresh_state():
    state = ChargerState(SERIAL)
    await feed(state, "DeviceData", device_data(10000))       # 100.00 kWh
    await feed(state, "SynchroStatus", synchro_status("idle"))
    await feed(state, "SynchroData", synchro_data("0.00"))
    return state


async def test_total_does_not_drop_when_a_session_ends():
    """The status flips to `finish` before DeviceData reports the new total.

    In that window the session term disappears from the sum while totalPower
    has not yet absorbed it, so a naive sum falls by the whole session.
    """
    state = await fresh_state()

    await feed(state, "SynchroStatus", synchro_status("charging"))
    await feed(state, "SynchroData", synchro_data("5.00"))
    during = state.total_charged_energy()
    assert during == 105.0, f"expected 105.0 while charging, got {during}"

    # Session ends. DeviceData has not caught up yet.
    await feed(state, "SynchroStatus", synchro_status("finish"))
    after = state.total_charged_energy()
    assert after >= during, f"total dropped from {during} to {after}"

    # DeviceData finally reports the new cumulative total.
    await feed(state, "DeviceData", device_data(10500))
    settled = state.total_charged_energy()
    assert settled == 105.0, f"expected 105.0 once settled, got {settled}"


async def test_total_does_not_double_count_when_devicedata_lands_first():
    """The opposite ordering: totalPower absorbs the session while still charging.

    Adding the session energy on top would spike the total, and a naive
    monotonic latch would then lock that spike in permanently.
    """
    state = await fresh_state()

    await feed(state, "SynchroStatus", synchro_status("charging"))
    await feed(state, "SynchroData", synchro_data("5.00"))
    assert state.total_charged_energy() == 105.0

    # totalPower now already includes the 5 kWh, but we are still charging.
    await feed(state, "DeviceData", device_data(10500))
    total = state.total_charged_energy()
    assert total == 105.0, f"expected 105.0, got {total} (session counted twice)"


async def test_total_is_monotonic_across_a_full_session():
    """Whatever the message ordering, the sequence must never decrease."""
    state = await fresh_state()
    seen = [state.total_charged_energy()]

    async def record(action, payload):
        await feed(state, action, payload)
        seen.append(state.total_charged_energy())

    await record("SynchroStatus", synchro_status("charging"))
    for energy in ("0.00", "1.50", "3.20", "5.00", "7.34"):
        await record("SynchroData", synchro_data(energy))
    await record("SynchroStatus", synchro_status("finish"))
    await record("DeviceData", device_data(10734))
    await record("SynchroData", synchro_data("0.00"))
    await record("SynchroStatus", synchro_status("idle"))

    drops = [(a, b) for a, b in zip(seen, seen[1:]) if b < a]
    assert not drops, f"total decreased at {drops} in sequence {seen}"
    # Tolerance because 107.34 reaches this by two routes -- 10734/100 and
    # 100.0 + 7.34 -- which need not land on the same double.
    assert abs(seen[-1] - 107.34) < 1e-9, \
        f"expected to settle at 107.34, got {seen[-1]}"


async def test_mqtt_sensor_reports_the_tracked_total():
    """The sensor Home Assistant sees must use the tracked value.

    Guards against the naive sum reappearing in the MQTT layer, where the
    monotonicity work in ChargerState would be bypassed entirely.
    """
    from mqtt_client import MQTTClient
    from scharge_server import SChargeConn

    conn = SChargeConn(SERIAL, "127.0.0.1", None, logger=logging.getLogger("unused"))
    client = MQTTClient("localhost", "1883", "u", "p", conn,
                        logging.getLogger("unused"))

    state = conn.charger_state
    await feed(state, "DeviceData", device_data(10000))
    await feed(state, "SynchroStatus", synchro_status("charging"))
    await feed(state, "SynchroData", synchro_data("5.00"))
    assert client.get_total_charged_energy() == 105.0

    # Session ends before DeviceData catches up -- the naive sum returns 100.0.
    await feed(state, "SynchroStatus", synchro_status("finish"))
    reported = client.get_total_charged_energy()
    assert reported == 105.0, f"MQTT sensor reported {reported}, bypassing the latch"


TESTS = [
    test_total_does_not_drop_when_a_session_ends,
    test_total_does_not_double_count_when_devicedata_lands_first,
    test_total_is_monotonic_across_a_full_session,
    test_mqtt_sensor_reports_the_tracked_total,
]


async def main():
    logging.getLogger("charger_state").setLevel(logging.CRITICAL)
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
