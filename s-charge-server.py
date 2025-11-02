#!/usr/bin/env python3
import socket
import time
import sys
import ipaddress

import asyncio
from websockets import serve
import json

from messages import *
from messages_rx import *
from charger_state import ChargerState

class SChargeConn:

    def __init__(self, charge_box_serial, rcv_ip):
        self.websocket = None

        self.charge_box_serial = charge_box_serial
        self.user_id = 1
        self.connection_key = charge_box_serial

        self.charger_state = ChargerState(self.charge_box_serial)

        self.rcv_ip = rcv_ip

        # get the 24 subnet corresponding to the specified ip address
        ip_network = ipaddress.ip_network(rcv_ip).supernet(new_prefix=24)
        self.broadcast_ip = f"{ip_network.broadcast_address}"
        self.broadcast_port = 3050

        self.timeout_s = 1.9
        self.handshake_period_s = 7.0
        self.request_data_period_s = 0.3

        self.send_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.send_sock.bind(('0.0.0.0', 3050))  # bind local port 3050
        self.send_sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)

        self.loop_tasks = set()

    async def start_charging(self, current, connectorId):
        if self.websocket is None:
            return False, "not connected"

        if not self.charger_state.initialized():
            return False, "charger state not initialized"
        
        msg = Authorize(
                    current_time_unix = time.time(),
                    userId = self.user_id,
                    chargeBoxSN = self.charge_box_serial,
                    purpose = "Start",
                    current = current,
                    connectorId = connectorId
                )
        message = msg.encode()
        await self.send_message(self.websocket, message)
        return False, "not implemented"

    async def send_message(self, websocket, message):
        print(f">> {message}")
        await websocket.send(message)

    async def send_ack(self, websocket, uniqueId):
        msg = Ack(
                    chargeBoxSN = self.charge_box_serial,
                    uniqueId = int(uniqueId)
                )
        message = msg.encode()
        await self.send_message(websocket, message)

    async def process_websocket(self, websocket):
        """Handles messages from the connected charger."""
        if self.websocket is None:
            self.websocket = websocket
            self.connected_ws_fut.set_result(websocket)
            remote_ip, remote_port = websocket.remote_address
            print(f"Connection established with {remote_ip}:{remote_port}!")

        async for message in websocket:
            print(f"<< {message}")
            msg_json = json.loads(message)

            if msg_json["messageTypeId"] != "6":
                print("Got message, sending ack")
                asyncio.create_task(self.send_ack(websocket, msg_json["uniqueId"]))

            msg_parsed = parse_json(msg_json)
            if msg_parsed is not None:
                print(msg_parsed.payload_data)
                self.charger_state.update(msg_parsed)
                print(f"{self.charger_state}")

    async def server_loop(self):
        """Starts the WebSocket server."""
        async with serve(self.process_websocket, self.rcv_ip) as server:
            socket = server.sockets[0]
            rcv_port = (socket.getsockname()[1])
            self.rcv_port_fut.set_result(rcv_port)
            print(f"Started WebSocket server on {self.rcv_ip}:{rcv_port}")

            try:
                await asyncio.Future()  # run until cancelled

            except asyncio.CancelledError:
                print("Server loop cancelled. Closing WebSocket server.")
                server.close()
                await server.wait_closed()
                raise

    async def udp_handshake_loop(self, ip_address, port):
        """Broadcasts UDP handshake messages until connected."""
        print(f"Sending UDP broadcast handshake to {self.broadcast_ip}:{self.broadcast_port}.")

        try:
            while self.websocket is None:

                msg = UDPHandShake(
                            timeout_time_unix = time.time() + self.timeout_s,
                            chargeBoxSN = self.charge_box_serial,
                            ip_address = ip_address,
                            port = port
                        )

                message = msg.encode().encode("ASCII")
                print(f">> {message}")
                self.send_sock.sendto(message, (self.broadcast_ip, self.broadcast_port))

                await asyncio.sleep(self.timeout_s)

        except asyncio.CancelledError:
            print("UDP handshake loop cancelled.")
            raise

        finally:
            self.send_sock.close()

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
            print("Handshake loop cancelled.")
            raise

    async def main(self):
        """Starts all tasks in the correct sequence."""
        self.rcv_port_fut = asyncio.Future()
        self.loop_tasks.add(asyncio.create_task(self.server_loop()))

        print("Waiting for WebSocket server initialization.")
        await self.rcv_port_fut

        self.connected_ws_fut = asyncio.Future()
        rcv_port = self.rcv_port_fut.result()
        self.loop_tasks.add(asyncio.create_task(self.udp_handshake_loop(self.rcv_ip, rcv_port)))

        print("Waiting for charger to connect to WebSocket.")
        await self.connected_ws_fut

        websocket = self.connected_ws_fut.result()
        self.loop_tasks.add(asyncio.create_task(self.handshake_loop(websocket)))

        await asyncio.Future()


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Please specify the charger serial number and this computer's IP address!")
        exit(1)

    charge_box_serial = sys.argv[1]
    rcv_ip = sys.argv[2]
    s_charge_conn = SChargeConn(charge_box_serial, rcv_ip)
    try:
        asyncio.run(s_charge_conn.main())
    except KeyboardInterrupt:
        print("Interrupted by user.")
