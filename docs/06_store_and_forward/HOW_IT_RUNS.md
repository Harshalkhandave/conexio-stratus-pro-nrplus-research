# How `06_store` actually runs

This is a walk through the firmware in the order the CPU executes it, then the same code again for each real situation (one board, two boards, a relay, a dead peer, a full queue, a reboot). Times below are the **defaults** from `Kconfig` unless a line says `exp sett`.

The short companion is [`IMPLEMENTATION.md`](IMPLEMENTATION.md). This file is the one to read when you want to know which function runs next and why the radio waited.

## 1. One picture

Think of a single walkie-talkie in a hallway.

The nRF9151 has one DECT radio. It can talk or it can listen. It cannot do both at once. That is half-duplex, the same rule as a push-to-talk radio: while you hold the button, you are deaf.

So the firmware is one person holding that radio:

1. Decide the next thing to say, or decide to listen for a fixed number of milliseconds.
2. Hand that job to the modem and **wait** until the modem says the job finished.
3. If something was heard during the listen, deal with it.
4. Go back to step 1.

That person is `radio_thread` in `src/main.c`. Nobody else is allowed to press the button.

Custody is a separate idea, like a signed parcel. When B accepts A's parcel, B signs for it (`ACK ACCEPTED`). A may then throw away its copy. If the truck crashes before B signs, A still has the parcel and tries again. The signature is the ACK. The shelf in the post office is the RAM store.

## 2. Who runs, and what silicon they touch

| Thread | Priority | What it may touch | What it must not do |
|---|---|---|---|
| `main` | Zephyr main, priority 0, runs `main()` then exits the function | Modem init, settings flash at boot | Transmit |
| `sf_radio` | priority 5, stack 8192 bytes | `nrf_modem_dect_phy_tx` / `rx`, the store, the link table | Overlap a TX with an RX |
| Modem library callback | Modem's own context, not our thread | Copy the received bytes into `sf_rxq`, give `op_sem` | Look at the store, log a lot, or block |
| Shell (`exp`) | Shell thread, stack 3072 bytes | Read and change RAM settings, `settings_save_one` for `exp save` | Call the modem |
| Log thread | Deferred log, 32 KB buffer | UART | — |

The mutex `sf_lock` is the door to the store and the link table. The radio thread holds it only while it is deciding (`sf_node_poll`) or folding in a received frame (`sf_node_on_rx`). It **drops the lock before** it asks the modem to transmit or listen, and it waits on `op_sem` with the lock released. That is why `exp status` still answers during a 200 ms ACK wait.

The modem callback never takes `sf_lock`. It copies the frame into a static buffer under a short spinlock and pushes that copy onto `sf_rxq`. The pointer the modem passed is only valid until the callback returns. If we read it later, we would be reading memory the modem has already reused.

## 3. Time, from the metal up

The modem does not count milliseconds. It counts its own ticks.

```text
NRF_MODEM_DECT_MODEM_TIME_TICK_RATE_KHZ = 69120
```

That is 69.12 million ticks per second. One tick is about 14.5 nanoseconds. The firmware converts a millisecond like this, in `receive()`:

```text
duration_ticks = milliseconds * 69120
```

A listen of `rx_slice` = 15 ms is 15 × 69120 = 1,036,800 ticks. The same formula is what Nordic's own DECT samples use (`seconds * 1000 * 69120`).

One DECT symbol is `NRF_MODEM_DECT_SYMBOL_DURATION` = 2880 ticks.

```text
2880 / 69120 ms = 0.0417 ms = 41.7 microseconds
```

Before every transmit the modem also does listen-before-talk (LBT). We ask for the longest legal check:

```text
LBT = 110 symbols * 2880 ticks = 316,800 ticks ≈ 4.6 ms
```

LBT is the radio sniffing the channel before it speaks, the way you glance down a hallway before you step out. The threshold in the TX request is `lbt_rssi_threshold_max = 0` (dBm). The measured energy must be below that for the channel to count as free. If the hallway is already loud, the modem returns `LBT_CHANNEL_BUSY` (error 1) and **does not transmit**. The firmware treats that as a failed attempt, not as "the frame went out."

