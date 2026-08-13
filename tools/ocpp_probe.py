#!/usr/bin/env python3
"""A permissive OCPP 1.6j central system, for finding out whether a charger
will talk OCPP at all -- and if it does, what it supports.

This is a diagnostic tool, not a production backend. It differs from a real
central system (and from the HACS `ocpp` integration) in three ways that matter
when you don't yet know what the charger expects:

  * it accepts *any* URL path, so the charge point identity never has to be
    agreed in advance -- whatever the charger sends is logged;
  * it accepts *any* websocket subprotocol, echoing back whatever the charger
    offers, so a subprotocol mismatch can't fail the handshake silently;
  * it answers every known OCPP action with a valid response and every unknown
    one with an empty result, so the charger has no reason to disconnect.

Anything unexpected is logged rather than raised: a probe that dies on the first
surprising frame tells you nothing.

Usage:
    source scharge_venv/bin/activate
    ./tools/ocpp_probe.py                      # listen on 0.0.0.0:9000
    ./tools/ocpp_probe.py --port 9000 --log /tmp/ocpp-probe.log

Once a charger connects, type commands on stdin (see `help`) to probe it:
`getconf` dumps every configuration key the charger exposes, which is the
fastest way to learn whether remote current control is available.
"""

import argparse
import asyncio
import json
import logging
import sys
from datetime import datetime, timezone

import websockets
from websockets.asyncio.server import serve

# Offered first when the charger gives us a choice.
PREFERRED_SUBPROTOCOLS = ["ocpp1.6", "ocpp2.0.1", "ocpp2.1"]

CALL = 2
CALLRESULT = 3
CALLERROR = 4

logger = logging.getLogger("ocpp_probe")


