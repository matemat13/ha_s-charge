# OCPP investigation tools

The charger is specced for **OCPP 1.6J** ([EVC D2 spec](https://evcharger.wiki/page/Joint_EVC_D2_EU_64A_With_Dual_T2_Socket)).
If we can get it to speak OCPP, remote current control becomes a documented
`SetChargingProfile` call instead of a re-sent `Authorize`, which would fix the
"changing current requires clicking Charge again" problem properly.

These tools exist to answer one question: **will this charger talk OCPP, and to
whom?**

## The actual blocker

`ocpp_probe.py` is the easy half. The hard half is that nothing yet tells the
charger where an OCPP server lives. A central system — this probe, or the HACS
`ocpp` integration — only *listens*; the charge point is the WebSocket client
and must be configured with a backend URL. Standing up a listener and waiting
will never produce a connection on its own.

So the OCPP URL setting has to be found first. It lives in one of three places:

1. **The S-Charge app** — an advanced/engineering menu. Nothing public documents
   one for this app, but most chargers in this class have it.
2. **A local web UI or AP-mode setup page** — the charger may broadcast its own
   SSID, with a config page at something like `http://10.10.10.1`. This is the
   usual pattern for chargers on this kind of Chinese firmware.
3. **The proprietary protocol itself** — the app may configure it over the same
   WebSocket link this repo already reverse-engineers. Note that
   `messages_rx.parse_json` silently drops every action it doesn't recognise, so
   the charger may already be sending relevant messages we throw away.

Worth checking before any of that: whether the charger is *already* speaking
OCPP outbound to a vendor cloud. If it is and the connection is plaintext `ws://`,
a local DNS override pointing that hostname at Home Assistant is the shortest
path to a working setup, with no charger-side config needed at all.

## `ocpp_probe.py` — a permissive central system

A deliberately forgiving OCPP 1.6j server that logs everything. It is a better
*first* test than the HACS integration because it removes the variables you
can't yet control:

| | HACS `ocpp` | this probe |
|---|---|---|
| charge point identity | must be agreed up front | any path accepted, logged |
| subprotocol | must match | echoes back whatever is offered |
| schema validation | on by default, drops the connection | never validates |
| unknown actions | `CALLERROR` | empty result, logged loudly |
| failed handshakes | buried in HA logs | logged with full headers |

```bash
source scharge_venv/bin/activate
./tools/ocpp_probe.py --port 9000 --log /tmp/ocpp-probe.log
```

Then point the charger at `ws://<host>:9000/<anything>`. On connection it logs
the request path, every header, and the negotiated subprotocol, then answers
`BootNotification` and immediately asks the charger to dump its whole
configuration — which is what tells us whether smart charging is supported.

With a terminal attached, type `help` for interactive commands (`getconf`,
`current 16`, `start`, `stop`, `trigger`, `reset`, `raw`). The two that matter
most:

- `getconf` — look for `SupportedFeatureProfiles` containing `SmartCharging`,
  and for `ChargingScheduleAllowedChargingRateUnit`.
- `current 16` — a `SetChargingProfile`. If this is accepted and the car's draw
  actually changes, OCPP solves the current-control problem.

## `fake_charge_point.py` — verifies the probe

Simulates a charge point so you can confirm the probe works before involving
real hardware.

```bash
./tools/ocpp_probe.py --port 9010 --set-current 13     # terminal 1
./tools/fake_charge_point.py --port 9010               # terminal 2
```

Checks the handshake, `BootNotification`, the automatic `GetConfiguration`,
`SetChargingProfile` on transaction start, and that malformed frames don't take
the connection down. Prints `PASS`/`FAIL`.

## Caveat before switching the charger over

A charger generally talks to *one* backend. Pointing this one at a private OCPP
server may disconnect it from the S-Charge cloud and break the app — and
possibly the local protocol this repo depends on. Find out how to reverse the
setting before applying it.