Propagation is not what you are tuning. Light and radio travel at 3×10^8 m/s. Across a 30 m room the one-way delay is 30 / 3×10^8 = 0.1 microseconds. Our shortest deliberate wait is 15 milliseconds, about 150,000 times longer. When an ACK is "late," the cause is the other board still being in its own listen slice or its own transmit, not the distance.

RSSI is received power in dBm. The modem reports it as `rssi_2` in half-dB steps (the log line divides by 2). Every −3 dB is half the power. −40 dBm is very strong (boards on the same bench). −75 dBm is a normal indoor hop. −100 dBm is close to where the packet stops decoding. `rssi_level = -60` in the RX request is only a hint to the modem's gain control for the first slot. It is not a filter. We still accept a packet at −90 dBm.

`power` on the shell is not dBm. It is the 4-bit index written into the PHY header (0..13). The hardware tops out near 19 dBm. `mcs` chooses how many bits ride on each symbol. MCS 0 is the slow, robust mode used in the 05_performance measurements. Higher MCS is shorter on the air and needs a cleaner signal. This image does not compute airtime from MCS. The waits below are software timers, and they must be longer than LBT plus the on-air frame plus the peer's reaction.

Rough on-air cost of one transmit, MCS 0, default sizes:

| Frame | Bytes | What you should budget |
|---|---|---|
| HELLO | 18 | LBT ~4.6 ms + a short frame, well under 10 ms |
| ACK | 21 | same |
| PROBE | 16 | same |
| DATA, `size 64` | 80 (16 header + 64) | LBT ~4.6 ms + a longer frame, still a few milliseconds |

The 200 ms ACK window is not the airtime. It is how long we are willing to stay deaf to our own next transmit while we wait for the other board to notice, finish its current listen, and answer.

## 4. Boot, function by function

`main()` in `src/main.c`.

1. `read_device_id()` reads two bytes from `hwinfo_get_device_id` into a `uint16_t`. That is the same read `03_topology` uses, so a board that was 14402 stays 14402. `0` and `65535` are reserved and become `1` with a warning. `SF_DEVICE_ID_OVERRIDE` skips the hardware read.
2. `sf_port_boot(id)` in `sf_port.c`:
   - `fill_kconfig()` copies every default into RAM (`role`, `interval_ms` = 1000, `ack_timeout_ms` = 200, `assume_up` = 0, `direct_fallback` = 1, …).
   - `sf_persist_init()` then `settings_load()` reads flash.
   - `sf_persist_boot_epoch()` adds 1 to the stored epoch and writes it back **before any radio**. First boot mixes the CPU cycle counter into the epoch. If this is boot number 6 or more without a long healthy run, `main`'s caller sleeps `delay_ms` here. The shell is already alive during that sleep. The radio is not.
   - If `sf/cfg` is a sane profile, those fields replace the Kconfig defaults. `node_id` and `phy_mtu` are put back so a saved profile cannot change identity or the frame ceiling.
   - `init_store()` points the store at the static arrays: 320 slots × 64 byte payload, 32 of those slots reserved for alarms. Nothing is malloc'd.
   - `sf_node_init()` copies the config into the node. Sequence counters start at 0. No link exists yet.
3. `boot_phy()`:
   - `nrf_modem_lib_init()` starts the modem library.
   - `nrf_modem_dect_phy_event_handler_set(dect_phy_event_handler)` registers the callback.
   - `nrf_modem_dect_phy_init()`, then `k_sem_take(op_sem, K_FOREVER)` until the callback runs `on_init` and gives the semaphore. `phy_fatal` aborts the boot.
   - `nrf_modem_dect_phy_configure()`. Band group is 1 only when the carrier is 525..551. Carrier 1711 (US overlay) is outside that range, so band group is 0, the ~2 GHz group. HARQ RX processes = 4, expiry 5 seconds. We do not use modem HARQ for the application ACK. The application ACK is our own frame.
   - `nrf_modem_dect_phy_activate(LOW_LATENCY)`. Same wait.
4. `k_thread_create` starts `sf_radio` at priority 5. The thread immediately blocks in `sf_port_wait_until_started()` on `sf_run_sem`.
5. If the profile says autostart and a source has a destination, `sf_port_start(0)` runs. Otherwise the log says `idle — exp start` and the radio thread stays parked. No carrier energy yet.