def utcnow() -> str:
    """OCPP wants ISO8601 UTC."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class ChargePoint:
    """One connected charger."""

    def __init__(self, identity, websocket, set_current=None):
        self.identity = identity
        self.websocket = websocket
        self.set_current = set_current
        self.transaction_id = 0
        self.active_transaction = None
        self.pending = {}  # our outgoing CALLs, by message id
        self.msg_counter = 0

    # ---------------------------------------------------------------- sending

    def next_msg_id(self) -> str:
        self.msg_counter += 1
        return f"probe-{self.msg_counter}"

    async def call(self, action: str, payload: dict):
        """Send a CALL to the charger and remember it so we can match the reply."""
        msg_id = self.next_msg_id()
        self.pending[msg_id] = action
        frame = json.dumps([CALL, msg_id, action, payload])
        logger.info(">> %s %s", action, json.dumps(payload))
        logger.debug(">> raw %s", frame)
        await self.websocket.send(frame)

    async def send_result(self, msg_id: str, payload: dict):
        frame = json.dumps([CALLRESULT, msg_id, payload])
        logger.debug("<< result raw %s", frame)
        await self.websocket.send(frame)

    # -------------------------------------------------------------- receiving

    async def handle_frame(self, raw: str):
        logger.debug("<< raw %s", raw)
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("<< NOT JSON, ignoring: %r", raw)
            return

        if not isinstance(msg, list) or not msg:
            logger.warning("<< not an OCPP frame, ignoring: %r", msg)
            return

        kind = msg[0]
        if kind == CALL:
            await self.handle_call(msg)
        elif kind == CALLRESULT:
            self.handle_callresult(msg)
        elif kind == CALLERROR:
            self.handle_callerror(msg)
        else:
            logger.warning("<< unknown message type id %r: %r", kind, msg)

    async def handle_call(self, msg: list):
        try:
            _, msg_id, action, payload = msg
        except ValueError:
            logger.warning("<< malformed CALL, ignoring: %r", msg)
            return

        logger.info("<< %s %s", action, json.dumps(payload))

        handler = getattr(self, f"on_{action}", None)
        if handler is None:
            # Answer anyway. A CALLERROR here would give the charger a reason to
            # drop the connection, and we want it to keep talking.
            logger.warning(
                "<< UNKNOWN ACTION %r -- answering with an empty result", action
            )
            await self.send_result(msg_id, {})
            return

        try:
            response = handler(payload)
        except Exception:
            logger.exception("handler for %s failed -- answering empty", action)
            response = {}

        await self.send_result(msg_id, response)

        if action == "BootNotification":
            # The charger has just told us who it is; now ask what it can do.
            asyncio.create_task(self.after_boot())

    def handle_callresult(self, msg: list):
        try:
            _, msg_id, payload = msg
        except ValueError:
            logger.warning("<< malformed CALLRESULT, ignoring: %r", msg)
            return
        action = self.pending.pop(msg_id, "<unmatched>")
        logger.info("<< RESULT for %s: %s", action, json.dumps(payload, indent=2))

    def handle_callerror(self, msg: list):
        action = "<unmatched>"
        if len(msg) >= 2:
            action = self.pending.pop(msg[1], "<unmatched>")
        logger.warning("<< ERROR for %s: %s", action, json.dumps(msg[2:]))

    # ------------------------------------------------------- action handlers

    def on_BootNotification(self, payload):
        logger.info("=== charger identified itself ===")
        for key, value in payload.items():
            logger.info("    %s: %s", key, value)
        return {"currentTime": utcnow(), "interval": 300, "status": "Accepted"}

    def on_Heartbeat(self, payload):
        return {"currentTime": utcnow()}

    def on_StatusNotification(self, payload):
        return {}

    def on_Authorize(self, payload):
        return {"idTagInfo": {"status": "Accepted"}}

    def on_StartTransaction(self, payload):
        self.transaction_id += 1
        self.active_transaction = self.transaction_id
        logger.info("=== transaction %d started ===", self.transaction_id)
        if self.set_current is not None:
            asyncio.create_task(self.send_charging_profile(self.set_current))
        return {
            "transactionId": self.transaction_id,
            "idTagInfo": {"status": "Accepted"},
        }

    def on_StopTransaction(self, payload):
        logger.info("=== transaction stopped ===")
        self.active_transaction = None
        return {"idTagInfo": {"status": "Accepted"}}

    def on_MeterValues(self, payload):
        return {}

    def on_DataTransfer(self, payload):
        # Vendor-specific. Worth logging loudly: this is where a charger that
        # only half-speaks OCPP tends to hide its proprietary extensions.
        logger.info("=== vendor DataTransfer: %s ===", json.dumps(payload))
        return {"status": "Accepted"}

    def on_FirmwareStatusNotification(self, payload):
        return {}

    def on_DiagnosticsStatusNotification(self, payload):
        return {}

    # ---------------------------------------------------------------- probing

    async def after_boot(self):
        """Ask the charger to describe itself."""
        await asyncio.sleep(1.0)
        await self.call("GetConfiguration", {})

    async def send_charging_profile(self, amps: int, connector_id: int = 1):
        """The whole point of the exercise: set the charging current remotely."""
        await asyncio.sleep(2.0)
        await self.call(
            "SetChargingProfile",
            {
                "connectorId": connector_id,
                "csChargingProfiles": {
                    "chargingProfileId": 1,
                    "stackLevel": 0,
                    "chargingProfilePurpose": "TxDefaultProfile",
                    "chargingProfileKind": "Absolute",
                    "chargingSchedule": {
                        "chargingRateUnit": "A",
                        "chargingSchedulePeriod": [
                            {"startPeriod": 0, "limit": amps}
                        ],
                    },
                },
            },
        )


HELP = """
commands:
  getconf [key]        GetConfiguration -- no key dumps everything
  setconf <key> <val>  ChangeConfiguration
  current <amps>       SetChargingProfile at <amps> on connector 1
  start [connector]    RemoteStartTransaction (default connector 1)
  stop                 RemoteStopTransaction on the active transaction
  trigger <message>    TriggerMessage, e.g. `trigger StatusNotification`
  reset [soft|hard]    Reset the charger
  raw <action> <json>  send an arbitrary CALL
  help                 this text
