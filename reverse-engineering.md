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

## 5a. Setting the charging current — measured

Measured live on 2026-08-13 against connector 2 with a car attached, sending
`Authorize` with `purpose: "Start"` directly (raw data in
`artifacts/current_experiment.csv`).

**[confirmed] The first `Start` after a session ends ignores the requested
current.** From `chargeStatus: finish`, `Start` at 6 A was accepted
(`result=True`) and the car then drew **30.95 A / 21.2 kW** — full rate — for
the whole 75 s step.

**[confirmed] A `Start` re-sent during an active session does apply the
current.** Requesting 8 A while already charging moved the draw from 30.93 A to
7.17 A within about 4 seconds. Requesting 10 A then moved it to 8.88 A. This is
the mechanism behind "changing the charging current requires clicking the Charge
button again" in `known-issues.md`.

**[confirmed] `reserveCurrent` does not echo the requested current.** It stayed
`0` through every step, confirming it belongs to the scheduled-charging feature
(§4.4) and is useless for verifying a setpoint.

**[confirmed] The car draws less than the limit**, by a margin that grows with
the setpoint: 8 A → 7.17 A, 10 A → 8.88 A. So the `current_tolerance = 1.0` in
`start_charging` is too tight — at 10 A the deviation is 1.12 A and the retry
loop would fire even though the setpoint was applied correctly. Verifying a
setpoint against the *measured* current is unreliable in general; tracking the
last setpoint actually sent is the sounder approach.

**[confirmed]** `chargeStatus` values seen live across the run: `charging`,
`finish`, `wait`.

## 6. Electrical model

**[confirmed]** `evsePhase` is `threephase` and the reported per-connector voltage
is ≈406 V — line-to-line on a 400 V system, not phase-to-neutral.

**[confirmed] At full load, `P = √3 × V_LL × I` holds to 0.1 %**, so `current`
is a per-phase figure and `voltage` is line-to-line:

```
√3 × 394.41 V × 30.95 A = 21.141 kW      reported: 21.168 kW
```

This settles the old question of whether `current` was per-phase or a sum of
phases: it is per-phase.

**[confirmed] At partial load the relation breaks down, and not by a constant
factor.** Steady-state means over 25 samples per step:

| I | U | P reported | √3·U·I | ratio |
|---|---|---|---|---|
| 7.17 A | 410.29 V | 2.051 kW | 5.094 kW | 0.40 |
| 8.88 A | 408.75 V | 5.647 kW | 6.287 kW | 0.90 |
| 30.95 A | 394.41 V | 21.168 kW | 21.141 kW | 1.00 |

Current rises 24 % between the first two rows while power nearly triples. That
step is the non-linearity reported in `known-issues.md`.

**[untested] Which mechanism causes it is not resolved.** Two candidates fit the
shape but neither fits the numbers cleanly:

1. *Power factor* — real power is `√3 · U · I · cosφ`, and an onboard charger's
   cosφ improves with load. But cosφ jumping 0.40 → 0.90 across a 24 % load
   change is abrupt for a PFC-equipped charger.
2. *Phase count* — the car switching between single- and three-phase would give
   a genuine ~3× step. But a single-phase fit at 7.17 A predicts 1.70 kW against
   2.05 kW measured, and a three-phase fit at 8.88 A predicts 6.29 kW against
   5.65 kW measured.

The protocol only exposes one aggregate current per connector, so per-phase
currents would be needed to separate these — a clamp meter on the individual
phases would settle it in minutes.

**Practical consequence:** do not derive power from current. The reported
`power` is real power and is trustworthy; `√3 · U · I` is apparent power and
only coincides with it at full load. The supply also sags measurably under load
(410 V idle → 394 V at 21 kW), so voltage is not a constant either.

**[confirmed]** `meterInfo` is always `0.00` because no CT clamp is installed. The
fields are functional, not broken.

## 7. Open questions

| Question | How to settle it | Blocks |
|---|---|---|
| Why is power non-linear in current — power factor or phase count? | Clamp meter on the individual phases | issue 4 |
| Do `fault` and `reserve` really appear as `chargeStatus`? | Watch for the warning `_missing_` now logs | issue 1 |
| Why does the first `Start` after a session ignore the current? | Unknown; the workaround (re-send) is proven | issue 3 |

Settled by the 2026-08-13 measurements in §5a and §6: re-sending `Start`
mid-session does change the current, `reserveCurrent` does not echo the
request, and `current` is per-phase.

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