`exp start` from the shell calls `sf_port_start`, which calls `sf_node_start` under the lock, then `k_sem_give(sf_run_sem)`. `sf_node_start` drops anything left in the store (`FLUSH reason=start`), zeroes counters, and sets `running`. It does **not** zero the sequence. Only a reboot changes the epoch, which is how peers notice a restart.

## 5. The loop that never ends

`radio_thread`:

```text
wait until exp start
while running:
    sf_port_note_stable_if_due()     once, after 300 s of this run, clears the boot counter in flash
    sf_port_poll()                   decide TX or RX, lock held only inside this call
    if stopped: leave the loop
    if TX:
        copy the frame into buf[] on this stack
        nrf_modem_dect_phy_tx()
        wait_op()                    blocks until the modem callback gives op_sem, or 2000 ms
        sf_port_on_tx_done(ok?)
    else:
        nrf_modem_dect_phy_rx(duration)
        wait_op()
        sf_port_drain_rx()           for each queued PDC, sf_node_on_rx
```

`wait_op` is the bare-metal handshake. The modem finishes in its own context, writes `op_result`, and gives `op_sem`. Success is error 0 or `OK_WITH_HARQ_RESET` (6). Anything else, including LBT busy (1), is a failed operation. If 2000 ms (`SF_OP_TIMEOUT_MS`) pass with no callback, we call `nrf_modem_dect_phy_cancel` and stop the run with `modem_timeout`. That 2000 ms is a hang guard, not the ACK timer.

`buf[]` and the PHY header live in `radio_thread`'s stack until `wait_op` returns. The modem reads them while the operation is in flight. The 8192 byte stack exists so this buffer, a second copy inside `sf_action`, and the log call all fit.

CPU time inside `sf_node_poll` is microseconds. The milliseconds you see are the modem operations that follow the decision.

## 6. What `sf_node_poll` decides

Every pass starts by doing bookkeeping, then returns **exactly one** action. The first match wins.

| Order | Condition | Action | How long the radio then spends |
|---|---|---|---|
| 0 | Source has sent `count` packets, store empty, nothing in flight | `sf_node_stop` → `SUMMARY`, then a short listen | one `rx_slice` (15 ms) and the thread leaves the run |
| 1 | An ACK is waiting in `ackq` | Transmit that ACK. `inflight` flag is false | LBT ~4.6 ms + ACK on air. Then `gap` (20 ms) of extra listen |
| 2 | A frame is in flight and backoff has not elapsed | Listen until backoff ends | `backoff` ms, default 10..20 on the first retry |
| 3 | ACK deadline has passed | `RETRY`, or if this was attempt 4, link `DOWN` | see scenario C |
| 4 | A frame is in flight and the deadline is in the future | Listen for the remaining ACK time | up to `ack_timeout` (200 ms) |
| 5 | `gap_until` is in the future | Listen for the rest of the gap | up to `gap` (20 ms) |
| 6 | This role sends HELLO and the period has elapsed | Transmit HELLO | LBT + HELLO, then 20 ms gap |
| 7 | Some link is `PROBING` and `next_probe_ms` has passed | Transmit PROBE | LBT + PROBE, then up to 200 ms ACK wait |
| 8 | Store has a frame, its link is `UP`, class is not in holdoff | Transmit DATA | LBT + DATA, then up to 200 ms ACK wait |
| 9 | Nothing else | Listen `rx_slice` | 15 ms |

HELLO period default is 2000 ms, jittered to about 1800..2200 ms (`jittered()`: ±10 %). A source does not send HELLO unless `exp sett hello_tx on`. A relay and a sink do, unless `hello_tx off` or `hello 0`.

Generation is not a transmit. `maybe_generate` runs at the top of the poll. If `interval` has elapsed (default 1000 ms) and the source has not hit `count`, it builds one frame and `put`s it in the store. The transmit happens later, on line 8, and only if the link is `UP`. `interval 0` means "do not generate." That is different from `03_topology`.

## 7. What a received frame does

During the listen, the modem calls `dect_phy_event_handler` → `on_pdc` → `sf_port_on_pdc`. That only enqueues. After the listen ends, `sf_port_drain_rx` calls `sf_node_on_rx` for each copy.

`sf_node_on_rx` decodes with `sf_codec_decode` (no struct cast). Then:

