# Reverse-engineering notes

What is actually known about the JNT-EVCD2-EU charger and the S-Charge protocol,
and how each fact was established. Written so that a future session does not
repeat work already done — including the dead ends.

Every claim is tagged:

- **[confirmed]** — directly observed, reproducible
- **[inferred]** — strong evidence, but one step removed from observation
- **[untested]** — hypothesis worth testing, not yet tested

---

## 1. Hardware

| | |
|---|---|
| Model | JNT-EVCD2-EU, Joint Tech / Joint Charging |
| Software version | `E3P3_H_1.1.1_R5190` (reported as `sVersion`) |
| Hardware version | `E3P3_V1.00` (reported as `hVersion`) |
| Connectors | 2 × Type 2 socket (`connectorMain`, `connectorVice`) |
| Rating | 2 × 22 kW, 64 A total across both sockets |
| Supply | 400 V AC three-phase (`evsePhase: "threephase"`) |

**[confirmed]** Versions and connector layout come from the charger's own
`DeviceData` message. **[inferred]** Ratings come from the vendor's published
specification for the EVC D2 line, not from the device.

The vendor advertises **OCPP 1.6J** for this product line. See §5 — we could not
find any way to reach it on this unit.

## 2. Network behaviour

**[confirmed]** The charger listens on **no TCP port at all**. A full scan of all
65535 ports returns only closed or filtered — nothing open:

```bash
nmap -Pn -p- --min-rate 3000 192.168.1.134
# All 65535 scanned ports are filtered (58351) or closed (7184)
```

Ports answer with RST rather than being dropped, so this is not a firewall
hiding services. Consequences: there is **no local web UI**, no telnet, no SSH,
and no configuration surface reachable over the LAN.

**[confirmed]** The charger is purely a **client**. It discovers a server via a
UDP broadcast to port 3050 and then opens a WebSocket *back* to the advertised
address. This is the mechanism `scharge_server.py` implements.

**[inferred]** No cloud connectivity. Observed by Wireshark before these notes
were written, and consistent with the app offering no remote functionality.
Not exhaustively verified — a capture taken on a LAN host cannot see charger →
internet traffic on a switched network, so a router-side capture would be needed
to state this with certainty.

**[confirmed]** There is **no AP mode**. The charger pairs with the app over
**Bluetooth LE**; the app's `WiFiConfig` string and its bundled `flutter_blue`
plugin corroborate BLE-based WiFi provisioning.

Net result: **every configuration path goes through the app**, over BLE for
provisioning and over the local WebSocket protocol thereafter.

## 3. The S-Charge app

| | |
|---|---|
| Package | `com.yill.s_charge` |
| Framework | Flutter (Dart AOT) |
| Notable libs | `flutter_blue` (BLE), Sentry (crash reporting) |

**[confirmed]** The app logic lives in `lib/arm64-v8a/libapp.so` (≈7.7 MB Dart AOT
snapshot). `classes.dex` holds only the Android shim and plugins.

**Consequence for future work:** jadx, apktool, and openjdk are of no use here —
they decompile the shim, not the protocol. Useful analysis is `strings` on
`libapp.so` plus the Flutter asset names. Going deeper means reversing the Dart
AOT snapshot (e.g. `blutter`), which was judged not worth the effort relative to
testing hypotheses directly against the charger.

```bash
unzip -o base.apk -d base                       # Android shim, plugins
unzip -o split_config.arm64_v8a.apk -d arm64    # the real payload
strings -n 4 arm64/lib/arm64-v8a/libapp.so > libapp.strings
```

The string pool is hash-ordered, so neighbouring strings are unrelated —
searching by vocabulary works, dumping surrounding lines does not.

## 4. Protocol findings

### 4.1 Message set

**[confirmed]** The app uses the same message set already implemented in
`src/messages.py` and `src/messages_rx.py`: `UDPHandShake`, `HandShake`, `Ack`,
`Authorize` (outgoing) and `DeviceData`, `SynchroStatus`, `SynchroData`,
`NWireToDics` (incoming).

**[confirmed]** There is one more incoming action the integration does not know
about — **`Heartbeat`**, observed in a live capture of 210 messages:

```json
{"messageTypeId":"5","uniqueId":"194375","action":"Heartbeat",
 "payload":{"chargeBoxSN":"2100322207300573"}}
```

It carries nothing but the serial and arrives roughly **every 12 s**.
`parse_json` returns `None` for it, so it is acked and then discarded, which is
harmless — but it is a free liveness signal. Heartbeats stopping is a much
faster and more reliable death detector than waiting for TCP to give up, which
is what the connection currently relies on (`ping_timeout=float("inf")` in
`server_loop` disables the websockets keepalive timeout).

Observed inbound mix over ~2 minutes idle: `DeviceData` 35, `SynchroStatus` 32,
`SynchroData` 19, `Heartbeat` 9, `NWireToDics` 1. Note `DeviceData` arrives
constantly — it is only the *value* of `totalPower` inside it that waits for a
session to end.

**[confirmed]** A sweep of the app's string pool for further action names found
nothing protocol-shaped — only Flutter framework classes and `WiFiConfig`. There
is **no hidden "set current" action**. Changing the current almost certainly means
re-sending `Authorize` with `purpose: "Start"`, which matches the observed
behaviour that pressing Charge again applies a new current.

### 4.2 `chargeStatus` values — important

**[inferred, high confidence]** `chargeStatus` takes at least six values:

```
idle    wait    charging    finish    fault    reserve
```

Evidence: the app ships one icon per state, and the three names that overlap with
known wire values match them exactly, so the other two follow the same pattern:

```
assets/charge-wait.png       assets/charge-charging.png   assets/charge-finish.png
assets/charge-fault.png      assets/charge-reserve.png
assets/charge-off.png        assets/charge-on.png          # device power, not chargeStatus
```

