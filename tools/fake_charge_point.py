#!/usr/bin/env python3
"""Pretends to be an OCPP 1.6j charge point, to check the probe server works
before you go and point real hardware at it.

Run the probe in one terminal and this in another:

    ./tools/ocpp_probe.py --port 9010 --set-current 13
    ./tools/fake_charge_point.py --port 9010

It exercises the paths that matter: the handshake and subprotocol negotiation,
BootNotification, the probe's automatic GetConfiguration, SetChargingProfile on
transaction start, and -- importantly -- that a burst of malformed frames
doesn't take the connection down.
"""

import argparse
import asyncio
import json
import sys

import websockets

CALL, CALLRESULT, CALLERROR = 2, 3, 4

# What a charger might plausibly answer GetConfiguration with.
FAKE_CONFIG = {
    "configurationKey": [
        {"key": "HeartbeatInterval", "readonly": False, "value": "300"},
        {
            "key": "ChargingScheduleAllowedChargingRateUnit",
            "readonly": True,
            "value": "Current",
        },
        {
            "key": "SupportedFeatureProfiles",
            "readonly": True,
            "value": "Core,SmartCharging,RemoteTrigger",
        },
    ],
    "unknownKey": [],
}


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=9010)
    parser.add_argument("--identity", default="JNT-TEST-0001")
    parser.add_argument(
        "--expect-amps",
        type=int,
        default=13,
        help="the --set-current value the probe was started with",
    )
    args = parser.parse_args()

    uri = f"ws://{args.host}:{args.port}/{args.identity}"
    seen = {"boot": False, "getconf": False, "amps": None, "alive": False}

    async with websockets.connect(uri, subprotocols=["ocpp1.6"]) as ws:
        print(f"connected to {uri}, subprotocol={ws.subprotocol}")

        async def read_frames(until):
            """Answer anything the probe asks, until `until` is answered."""
            async for raw in ws:
                msg = json.loads(raw)
                print(f"<< {raw}")
                if msg[0] == CALLRESULT:
                    if msg[1] == "1":
                        seen["boot"] = msg[2].get("status") == "Accepted"
                    if msg[1] == "4" and "currentTime" in msg[2]:
                        seen["alive"] = True
                    if until and msg[1] == until:
                        return
                elif msg[0] == CALL:
                    _, mid, action, payload = msg
                    if action == "GetConfiguration":
                        seen["getconf"] = True
                        await ws.send(json.dumps([CALLRESULT, mid, FAKE_CONFIG]))
                    elif action == "SetChargingProfile":
                        seen["amps"] = (
                            payload["csChargingProfiles"]
                            ["chargingSchedule"]
                            ["chargingSchedulePeriod"][0]["limit"]
                        )
                        await ws.send(
                            json.dumps([CALLRESULT, mid, {"status": "Accepted"}])
                        )
                    else:
                        await ws.send(json.dumps([CALLRESULT, mid, {}]))

        async def pump(seconds, until=None):
            """Read frames for a while. asyncio.wait_for rather than
            asyncio.timeout, so this runs on Python 3.8 too."""
            try:
                await asyncio.wait_for(read_frames(until), timeout=seconds)
            except asyncio.TimeoutError:
                pass

        await ws.send(
            json.dumps(
                [
                    CALL,
                    "1",
                    "BootNotification",
                    {
                        "chargePointVendor": "Joint",
                        "chargePointModel": "EVCD2",
                        "firmwareVersion": "E3P3_H_1.1.1_R5190",
                    },
                ]
            )
        )
        await pump(3.0)

        await ws.send(
            json.dumps(
                [
                    CALL,
                    "2",
                    "StartTransaction",
                    {
                        "connectorId": 1,
                        "idTag": "abc",
                        "meterStart": 0,
                        "timestamp": "2026-08-13T10:00:00Z",
                    },
                ]
            )
        )
        await pump(5.0)

        # The probe must survive all three of these.
        await ws.send("not json at all")
        await ws.send(json.dumps({"not": "a list"}))
        await ws.send(json.dumps([CALL, "3", "TotallyUnknownAction", {"x": 1}]))
        await pump(2.0)

        # Still there?
        await ws.send(json.dumps([CALL, "4", "Heartbeat", {}]))
        await pump(3.0, until="4")

    checks = [
        ("BootNotification accepted", seen["boot"]),
        ("GetConfiguration received", seen["getconf"]),
        (f"SetChargingProfile == {args.expect_amps}A", seen["amps"] == args.expect_amps),
        ("survived malformed frames", seen["alive"]),
    ]
    print("\n--- results ---")
    for label, ok in checks:
        print(f"  {'PASS' if ok else 'FAIL'}  {label}")

    overall = all(ok for _, ok in checks)
    print("\nPASS" if overall else "\nFAIL")
    sys.exit(0 if overall else 1)


if __name__ == "__main__":
    asyncio.run(main())