| Type | Path |
|---|---|
| Bad version, `SEC=1`, truncated, unknown type | `BAD_FRAME`, counter `rx_bad_hdr`, no answer |
| HELLO | Remember the sender in the neighbour table. If we already have a link to that id, mark `heard_hello`. Do not go `UP` |
| PROBE whose `next` is us | Queue `ACK` status `PROBE_REPLY`. It goes out on the next poll, ahead of any DATA |
| PROBE for someone else | `rx_not_mine` |
| ACK | `handle_ack`. Must match the one frame we have in flight (`prev`, `src`, `epoch`, `seq`, `class`). Otherwise `rx_stale_ack` and we ignore it |
| DATA whose `next` is not us | `rx_not_mine`. A sink that overhears "A talking to the relay" does not deliver it |
| DATA whose `next` is us and `dst` is us | Deliver, then ACK `ACCEPTED`. The sink does not store it |
| DATA whose `next` is us, `dst` is someone else, we are a relay | Store a rewritten copy, then ACK `ACCEPTED` only if `put` returned 0 |

Dedup runs before the store. Same `(src, class, epoch)` and a sequence that is not newer: ACK `DUPLICATE`, do not deliver again. A newer epoch: log `SRC_RESET` and accept. An older epoch: ACK `DUPLICATE` and count `rx_stale_epoch`.

The rewritten relay copy changes only the hop fields: `prev` becomes us, `next` becomes the route (or `dst` if `direct` is on), `hops` increments, `ttl` decrements. `src`, `seq`, `epoch`, and the payload stay as the originator wrote them.

## 8. Scenarios

### A. Idle, nothing started

`sf_radio` is blocked on `sf_run_sem`. The modem is active and quiet. `exp status` takes `sf_lock`, prints, releases it. No carrier activity. Time in this state: as long as you like. Cost: the modem is on, but it is not in an RX or TX operation.

### B. One board, role sink, `exp start`

Poll line 6. First HELLO goes out within one 15 ms listen (the first poll sees `next_hello_ms` already due). Then the thread listens 15 ms slices until about 2 s have passed, then another HELLO.

You adjust the cadence with `exp sett hello <ms>`. `hello 0` or `hello_tx off` stops them. This does not prove a second board can hear you. It proves our TX path and the scheduler.

### C. One board, role source, `assume_up on`, nobody answers

`assume_up on` creates the link already `UP`, so poll line 8 transmits DATA on the first poll that has a stored frame.

Timeline for one packet, defaults, no peer:

```text
t=0        put into store, TX DATA (LBT ~5 ms + frame)
t≈5 ms     on_tx_done(ok): deadline = now + 200 ms
t=5..205   listen for an ACK. None arrives
t=205      service_timeout: attempt becomes 2, RETRY, backoff 10..20 ms
t=205..220 listen during backoff
t=220      TX same bytes, RETX bit set
...        attempts 3 and 4 the same way
t≈0.9 s    attempt 4 also times out
           sf_link_fail: LINK_STATE new=DOWN reason=max_attempts
           frame stays in the store
           hold-down 5 s, then a probe is allowed
```

Four transmits because `attempts` default is 4 (the first send counts). Backoff for attempt 2 is uniform between `backoff_min` (10) and `backoff_max` (20). Each later retry doubles that window until `backoff_cap` (80). So the gaps are about 10–20 ms, then up to 40, then up to 80, plus 200 ms of deaf waiting after each transmit.

If you want a one-board test to finish faster:

```text
exp sett ack_timeout 50
exp sett attempts 2
exp sett backoff_min 0
exp sett backoff_max 0
```

Do not use those numbers against a real peer. 50 ms is shorter than a peer that is itself waiting on someone else.

`exp stop` during the 200 ms listen returns when that listen ends, not instantly. Worst case is one `ack_timeout`.

### D. Two boards, direct, the happy path

A is source, `dest` = C's id, `direct` on (the default), so `next` on the air is C. C is sink.

With `assume_up off` (the default), A does not send DATA first. `sf_link_ensure` creates the link `DOWN` with `hold_until = now`, and `sf_link_tick` immediately promotes it to `PROBING` because the hold has already expired and the probe timer is due. Poll line 7 sends a PROBE.

C hears it inside its current 15 ms slice, queues `PROBE_REPLY`, and the next poll sends that ACK before anything else. A must see it inside the 200 ms window. `sf_link_probe_ok` increments `consec`. `n_up` is 3, and `probe_fast` is 200 ms between successes. Three good replies take on the order of 3 × 200 ms ≈ 0.6 s, plus each reply's airtime. Then the log says `LINK_STATE ... new=UP reason=probes`.