"""


async def console(state: dict):
    """Drive the connected charger from stdin."""
    loop = asyncio.get_running_loop()
    while True:
        line = await loop.run_in_executor(None, sys.stdin.readline)
        if not line:  # stdin closed
            return
        line = line.strip()
        if not line:
            continue

        cp = state.get("cp")
        if cp is None:
            logger.warning("no charger connected yet")
            continue

        parts = line.split(maxsplit=2)
        cmd = parts[0].lower()
        try:
            if cmd == "help":
                print(HELP)
            elif cmd == "getconf":
                payload = {"key": [parts[1]]} if len(parts) > 1 else {}
                await cp.call("GetConfiguration", payload)
            elif cmd == "setconf":
                await cp.call(
                    "ChangeConfiguration", {"key": parts[1], "value": parts[2]}
                )
            elif cmd == "current":
                await cp.send_charging_profile(int(parts[1]))
            elif cmd == "start":
                connector = int(parts[1]) if len(parts) > 1 else 1
                await cp.call(
                    "RemoteStartTransaction",
                    {"connectorId": connector, "idTag": "probe"},
                )
            elif cmd == "stop":
                if cp.active_transaction is None:
                    logger.warning("no active transaction")
                    continue
                await cp.call(
                    "RemoteStopTransaction",
                    {"transactionId": cp.active_transaction},
                )
            elif cmd == "trigger":
                await cp.call("TriggerMessage", {"requestedMessage": parts[1]})
            elif cmd == "reset":
                kind = parts[1].capitalize() if len(parts) > 1 else "Soft"
                await cp.call("Reset", {"type": kind})
            elif cmd == "raw":
                await cp.call(parts[1], json.loads(parts[2]))
            else:
                logger.warning("unknown command %r -- try `help`", cmd)
        except (IndexError, ValueError) as e:
            logger.warning("bad command (%s) -- try `help`", e)


def select_subprotocol(connection, subprotocols):
    """Accept whatever the charger offers.

    websockets' default would answer with no subprotocol at all when there's no
    overlap with our list, and some chargers abort the handshake at that point.
    """
    logger.info("charger offered subprotocols: %s", list(subprotocols) or "<none>")
    for preferred in PREFERRED_SUBPROTOCOLS:
        if preferred in subprotocols:
            return preferred
    if subprotocols:
        logger.warning(
            "none of %s offered -- echoing %r back anyway",
            PREFERRED_SUBPROTOCOLS,
            subprotocols[0],
        )
        return subprotocols[0]
    return None


def make_handler(state: dict, set_current):
    async def handler(websocket):
        request = websocket.request
        path = request.path
        identity = path.rstrip("/").rsplit("/", 1)[-1] or "<empty>"
        peer = websocket.remote_address

        logger.info("=" * 70)
        logger.info("CONNECTION from %s:%s", peer[0], peer[1])
        logger.info("  request path : %s", path)
        logger.info("  identity     : %s", identity)
        logger.info("  subprotocol  : %s", websocket.subprotocol or "<none>")
        logger.info("  headers:")
        for name, value in request.headers.raw_items():
            logger.info("    %s: %s", name, value)
        logger.info("=" * 70)

        cp = ChargePoint(identity, websocket, set_current=set_current)
        state["cp"] = cp

        try:
            async for raw in websocket:
                try:
                    await cp.handle_frame(raw)
                except Exception:
                    # Never let one bad frame kill the connection.
                    logger.exception("failed to handle frame %r", raw)
        except websockets.exceptions.ConnectionClosed as e:
            logger.info("connection closed: %s", e)
        finally:
            if state.get("cp") is cp:
                state["cp"] = None
            logger.info("charger %s disconnected", identity)

    return handler


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=9000)
    parser.add_argument("--log", default="/tmp/ocpp-probe.log")
    parser.add_argument(
        "--set-current",
        type=int,
        default=None,
        metavar="AMPS",
        help="automatically send a SetChargingProfile at AMPS when a "
        "transaction starts",
    )
    args = parser.parse_args()

    formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
    logger.setLevel(logging.DEBUG)

    fh = logging.FileHandler(args.log)
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(formatter)
    logger.addHandler(fh)

    sh = logging.StreamHandler()
    sh.setLevel(logging.INFO)
    sh.setFormatter(formatter)
    logger.addHandler(sh)

    # Surface the library's own handshake failures -- a charger that fails to
    # connect often fails here, before our handler ever runs.
    ws_logger = logging.getLogger("websockets.server")
    ws_logger.setLevel(logging.DEBUG)
    ws_logger.addHandler(fh)
    ws_logger.addHandler(sh)

    state = {"cp": None}

    logger.info("OCPP probe listening on ws://%s:%d/", args.host, args.port)
    logger.info("point the charger at ws://<this-host>:%d/<any-id>", args.port)
    logger.info("logging to %s -- type `help` for commands", args.log)

    async with serve(
        make_handler(state, args.set_current),
        host=args.host,
        port=args.port,
        select_subprotocol=select_subprotocol,
        ping_interval=None,  # some chargers don't answer pings
    ):
        if sys.stdin.isatty():
            await console(state)
        else:
            # Running detached (nohup, addon, systemd): there is no console to
            # read, and treating EOF on stdin as "quit" would kill the server.
            logger.info("stdin is not a terminal -- console disabled")
            await asyncio.Future()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
