#!/usr/bin/env python3
import socket
import time
import sys
import ipaddress
import logging

import asyncio
import websockets
import json

from messages import *
from messages_rx import *
from charger_state import ChargerState

class SChargeConn:

    def __init__(self, charge_box_serial, rcv_ip, rcv_port, logger):
        self.shutdown = False
        self.websocket = None
        self.future_confirmations = list()
        self.logger = logger

        self.charge_box_serial = charge_box_serial
        self.user_id = 1
        self.connection_key = charge_box_serial

        self.charger_state = ChargerState(self.charge_box_serial)

        self.rcv_ip = rcv_ip
        self.rcv_port = rcv_port

        # get the 24 subnet corresponding to the specified ip address
        ip_network = ipaddress.ip_network(rcv_ip).supernet(new_prefix=24)
        self.broadcast_ip = f"{ip_network.broadcast_address}"
        self.broadcast_port = 3050

        self.udp_handshake_timeout_s = 1.9
        self.confirmation_timeout_s = 5.0
        self.handshake_period_s = 3.0
        self.request_data_period_s = 0.3
        # The charger sends a Heartbeat about every 12s on top of its data
        # messages, so this leaves plenty of room before we call it dead.
        self.message_timeout_s = 30.0
        self.last_message_time = 0.0

        # Charging current management; see current_reconcile_loop().
        self.desired_current = None
        self.applied_current = {}   # connectorId -> setpoint the charger acked
        self.charging_since = {}    # connectorId -> when that setpoint landed
        self.stopping = set()       # connectorIds we have asked to stop
        self.reconcile_period_s = 2.0
        self.current_settle_s = 10.0
        self.current_ceiling_margin_A = 1.0
        self.charging_start_timeout_s = 30.0
        self.charging_stop_timeout_s = 30.0
        self.shutdown_timeout_s = 5.0

        self.loop_tasks = set()

    async def send_authorize_msg(self, current: int, purpose: str, connectorId: int):
        if self.websocket is None:
            return False, "not connected"

        if not self.charger_state.initialized():
            return False, "charger state not initialized"
        
        num_connectors = len(self.charger_state.connectors)
        if connectorId > num_connectors or connectorId < 1:
            return False, f"invalid connector ID {connectorId} (expected within range of [1, {num_connectors}]"

        msg_id = int(1000 * time.time())
        msg = Authorize(
                    uniqueId = msg_id,
                    userId = self.user_id,
                    chargeBoxSN = self.charge_box_serial,
                    purpose = purpose,
                    current = current,
                    connectorId = connectorId
                )
        message = msg.encode()

        confirmation = FutureConfirmation(msg_id)
        self.future_confirmations.append(confirmation)
        await self.send_message(self.websocket, message)

        try:
            await asyncio.wait_for(confirmation, timeout=self.confirmation_timeout_s)
            self.future_confirmations.remove(confirmation)
            return confirmation.result(), "response received"

        except TimeoutError:
            self.logger.warning(f"Timeout when awaiting confirmation for message {msg}")
            self.future_confirmations.remove(confirmation)
            return False, "response timed out"

    def set_desired_current(self, current):
        """Records the wanted charging current. current_reconcile_loop applies it."""
        if current != self.desired_current:
            self.logger.info(f"Desired charging current set to {current}A.")
        self.desired_current = current

    async def apply_current(self, connectorId: int, current: int) -> bool:
        """Pushes a charging current to a connector that is already charging."""
        acked, why = await self.send_authorize_msg(current, "Start", connectorId)
        if acked:
            self.applied_current[connectorId] = current
            self.charging_since[connectorId] = time.time()
            self.logger.info(f"Applied {current}A to connector {connectorId}.")
        else:
            self.logger.warning(f"Could not apply {current}A to connector {connectorId}: {why}.")
        return acked

    async def reconcile_connector_current(self, connectorId: int):
        connector = self.charger_state.connectors[connectorId-1]

        if not connector.is_charging():
            self.applied_current.pop(connectorId, None)
            self.charging_since.pop(connectorId, None)
            self.stopping.discard(connectorId)
            return

        # We asked this connector to stop; re-sending Start would undo that.
        if connectorId in self.stopping:
            return

        if self.desired_current is None:
            return

        # Either a session that just began -- the charger acks the first Start
        # after a session ends but ignores the current in it, and sessions also
        # start on their own -- or a setpoint the user has changed since.
        if self.applied_current.get(connectorId) != self.desired_current:
            await self.apply_current(connectorId, self.desired_current)
            return

        # Being acked does not mean it was honoured. The setpoint is a ceiling,
        # so only an overshoot means anything: the car settles *below* the limit
        # by a margin that grows with it (8A -> 7.17A, 10A -> 8.88A measured), so
        # checking for equality would fire constantly.
        since = self.charging_since.get(connectorId)
        if since is None or time.time() - since < self.current_settle_s:
            return

        measured = connector.current.value
        if measured is not None and measured > self.desired_current + self.current_ceiling_margin_A:
            self.logger.warning(f"Connector {connectorId} draws {measured}A against a {self.desired_current}A limit, re-applying.")
            await self.apply_current(connectorId, self.desired_current)

    async def current_reconcile_loop(self):
        """Keeps the charging current at what was actually asked for.

        Runs as its own task rather than off a charger-state callback: applying
        a current waits for an Ack that only arrives through the read loop, so
        doing it inline would deadlock until that confirmation timed out.
        """
        try:
            while True:
                await asyncio.sleep(self.reconcile_period_s)
                try:
                    for connectorId in range(1, len(self.charger_state.connectors) + 1):
                        await self.reconcile_connector_current(connectorId)
                except Exception:
                    self.logger.exception("Failed to reconcile the charging current")

        except asyncio.CancelledError:
            self.logger.info("Current reconciliation loop cancelled.")
            raise

    async def start_charging(self, current: int, connectorId: int) -> bool:
        """Starts a session. Success means a session is running.

        It does *not* mean the session runs at `current`: the charger ignores
        the current in the first Start after a session ends. Getting the
        setpoint to stick is current_reconcile_loop's job.
        """
        self.set_desired_current(current)
        self.stopping.discard(connectorId)

        acked, why = await self.send_authorize_msg(current, "Start", connectorId)
        if not acked:
            self.logger.warning(f"Start command for connector {connectorId} was not accepted: {why}.")
            return False

        deadline = time.time() + self.charging_start_timeout_s
        while time.time() < deadline:
            if self.charger_state.connectors[connectorId-1].is_charging():
                return True
            await asyncio.sleep(0.5)

        self.logger.warning(f"Connector {connectorId} did not start charging within {self.charging_start_timeout_s}s.")
        return False

    async def stop_charging(self, connectorId: int) -> bool:
        connector = self.charger_state.connectors[connectorId-1]

        # Set before sending, so the reconciler cannot restart what we stop.
        self.stopping.add(connectorId)

        acked, why = await self.send_authorize_msg(connector.miniCurrent.value, "Stop", connectorId)
        if not acked:
            self.logger.warning(f"Stop command for connector {connectorId} was not accepted: {why}.")
            self.stopping.discard(connectorId)
            return False

        deadline = time.time() + self.charging_stop_timeout_s
        while time.time() < deadline:
            if not connector.is_charging():
                return True
            await asyncio.sleep(0.5)

        # Deliberately stays in self.stopping: charging is still running, and
        # restarting it because a Stop failed is the wrong way to be wrong.
        self.logger.warning(f"Connector {connectorId} did not stop charging within {self.charging_stop_timeout_s}s.")
        return False

    async def send_message(self, websocket, message):
        self.logger.debug(f">> {message}")
        await websocket.send(message)

    async def send_ack(self, websocket, uniqueId):
        msg = Ack(
                    chargeBoxSN = self.charge_box_serial,
                    uniqueId = int(uniqueId)
                )
        message = msg.encode()
        await self.send_message(websocket, message)

    async def process_message(self, websocket, message):
        """Handles a single message from the charger."""
        self.logger.debug(f"<< {message}")
        msg_json = json.loads(message)

        msg_serial = msg_json["payload"]["chargeBoxSN"]
        if msg_serial != self.charge_box_serial:
            self.logger.info(f"Ignoring message for a different charge box with SN{msg_serial} (expected SN{self.charge_box_serial}).")
            return

        # If it's an Ack message check if we're not expecting confirmation for a message
        if msg_json["messageTypeId"] == Ack.messageTypeId:
            for future_confirmation in self.future_confirmations:
                if future_confirmation.uniqueId == int(msg_json["uniqueId"]):
                    future_confirmation.set_result(msg_json["payload"]["result"])

        # Otherwise it's a payload message, send an ack for it and then process it
        else:
            asyncio.create_task(self.send_ack(websocket, msg_json["uniqueId"]))

            msg_parsed = parse_json(msg_json)
            if msg_parsed is not None:
                await self.charger_state.update(msg_parsed)

    async def watchdog_loop(self, websocket):
        """Closes the connection if the charger goes quiet.

        A charger that loses power or drops off the WiFi can leave the socket
        open from our side indefinitely. Nothing else notices: server_loop
        disables the websockets keepalive timeout with ping_timeout=inf, so
        this would only surface when TCP finally gives up, minutes later, with
        the UDP handshake never rebroadcast in the meantime.
        """
        try:
            while True:
                await asyncio.sleep(self.message_timeout_s / 2)
                silence_s = time.time() - self.last_message_time
                if silence_s > self.message_timeout_s:
                    self.logger.warning(f"Nothing from the charger for {silence_s:.0f}s, assuming the connection is dead.")
                    await websocket.close()
                    return

        except asyncio.CancelledError:
            raise

    async def process_websocket(self, websocket):
        """Handles messages from the connected charger."""
        watchdog_task = None
        try:
            if self.websocket is None:
                self.websocket = websocket
                self.connected_ws_evt.set()
                remote_ip, remote_port = websocket.remote_address
                self.logger.info(f"Connection established with {remote_ip}:{remote_port}!")

            self.last_message_time = time.time()
            watchdog_task = asyncio.create_task(self.watchdog_loop(websocket))

            async for message in websocket:
                self.last_message_time = time.time()
                try:
                    await self.process_message(websocket, message)
                except Exception:
                    # One unexpected message must never cost us the connection.
                    # The charger is the only source of data and it only
                    # reconnects after a fresh UDP handshake, so a dropped
                    # connection strands the integration until it is restarted.
                    self.logger.exception(f"Failed to process message {message}")

        except (websockets.exceptions.ConnectionClosed, ConnectionResetError) as e:
            self.logger.info(f"Websocket connection lost: {e}")

        finally:
            if watchdog_task is not None:
                watchdog_task.cancel()

            # Also reached on a clean close: the websockets async iterator
            # swallows ConnectionClosedOK and simply stops, so without this the
            # server would wait on disconnected_evt forever and never
            # rebroadcast the UDP handshake the charger needs to come back.
            if self.websocket is websocket:
                self.logger.info("Charger disconnected.")
                self.disconnected_evt.set()

    async def close_server(self, server):
        """Closes the WebSocket server without letting shutdown block forever.

        wait_closed() returns only once every connection handler has returned.
        During interpreter teardown those handlers have themselves been
        cancelled and it never returns, so an unbounded wait here is the
        difference between the process exiting and being SIGKILLed.
        """
        server.close()
        try:
            await asyncio.wait_for(asyncio.shield(server.wait_closed()),
                                   timeout=self.shutdown_timeout_s)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            self.logger.warning(f"WebSocket server did not close within {self.shutdown_timeout_s}s, abandoning it.")

    async def server_loop(self):
        """Starts the WebSocket server."""
        self.disconnected_evt = asyncio.Event()
        self.logger.info(f"Starting WebSocket server on {self.rcv_ip}:{self.rcv_port}")

        # Deliberately not `async with`: its __aexit__ waits on wait_closed()
        # unbounded, which is the thing that hangs shutdown.
        server = await websockets.serve(self.process_websocket, host=self.rcv_ip, port=self.rcv_port, ping_timeout=float("inf"))
        try:
            socket = server.sockets[0]
            self.rcv_port = (socket.getsockname()[1])
            self.rcv_port_evt.set()
            self.logger.info(f"Started WebSocket server on {self.rcv_ip}:{self.rcv_port}")

            self.logger.info("Waiting if server disconnects")
            await self.disconnected_evt.wait()

        except asyncio.CancelledError:
            self.logger.info("Server loop cancelled. Closing WebSocket server.")
            self.shutdown = True
            raise

        finally:
            self.websocket = None
            await self.close_server(server)

    async def udp_handshake_loop(self, ip_address, port):
        """Broadcasts UDP handshake messages until connected."""
        self.logger.info(f"Sending UDP broadcast handshake to {self.broadcast_ip}:{self.broadcast_port}.")

        send_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        send_sock.bind(('0.0.0.0', 3050))  # bind local port 3050
        send_sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)

        try:
            while self.websocket is None:

                msg = UDPHandShake(
                            timeout_time_unix = time.time() + self.udp_handshake_timeout_s,
                            chargeBoxSN = self.charge_box_serial,
                            ip_address = ip_address,
                            port = port
                        )

                message = msg.encode().encode("ASCII")
                self.logger.debug(f">>UDP {message}")
                send_sock.sendto(message, (self.broadcast_ip, self.broadcast_port))

                await asyncio.sleep(self.udp_handshake_timeout_s)

        except asyncio.CancelledError:
            self.logger.info("UDP handshake loop cancelled.")
            send_sock.close()
            raise

    async def handshake_loop(self, websocket):
        """Periodically sends WebSocket handshake to keep the connection alive."""

        try:
            while True:
                msg = HandShake(
                            current_time_unix = time.time(),
                            userId = self.user_id,
                            chargeBoxSN = self.charge_box_serial,
                            connectionKey = self.connection_key
                        )
                message = msg.encode()
                await self.send_message(websocket, message)
                await asyncio.sleep(self.handshake_period_s)

        except asyncio.CancelledError:
            self.logger.info("Handshake loop cancelled.")
            raise
    
    async def keyboard_loop(self):
        # TODO: fix
        while not self.charger_state.initialized():
            await asyncio.sleep(1)
        await asyncio.sleep(1.0)
        self.logger.info("Detected charger state initialized, starting charging!")

        desired_current = 6
        res = await self.start_charging(desired_current, 2)
        if not res:
            self.logger.info("Failed to start charging. Giving up.")
            return

        self.logger.info(f"Desired current ({desired_current}A) set, charging for 10s.")
        await asyncio.sleep(10.0)
        self.logger.info("Stopping charging!")

        res = await self.stop_charging(2)
        if not res:
            self.logger.info("Failed to start charging. Giving up.")
            return

        self.logger.info("Stopped charging!")

    async def main(self):
        while not self.shutdown:
            """Starts all tasks in the correct sequence."""
            self.rcv_port_evt = asyncio.Event()
            self.server_disconnected_evt = asyncio.Event()
            self.server_loop_task = asyncio.create_task(self.server_loop())
            self.loop_tasks.add(self.server_loop_task)

            self.logger.info("Waiting for WebSocket server initialization.")
            await self.rcv_port_evt.wait()

            self.connected_ws_evt = asyncio.Event()
            self.loop_tasks.add(asyncio.create_task(self.udp_handshake_loop(self.rcv_ip, self.rcv_port)))

            self.logger.info("Waiting for charger to connect to WebSocket.")
            await self.connected_ws_evt.wait()

            self.handshake_loop_task = asyncio.create_task(self.handshake_loop(self.websocket))
            self.loop_tasks.add(self.handshake_loop_task)

            self.reconcile_loop_task = asyncio.create_task(self.current_reconcile_loop())
            self.loop_tasks.add(self.reconcile_loop_task)

        # self.loop_tasks.add(asyncio.create_task(self.keyboard_loop()))

            await self.server_loop_task
            if self.shutdown:
                return

            for task in self.loop_tasks:
                task.cancel()


if __name__ == "__main__":
    if len(sys.argv) < 4:
        print("Please specify the charger serial number, this computer's IP address, and a serial port (\"auto\" to autoselect)!")
        exit(1)

    logger = logging.getLogger("S-Charge_server")
    logger.setLevel(logging.DEBUG)
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')

    fh = logging.FileHandler("/tmp/s-charge-server.log")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(formatter)
    logger.addHandler(fh)

    sh = logging.StreamHandler()
    sh.setLevel(logging.INFO)
    sh.setFormatter(formatter)
    logger.addHandler(sh)

    charge_box_serial = sys.argv[1]
    rcv_ip = sys.argv[2]
    rcv_port = sys.argv[3]
    if rcv_port == "auto":
        rcv_port = None
    s_charge_conn = SChargeConn(charge_box_serial, rcv_ip, rcv_port, logger=logger)
    try:
        asyncio.run(s_charge_conn.main())
    except KeyboardInterrupt:
        logger.info("Interrupted by user.")

    for handler in logger.handlers:
        handler.close()
        logger.removeFilter(handler)