Only then does line 8 send DATA. C's `handle_data` sees `next == C` and `dst == C`, delivers, commits dedup, queues `ACCEPTED`. A's `handle_ack` matches the in-flight frame, `sf_store_pop_order` deletes it, `drained_total` increments, and a 20 ms `gap` listen follows so C can still push something at A.

End-to-end software budget for one DATA after the link is already up:

```text
A: LBT+TX           ~5 ms
A: ACK window       up to 200 ms, typically ends when the ACK arrives
C: rest of rx_slice up to 15 ms
C: LBT+ACK          ~5 ms
A: gap              20 ms
```

A healthy bench RTT is usually a few tens of milliseconds, dominated by C's 15 ms slice, not by the flight of the wave. If your measured `rtt_ms` on `ACK_RX` is consistently under 40, you can try `exp sett ack_timeout 80` and `exp sett rx_slice 10`. If you then see `reason=max_attempts` on a link that is sitting on the desk, put the timeout back.

`exp sett assume_up on` on both sides skips the 0.6 s of probes. Use that only when you already trust the channel. The spec's rule, and the default, is "do not call the link up until it has answered three times."

### E. Three boards, A → B → C

A has `direct off` and `exp route set <C's id> <B's id>`. A's frames have `next=B`, `dst=C`.