`idle` additionally appears in the string pool.

**This breaks the integration today.** `ChargeStatusEnum` in
`src/charger_state.py` defines only `wait`, `charging`, `finish`, `idle`. A
`fault` or `reserve` status raises `ValueError` inside `ChargerParam.update`,
which propagates out of `process_websocket` uncaught — permanently wedging the
connection until restart. See `known-issues.md` issue 1; this is one of its
confirmed root causes.

Treat the list as a lower bound, not a closed set. The parser should tolerate
unknown values rather than enumerate them — which is what `_missing_` on
`ChargeStatusEnum` now does.

A live capture of 210 messages with nothing plugged in showed only `idle` and
`finish`, so `fault` and `reserve` have still not been seen on the wire. They
remain inferred.

### 4.3 `electricWork` persists after a session ends

**[confirmed]** When a session finishes, `electricWork` keeps reporting that
session's energy — it is not cleared. Captured live with nothing plugged in:

```json
"connectorVice":{"voltage":"403.64","current":"0.00","power":"0.00",
                 "electricWork":"5.00","chargingTime":"2:33:15"}
```

with `chargeStatus` already `finish` and `totalPower` already grown to include
those 5 kWh. So `electricWork` may only ever be added to `totalPower` while
`chargeStatus` is `charging`; outside a session it is a stale leftover and
adding it would double-count. This is the mechanism behind the second entry in
`known-issues.md`, and it is why `ChargerState.total_charged_energy()` anchors
the session to the total observed when it *started*.

### 4.4 Scheduled charging ("reserve")

**[confirmed]** The app has a scheduled-charging feature. Its payload keys appear
in the string pool:

```
reservationId   reserveBegin   reserveEnd   reserveConnector   reserveCurrent
```

with UI text "Reserve to Charge", "Cancel Reservation", "Notice: Plug in the
connector, and wait to start at the reserved time".

**[untested]** Reservations are probably sent as `Authorize` with
`purpose: "Reserve"` — bare `Reserve` and `Reserved` sit in the string pool
alongside `Start` and `Stop`, and no separate action name exists.

**Correction to an earlier assumption:** `reserveCurrent` (present in
`SynchroStatus` and already parsed) belongs to *this* feature — the current for a
booked future session. It should **not** be assumed to be the live setpoint echo
for an active charge. Whether it also tracks the current requested by a normal
`Start` is **[untested]** and worth checking, since a real setpoint echo would be
a much better thing to verify against than the measured current.

## 5. OCPP — investigated and dropped

**[confirmed]** No way to point this unit at an OCPP backend was found:

- no OCPP settings in the app;
- no local web UI (no open TCP port);
- no AP-mode configuration page;
- no observed cloud connection that could be DNS-redirected.

**[inferred]** The firmware is probably an app/cloud SKU without a usable OCPP
client, despite the product line advertising OCPP 1.6J. The `H` in
`E3P3_H_1.1.1_R5190` may denote a home build. Untested route if this is ever
revisited: ask Joint Tech directly for the OCPP configuration procedure or
firmware, quoting model, serial, and firmware version.

`tools/` holds a permissive OCPP 1.6j probe server built during this
investigation. It is verified working against a simulated charge point and is
kept for the case where OCPP firmware becomes available. See `tools/README.md`.

## 6. Electrical model

**[confirmed]** `evsePhase` is `threephase` and the reported per-connector voltage
is ≈406 V — line-to-line on a 400 V system, not phase-to-neutral.

**[untested]** Therefore power should follow the three-phase relation rather than
a naive product:

```
P = √3 × V_LL × I ≈ 1.732 × 406 × I     →  16 A ≈ 11.3 kW
```

Two candidate readings of the reported `current` remain open, and a single log of
concurrent set-current / reported-current / voltage / power values distinguishes
them:

1. `current` is per-phase — the relation above applies directly;
2. `current` is the sum of all three phases — then `P = V_phase × I_sum`, which
   is numerically identical, and reported current will be ≈3× the set current.

**[untested]** The reported non-linearity of power against set current is not
explained by either. The most plausible cause is the vehicle switching between
single-phase and three-phase charging at some current threshold, which would put
a genuine 3× step in the ratio. Power factor and standby draw account for a few
percent at most.

**[confirmed]** `meterInfo` is always `0.00` because no CT clamp is installed. The
fields are functional, not broken.

## 7. Open questions

All of these need a car plugged in, so they need the owner present.

| Question | How to settle it | Blocks |
|---|---|---|
| Does re-sending `Authorize`/`Start` mid-session change the current? | Send it while charging, watch `current` | issue 3 |
| Does `reserveCurrent` echo a normal `Start` request? | Start at 10 A, read `SynchroStatus` | issue 3 |
| Is reported `current` per-phase or summed? | One log at 2–3 set currents | issue 4 |
| Why is power non-linear in set current? | Same log, plus the car's phase behaviour | issue 4 |
| Do `fault` and `reserve` really appear as `chargeStatus`? | Watch for the warning `_missing_` now logs | issue 1 |

Live reference values captured 2026-08-13, charger idle:
`totalPower` 57399 (573.99 kWh), `chargeTimes` 174, `loadbalance` 11700,
`rssi` -67, per-connector voltage 402.98 / 403.64 V.

## 8. Dead ends — do not repeat

- **Public documentation.** The S-Charge local protocol is undocumented. The only
  search hit anywhere is this repository.
- **jadx / apktool / openjdk on the APK.** Flutter app; they decompile the shim
  only.
- **Port scanning for a config UI.** Nothing is open; already scanned in full.
- **OCPP without vendor involvement.** No configuration surface exists on this
  firmware.
