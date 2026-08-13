# Known issues with this integration

Findings behind these, and the measurements that settled them, are in
[reverse-engineering.md](reverse-engineering.md).

## Open

* The charging power doesn't correspond to the charge current * voltage, and
  scales non-linearly with the reported charge current. Partly explained: the
  reported `current` is **per-phase** and `voltage` is line-to-line, so at full
  load `P = √3 × U × I` holds to 0.1% (measured: √3 × 394.41 V × 30.95 A =
  21.141 kW against 21.168 kW reported). At partial load the relation collapses
  and not by a constant factor — the ratio of reported power to `√3 × U × I`
  measured 0.40 at 7.17 A, 0.90 at 8.88 A and 1.00 at 30.95 A. Power factor and
  the car switching phase count both fit the shape but neither fits the numbers
  cleanly. A later run held 6.63 A at 0.01 kW, which no relation between the two
  survives at all.

  The protocol exposes only one aggregate current per connector, so this cannot
  be resolved from the wire; a clamp meter on the individual phases would settle
  it. **Practical upshot: use the reported `power`, never derive it from
  current.** The reported power is real power and is trustworthy.

## Fixed

* ~~Sometimes, the integration does not automatically connect to the charger and
  has to be restarted in order to connect.~~ Three separate paths left the
  server believing it was still connected while the UDP handshake was never
  rebroadcast: an exception from any single message escaped the read loop (a
  `fault` charge status was enough), a clean close went undetected because the
  websockets iterator swallows `ConnectionClosedOK`, and a charger that went
  silent was only noticed once TCP gave up minutes later. Message handling is
  now isolated per message, `disconnected_evt` fires from a `finally`, and a
  watchdog drops the connection after 30 s of silence — the charger sends a
  `Heartbeat` every ~12 s, so silence is a reliable signal.

* ~~The total charged energy seems to only update after terminating the charging.
  Calculating it dynamically during charging sometimes reduces the total, which
  should be monotonic.~~ `totalPower`, `chargeStatus` and `electricWork` arrive
  in three different messages with no ordering guarantee, so at a session
  boundary either order corrupted the sum — the status flipping first dropped
  the whole session, the total landing first counted it twice. The session is
  now anchored to the total observed when it started, and the result latched so
  it can never decrease.

* ~~Changing the charging current requires clicking the Charge button again, and
  charging that starts on its own doesn't respect the set current.~~ Measured:
  the charger acks the first `Start` after a session ends but ignores the
  current in it (a 6 A request ran at 30.95 A), while a `Start` re-sent during a
  session does apply it. A reconcile loop now re-applies the setpoint whenever a
  session begins or the setpoint changes. Verification is a ceiling check rather
  than equality — the car settles *below* the limit by a margin that grows with
  it, so the old 1 A tolerance reported failure for sessions that were running
  correctly.

* ~~The process hangs on shutdown and only stops when killed.~~ `server_loop`
  closed the WebSocket server through `wait_closed()`, which returns only once
  every connection handler has returned — during teardown those handlers have
  themselves been cancelled and it never returns. The wait is now bounded.