B is a relay. It does not generate. On DATA with `next=B` and `dst=C` it stores an outbound copy (`next` becomes C, because B's `direct` is on) and ACKs A. That ACK is poll line 1, so it goes out before B forwards.

B then has its own link to C. If that link is still `PROBING`, B probes C before it forwards. A's packet sits in B's store the whole time. A has already deleted its copy, because B signed for it. That is custody: the parcel is B's problem now.

C delivers when B's forward arrives with `next=C`. C does not deliver A's original transmission, because that frame's `next` was B. This is why a blocked direct path does not show up as a second delivery.

The expensive case: B is in its own 200 ms ACK wait toward C when A's next frame arrives. B cannot answer A until that wait ends. A's `ack_timeout` must be longer than B's. With both set to 200 ms, A can time out once and retry. That retry is correct, not a bug. If you see a `RETRY` on every packet in a healthy 2-hop setup, raise A's `ack_timeout` (try 400) or lower `rx_slice` on B and C.

### F. The relay shelf is full

Telemetry may use 320 − 32 = 288 small slots. At `interval 1000` that is about 288 seconds of backlog.

When B cannot `put`, it ACKs `QUEUE_FULL` and does **not** advance dedup, so A's retry is still "new." A' s `handle_ack` does not pop. It sets `holdoff_ms` for that class to `nack_holdoff` (1000 ms). If `queue_free` in the ACK is 0, the holdoff doubles to 2000 ms. During holdoff, poll line 8 will not transmit that class. The frame stays at the head of A's store.

`exp sett policy drop_oldest` on B is the other policy. B deletes its oldest telemetry (and logs `CUSTODY_BROKEN`) to make a hole, then accepts the new one. Those dropped sequences will be missing at C on purpose. Alarm frames never take that path. They can also use the 32 reserved slots, so a full telemetry shelf can still accept an alarm.

`exp sett nack_holdoff 200` makes a full peer retry sooner. Too small and you hammer a board that is already full.

### G. The peer was alive, then left

Two different detectors:

- Four failed DATA or PROBE attempts: `sf_link_fail`, reason `max_attempts`. First hold-down is `hold_min` = 5 s. A second failure before the link has been `UP` for `hold_reset` (60 s) doubles it (10 s, 20 s, …) up to `hold_max` (60 s). `next_probe_ms` is hold-down plus `t_probe` (3 s). So the first recovery probe is about 8 s after the link dies.
- HELLO silence: only if this neighbour has sent us at least one HELLO, and then nothing for `hello_dead` (7 s). A source that never sends HELLO cannot be killed this way. That is deliberate.

While `DOWN`, new source frames still enter the store. They do not go on the air. When the peer returns, HELLO or the probe timer moves the link to `PROBING`, three probe replies move it to `UP`, and the backlog drains oldest-alarm-first, then oldest telemetry. `tel_ttl` (600 s) deletes telemetry that sat longer than that. `tel_ttl 0` keeps it until the pool is full.

`exp sett hold_min 0` and `exp sett t_probe 0` make recovery aggressive. You will also flap if the channel is merely noisy. `exp sett hello_dead 0` disables the HELLO silence detector.

### H. Someone reboots

Boot reads the epoch, adds one, writes it back, then the radio starts. The other boards see the new epoch on HELLO, PROBE, or ACK (`node_epoch`). `note_neighbor` logs `NEIGHBOR_RESET` and `sf_link_force_probe` jumps that link to `PROBING` even if hold-down has not finished. Their queue was RAM. It is gone. Probing again is how we find out.

Frames we had already accepted and not yet forwarded are gone with the RAM. The sink later sees a hole in the sequence and logs `RX_GAP`. That hole is the declared loss. Frames still at the previous hop were never ACKed, so that hop still has them and will send them after the link returns.

Five boots in a row without a run that lasts `SF_BOOT_STABLE_S` (300 s) delay the next radio start by 2, 4, 8, … seconds, capped at 60. The shell works during the delay. `exp factory` deletes the profile and does not touch the epoch. Resetting the epoch would make the new life look like a continuation of the old sequence numbers.

## 9. Knob, symptom, and when to turn it

All of these are `exp sett <key> <value>` unless the row says Kconfig. Kconfig is the value after a fresh boot with no profile. `exp save` keeps the shell value across reset.

| Knob | Default | Turn it down when | Turn it up when | If it is wrong |
|---|---|---|---|---|
| `rx_slice` | 15 ms | You need a faster ACK on an idle sink | The log shows `rx operation failed` (slice too short for the modem) | Too long: every ACK waits up to this long. Too short: the modem rejects the listen |
| `ack_timeout` | 200 ms | Measured `rtt_ms` is far below it and you want less deaf time | You see `max_attempts` on a link that is actually up, especially 2-hop | Too short: false `DOWN`, frames stuck. Too long: a dead peer blocks the radio for `attempts × timeout` |
| `attempts` | 4 | One-board smoke test | The channel drops single frames but recovers | Too small: one fade kills the link. Too large: a dead peer occupies the radio for a long time |
| `backoff_min` / `max` / `cap` | 10 / 20 / 80 ms | You want retries back-to-back (`0`) | Several boards collide | Zero backoff makes two boards retry in lockstep |
| `gap` | 20 ms | You are chasing minimum latency on a quiet 1-hop | A peer's ACK often lands just after you started your next TX | Too small: you step on the peer's answer |
| `hello` | 2000 ms | You want faster "I am here" | You want less airtime | `0` disables HELLO. Then only probes detect a dead next hop |
| `hello_dead` | 7000 ms | You want a silent neighbour declared dead sooner | HELLO is jittery and you get false `DOWN` | `0` disables this detector. Keep it ≥ 3 × `hello` |
| `t_probe` | 3000 ms | You want to rediscover a peer sooner after hold-down | Probes are wasting air while the peer is truly gone | `0` probes as soon as hold-down ends |
| `probe_fast` | 200 ms | Bring-up, you want `UP` in under a second | The channel is marginal and three fast probes are luck | Too fast: `UP` on a link that cannot carry DATA |
| `n_up` | 3 | `assume_up` is off and you accept one reply as proof | You want a stricter gate | 1 is almost `assume_up`, but still one real answer |
| `hold_min` / `hold_max` | 5 s / 60 s | Lab, you want the next probe quickly | The link is flapping | 0 retries immediately and can livelock a noisy channel |
| `hold_reset` | 60 s | — | A brief `UP` should not forgive a long flap history | How long `UP` must last before the next failure starts the hold-down back at `hold_min` |
| `interval` | 1000 ms | Throughput experiments | The sink or the store cannot keep up | `0` generates nothing. This is not "as fast as possible" |
| `count` | 0 | A finite run | — | 0 means until `exp stop`. `exp start 10` overrides it for that run only |
| `nack_holdoff` | 1000 ms | You want a full peer retried quickly | The peer is full and you are adding load | Doubles automatically when `queue_free` is 0 |
| `tel_ttl` | 600000 ms | Stale telemetry should die in the store | A long outage must still drain | `0` means never expire |
| `size` | 16 bytes on this bench | — | You need a bigger payload | Payload only. The frame is `size+16`. Stay at 16 until DATA ignores modem slot padding (see §10). Above 64 also needs `CONFIG_SF_LARGE_SLOTS` or a bigger `SF_SMALL_PAYLOAD`, then a rebuild |
| `power` | 10 (overlay) | Boards are on the same desk and you want less splash into other tests | The hop is weak (`RSSI` near −100, retries) | Index 0..13, not dBm |
| `mcs` | 0 | The link is weak | You have SNR to spare and want shorter frames | This image does not retune the ACK timer when you change MCS |
| `assume_up` | off | — | You are on the bench and you do not want the probe gate | On: DATA before anyone has answered. Off: three probes first |
| `direct` | on | A must go through a relay (`exp route set`) | 1-hop, `next` should equal `dest` | On with no route: `next = dest`. Off with no route: `NO_ROUTE`, frame stays, holdoff |
| `ttl` | 5 | — | A longer chain | A relay that would forward with no hops left ACKs `TTL_EXPIRED` and the sender deletes the frame. That loss is declared |
| `policy` | reject | — | You would rather drop old telemetry than refuse new | `drop_oldest` logs `CUSTODY_BROKEN` |
| `hello_tx` | auto | A source should also beacon | A sink should be silent | `auto`: relay and sink hello, source does not |
| `dedup` | on | You are deliberately testing double delivery | — | Off delivers every copy. Leave it on |
| `alarm_rate` / `alarm_burst` | 5/s, burst 10 | — | A test that injects more `exp alarm` | Extra alarms return "alarm rate limit" and are not stored |
| `SF_OP_TIMEOUT_MS` | 2000, Kconfig only | — | — | Hang guard. If you see `modem_timeout` on a healthy board, the modem callback did not run. Do not shrink this to be clever |
| `SF_RX_QUEUE` | 8, Kconfig only | — | `exp status` shows `rx_queue_drop` above 0 at 1 pkt/s | Frames arrived faster than the radio thread drained them |
| `SF_SMALL_SLOTS` | 320, Kconfig only | The link fails with RAM overflow (non-secure RAM is 128 KB, the log buffer is already 32 KB) | You need more than ~288 s of telemetry at 1 pkt/s | Rebuild. `exp sett` cannot grow the array |

`exp save` after a knob change is what survives reset. Autostart is the same rule: `exp autostart on` does nothing across a reset until `exp save`.

## 10. What is not in our CPU

We never program the radio registers ourselves. `nrf_modem_dect_phy_tx` and `_rx` are requests into the modem core, which owns the synthesizer, the LBT measurement, the OFDM symbols, and the CRC. Our callback is how that core talks back.

We do not schedule TX at a modem timestamp. `start_time = 0` means "as soon as the modem is idle." Because our thread only submits one operation at a time, idle means now.

The PHY header's `packet_length` nibble is not the payload size. It is the subslot-length code `03_topology` already used on the air: `0x03` up to 32 bytes, `0x07` up to 64, `0x0F` above that. A wrong code is `INVALID_PHY_HEADER` or `UNSUPPORTED_DATA_SIZE` from the modem, which we now treat as a failed transmit.

The modem hands back a buffer filled out to that slot, not cut to the bytes we submitted. `03_topology` hid this with a fixed 18-byte struct. `sf_codec_decode` sets a DATA payload length to `buffer_len - 16`, so the pad becomes a fake payload, `put` returns "too big" (`-2`), and the node logs `BAD_FRAME` and ACKs `QUEUE_FULL` even though the store is empty. Measured: `size 64` → frame 80 → code `0x0F` → modem length 249 → payload 233. `size 48` → frame 64 → code `0x07` → payload length 99, still above the 64-byte small pool. `size 16` → frame 32 → code `0x03` → the pad matches the slot the application already fits. That is why the recorded run uses `size 16`. A production codec puts a 2-byte length at the start of the DATA body and ignores the rest of the slot. `QUEUE_FULL` should mean the pool has no free telemetry slot, not "this buffer was padded."

The application ACK is not the modem's HARQ ACK. HARQ, if the modem uses it internally, is invisible here. Our ACK is a 21-byte frame that any of our boards can parse. That is why a `03_topology` board on the same carrier produces `BAD_FRAME` and nothing else. Do not mix the two images on one network id.
