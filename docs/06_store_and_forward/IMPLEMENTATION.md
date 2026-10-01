# 06_store firmware

Hop-by-hop custody on the same three-node DECT NR+ bench as `03_topology`.
`03_topology` is unchanged. This image replaces the 8-deep fire-and-forget forward queue with a store, a hop ACK, and a link state machine.

Build it the same way as `03_topology`: nRF Connect, board `conexio_stratus_pro/nrf9151/ns`, sysbuild, and `overlay-us.conf` or `overlay-eu.conf`. Serial is 115200 8N1.

The protocol rules are in [`experiments/06_store/topo_protocol_spec_v1.md`](../../experiments/06_store/topo_protocol_spec_v1.md). The plan is in [`DESIGN_AND_PLAN.md`](DESIGN_AND_PLAN.md). This file is what the code actually does.

## Bring-up

Same device IDs as prior experiments (03_topology through 05_performance, using modem short IDs). Example with A source `14402`, B relay `56992`, C sink `44720`.

```text
# C sink
exp role sink
exp sett hello 2000
exp autostart on
exp save

# B relay — no route needed when direct=on; it forwards to the packet's dst
exp role relay
exp sett hello 2000
exp autostart on
exp save

# A source — direct=on sends the next hop equal to dest
exp role source
exp sett dest 44720
exp sett size 16
exp sett interval 1000
exp sett count 100
exp autostart on
exp save
```

Start sink, then relay, then source. `direct` defaults on, so a 1-hop source does not need `exp route`. For a forced relay path:

```text
exp sett direct off
exp route set 44720 56992
```

`assume_up` defaults **off**. The first data frame waits until the next hop has answered `N_UP` probes (default 3). That is a few hundred milliseconds, not a failure. `exp sett assume_up on` skips it.

## Shell

`exp sett` with no arguments prints every key and its current value.

| Command | What it does |
|---|---|
| `exp status` | Role, epoch, counters, in-flight frame, carrier |
| `exp sett` | List or `exp sett <key> <value>` |
| `exp sett role` | `source` / `relay` / `sink` (also `exp role`) |
| `exp route` | List, `set <dst> <next>`, `del <dst>` |
| `exp start [count]` | Start. A count overrides `exp sett count` for this run only |
| `exp stop` | Stop. The log gets `SUMMARY` |
| `exp sf` | Pool occupancy |
| `exp link` | Per next-hop `DOWN` / `PROBING` / `UP` |
| `exp neigh` | Last RSSI and epoch heard |
| `exp alarm` | One alarm frame, rate-limited, running source only |
| `exp flush` | Drop the RAM store and log `FLUSH` |
| `exp autostart on\|off` | RAM only until `exp save` |
| `exp save` / `load` / `factory` | Profile in flash. Factory does **not** erase the boot epoch |

`exp sett` keys: `dest`, `interval`, `hello`, `count`, `power`, `mcs`, `size`, `ttl`, `policy`, `assume_up`, `direct`, `class`, `hello_tx`, `dedup`, `ack_timeout`, `attempts`, `backoff_min`, `backoff_max`, `backoff_cap`, `nack_holdoff`, `gap`, `rx_slice`, `hello_dead`, `t_probe`, `probe_fast`, `n_up`, `hold_min`, `hold_max`, `hold_reset`, `tel_ttl`, `stream_idle`, `alarm_rate`, `alarm_burst`.

These are refused while a run is active, because they change the meaning of frames already stored: `role`, `dest`, `size`, `ttl`, `direct`, `assume_up`, `dedup`, `class`, `hello_tx`, and `exp route`. Timers, `policy`, `power`, `mcs`, `interval`, `hello`, and `count` can change during a run. The next transmission picks them up.

`size` is the **application payload**. The on-air frame is `size + 16`. In `03_topology`, `size` was the whole PDC buffer (18 bytes of header included). A profile that said `size 32` there is not a 32-byte payload here.

On this modem the PHY slot code is chosen from the frame length (`≤32` → `0x03`, `≤64` → `0x07`, else `0x0F`), and the modem returns a buffer padded out to that slot. HELLO, ACK, and PROBE ignore the tail. DATA currently treats `buffer_len - 16` as the payload, so the padding is parsed as payload. `size 16` keeps the frame at 32 bytes (code `0x03`) and is the setting the Experiment 06 bench run used. `size 48` and `size 64` are rejected as `BAD_FRAME` and answered `QUEUE_FULL` even when the store is empty. Until the codec carries an explicit payload length and ignores the pad, do not raise `size` above 16.

`interval 0` turns the periodic generator off. In `03_topology`, 0 still sent as fast as the radio loop.

`exp start` with no count uses `exp sett count`. `exp start 0` does the same. Forever is `exp sett count 0` and then `exp start`.

`max_hops`, `source_rx`, and the old 16-entry duplicate set are gone. The node always listens. Duplicate suppression is per `(src, class, epoch)` and is on unless `exp sett dedup off`.

Carrier and network id stay in the region overlay. They are regulatory, and changing them needs a rebuild. `exp status` prints the carrier so a wrong overlay is obvious.

## Layout

| File | Role |
|---|---|
| `src/sf_codec.c` | Bytes on the air. No struct cast of a received buffer |
| `src/sf_dedup.c` | Per-stream sequence and epoch |
| `src/sf_store.c` | RAM pools, alarm reserve, expiry, drop-oldest |
| `src/sf_link.c` | `DOWN` / `PROBING` / `UP` for one next hop |
| `src/sf_node.c` | Custody, ACKs, generator, scheduler decisions |
| `src/sf_port.c` | Kconfig defaults, lock, NVS glue, RX queue |
| `src/sf_persist.c` | `sf/cfg` profile and `sf/epoch` boot counter |
| `src/sf_shell.c` | `exp` commands |
| `src/main.c` | Modem init and the one radio thread |
| `tests/host_test.c` | The engine without the modem |

Capacities (slots, routes, streams) are Kconfig because they size arrays. Everything that changes during a test is `exp sett` or `exp route`, and `exp save` keeps it.

## Codec — `sf_codec.c`

`sf_codec_encode` writes the 16-byte header little-endian, then the type payload. Version is 1. DATA always sets `CUSTODY`. `class` is stored in flag bits 3:2, `RETX` in bit 1. The return value is the frame length, or a negative `sf_codec_err`.

`sf_codec_decode` rejects a short buffer, a version other than 1, `SEC=1`, an unknown type, and a frame longer than the PHY MTU. DATA without `CUSTODY` is rejected. Extra bytes after a HELLO or ACK are ignored. Reserved flag bits are ignored on receive, as the spec requires.

`sf_delta16` compares 16-bit sequence numbers and epochs with defined wrap arithmetic. `0` after `65535` is the next value, not a duplicate.

## Dedup — `sf_dedup.c`

`sf_dedup_check` does not move `last_seq`. `sf_dedup_commit` does, and only after the store accepted the frame or the node declared a drop (`TTL_EXPIRED`). A `QUEUE_FULL` or `NO_ROUTE` does not commit, so the sender's retry is still new.

Same epoch and `delta <= 0` is a duplicate: the node ACKs `DUPLICATE` and does not deliver again. `delta > 1` is a gap; the frame is still accepted and `RX_GAP` is logged. A newer epoch is `SRC_RESET` and starts the stream over. An older epoch is `DUPLICATE` plus `rx_stale_epoch`.

Idle streams are dropped. If the table is full, the least recently seen stream is evicted and counted. A later duplicate of an evicted stream will look new. That is the spec's accepted risk (`D5`).

## Store — `sf_store.c`

Two pools. A frame uses the small pool when it fits, otherwise the large pool. The large pool defaults to **0 slots**. `order == 0` means free. Orders start at 1.

Telemetry may occupy only `nslots - alarm_reserved` entries. Alarm may use any free slot. `sf_store_put` returns 0, `-2` if the payload fits neither pool, or `-3` if the class is full. With `drop_oldest`, a full telemetry class drops the oldest telemetry frame that is not the one currently on the air, then inserts. The dropped identity is returned so the node can log `CUSTODY_BROKEN`.

`sf_store_peek` expires telemetry first, then picks the oldest alarm, else the oldest telemetry. The in-flight order is skipped so a retry does not start a second copy. Alarm is not expired. `tel_ttl 0` disables expiry.

`sf_store_pop_order` deletes one frame after `ACCEPTED`, `DUPLICATE`, or `TTL_EXPIRED`. `sf_store_flush` drops everything and returns the count.

Peek is a scan of the pool. At 320 slots that is noise next to a radio round trip. It keeps the code free of an intrusive list.

## Link — `sf_link.c`

`sf_link_ensure` creates a next hop. New links start `DOWN` unless `assume_up` is on, in which case they start `UP`.

`sf_link_tick` moves `UP` to `DOWN` when a neighbour that has sent HELLO goes quiet for `hello_dead`. A neighbour that never sends HELLO does not kill the link. After hold-down, a fresh HELLO or the probe timer moves the link to `PROBING`.

`sf_link_probe_ok` counts consecutive probe replies. At `n_up` the link becomes `UP`. `sf_link_fail` applies hold-down, doubling it for each failure inside `hold_reset`, capped at `hold_max`. `sf_link_force_probe` is the neighbour-reset path: it enters `PROBING` immediately, including during hold-down, because that neighbour's queue is gone.

## Node — `sf_node.c`

`sf_node_init` copies the config, routes, epoch, and pool pointers. It does not allocate.

`sf_node_start` refuses a source with no destination. It drops any leftover store (`FLUSH reason=start`), clears counters, and keeps sequence numbers and the epoch. Sequence numbers reset only on reboot, because a reboot bumps the epoch and peers then treat the stream as new. Resetting the sequence without an epoch bump would look like duplicates.

`sf_node_stop` logs `STOP` and `SUMMARY`. The summary is the conservation line: generated, delivered, stored, drained, the drop counters, what is still in RAM, and whether a frame is in flight.

`sf_node_poll` returns one action: transmit one frame, or listen for `rx_ms`. Order:

1. Expire, sweep dedup, generate at most one source frame if the interval has elapsed, tick links.
2. If an ACK is queued, send it. This is ahead of new data.
3. If a frame is in flight, wait out its backoff or ACK window, or retry. The retry sets `RETX` and keeps the same sequence number.
4. After `attempts` transmissions with no ACK, the link goes `DOWN`. The frame stays in the store.
5. Otherwise HELLO (if this role sends it), then a probe if any link is `PROBING`, then the next stored frame whose link is `UP` and whose class is not in holdoff.

`interval 0` does not generate. `sf_node_alarm` spends one token. The bucket refills at `alarm_rate` per second up to `alarm_burst`.

`sf_node_on_tx_done` starts the ACK deadline only for the in-flight DATA or PROBE. An ACK or HELLO just opens the listen gap (`gap`). A failed submit sets the deadline to now so the attempt counts as a timeout instead of waiting forever.

`sf_node_on_rx` decodes, logs `RX`, and updates the neighbour table.

- DATA is accepted only when `next` is this node. A sink that overhears a frame aimed at the relay does not deliver it. The relay will forward a frame whose `next` is the sink. That is what keeps a blocked direct path from looking like a second delivery.
- Destination equals this node: deliver, commit dedup, ACK `ACCEPTED`.
- Otherwise a relay stores an outbound copy (`hops+1`, `ttl-1`, `prev` rewritten, `next` from the route or from `direct`) and ACKs `ACCEPTED` only after `put` returns 0. `ttl == 0` ACKs `TTL_EXPIRED` and commits dedup so the sender drops it. No route ACKs `NO_ROUTE` and does not commit. A full class ACKs `QUEUE_FULL`, starts holdoff, and does not commit.
- ACK matches only `prev`, `src`, `epoch`, `seq`, and `class` of the frame in flight. Anything else counts `rx_stale_ack` and is not logged at info, because a late ACK during recovery would flood the UART. `ACCEPTED` and `DUPLICATE` pop the store. `QUEUE_FULL` and `NO_ROUTE` keep the frame and hold the class off. `queue_free == 0` doubles that holdoff. `PROBE_REPLY` advances the link.
- HELLO refreshes liveness. It does not set the link `UP`.
- PROBE aimed at this node queues `PROBE_REPLY`.

`sf_node_set` / `sf_node_route_set` are the shell. `sf_node_flush` drops the store. Changing role flushes, because the queued next hop was chosen for the old role.

Payload bytes are `0xA5` with the low byte of the sequence in byte 0. They are a marker, not a protocol field.

## Port, flash, shell, radio

`sf_port_boot` builds the config from Kconfig, reads the epoch (and sleeps if the boot-loop guard says so), overlays a saved profile, then initialises the pools. Pools are static. There is no `malloc`.

`sf_port_on_pdc` copies the modem buffer into a message queue. The callback does not touch the store. `sf_port_drain_rx` runs on the radio thread after the receive window ends. If the queue is full, `rx_queue_drop` increments; `exp status` prints it.

The radio thread in `main.c` is the only caller of TX and RX. It drains the completion semaphore before each operation so a late cancel event cannot finish the next operation instantly. If the modem does not complete within `SF_OP_TIMEOUT_MS` (default 2 s), the operation is cancelled and the run stops with `modem_timeout`. Init, configure, and activate still wait without that timeout, same as `03_topology`.

The PHY header `packet_length` nibble is the same mapping `03_topology` used for the 05_performance 249-byte frames: `0x03` up to 32 bytes, `0x07` up to 64, otherwise `0x0F`. It is not a shell setting. A wrong value here is a modem header, not a lab parameter.

`read_device_id` uses the same two-byte `hwinfo` read as `03_topology`, so the bench ids stay `14402`, `56992`, and `44720`. `SF_DEVICE_ID_OVERRIDE` replaces it. `0` and `65535` are reserved and become `1` with a warning.

`sf_persist_boot_epoch` adds one to the stored epoch before any transmission, wrapping past 0 to 1. The first boot mixes the cycle counter into the epoch because there is no RNG requirement beyond uniqueness across boots. Each boot increments `boots`. Past `SF_BOOT_LOOP_MAX` (default 5) the radio start is delayed by `2^(boots-max)` seconds, capped at `SF_BOOT_DELAY_CAP_S`. After the node has been running for `SF_BOOT_STABLE_S` (default 300 s), `boots` is cleared. There is no RTC, so this is a boot counter, not a wall-clock window. `exp factory` deletes `sf/cfg` only.

The profile blob is version `1` and magic `SF61`. A size or sanity mismatch is ignored and the Kconfig defaults stay. A payload that does not fit the pools built into this image is rejected the same way.

Shell handlers only parse and print. They call `sf_port_*`, which holds the mutex around the node and drops it before `settings_save_one`.

## Decisions you may want to change

1. **New links start DOWN and need 3 probe replies.** The spec's liveness rule. `exp sett assume_up on` (and save) if you want data on the first poll. Default is off.
2. **One frame on the air for the whole node**, not one per next hop. The radio is half-duplex. A second route waits.
3. **ACK is sent at the end of the current receive slice**, not by cancelling the modem mid-window. Cancelling drops whatever ACK we were waiting for. Idle delay is at most `rx_slice` (15 ms). If this node is already waiting on a downstream ACK, the upstream ACK waits out that attempt too. That is why the default ACK timeout is **200 ms**, not the spec's provisional 40 ms. Measure a clean 1-hop RTT, then `exp sett ack_timeout`.
4. **Overheard frames are ignored unless `next` is this node.** A sink does not deliver a source transmission that was addressed to the relay. Say if you would rather deliver any frame whose `dst` is this node.
5. **`direct` defaults on.** `exp sett dest` is enough for 1 hop. Turn it off when the source must not skip the relay.
6. **`interval 0` generates nothing.** The old firmware treated 0 as "as fast as the loop".
7. **`size` is payload, not the whole frame.**
8. **Telemetry expiry and alarm reserve are real.** Default 320 small slots, 32 reserved, so telemetry backlog at 1 pkt/s is about 288 s, short of the 5-minute motto. Raise `SF_SMALL_SLOTS` after `ram_report` if you need the full 5 minutes with margin. The large pool is off until you need payloads above 64 bytes.
9. **RAM only.** A reboot loses the store. The epoch makes that loss show up as `NEIGHBOR_RESET` / `SRC_RESET` and `RX_GAP`, not as a silent hole. Flash custody is not implemented; `put` is synchronous.
10. **Neighbour reset skips hold-down** and forces `PROBING`. Hold-down still applies to ordinary ACK failures.
11. **HELLO silence does not kill a link that has never sent HELLO.** Otherwise a source with HELLO off would be marked dead.
12. **No application checksum.** The PHY CRC is the integrity check. `SEC` must be 0; those frames are dropped.
13. **Backoff uses a local xorshift**, not the entropy driver. It only spaces retries.
14. **Carrier and network id are not shell settings.**
15. **`exp start` does not zero the sequence.** Reboot does, via the epoch. `exp start` does empty the store so the new run's counters are not mixed with the previous backlog.
16. **`exp factory` keeps the epoch.** Resetting it would make old and new streams look continuous.

## What you should expect on the bench

- The first packets after `exp start` are probes, then HELLO from relay and sink, then DATA. With `assume_up off` that is normal.
- `ACK_TIMEOUT` too low looks like `LINK_STATE ... reason=max_attempts` on a link that is fine. The frames are still in the store. Raise the timeout or `exp sett assume_up on` only after you have seen ACKs at all.
- `exp stop` returns after the current listen or ACK wait, up to `ack_timeout` if a frame is in flight.
- A full relay answers `QUEUE_FULL`. The source keeps the frame and pauses that class for `nack_holdoff` (doubled when `queue_free` is 0). It does not delete it.
- `drop_oldest` logs `CUSTODY_BROKEN`. Those sequences will be missing at the sink on purpose.
- A relay or source reboot logs `NEIGHBOR_RESET` or `SRC_RESET` and a gap. The gap is the RAM that died. That is a declared loss, not a bug in the counter.
- `rx_queue_drop` on `exp status` means the modem delivered frames faster than the radio thread drained them. Raise `SF_RX_QUEUE` if you see it on a normal 1 pkt/s run. You should not.
- `BAD_FRAME` is a version, length, `SEC`, or class the peer did not generate. A `03_topology` board on the same carrier will cause these. Do not mix the two images on one network id.
- UART logging of every `RX`/`TX` at 1 pkt/s is fine. The log buffer is 32 KB and deferred, same idea as the 05_performance fix. A retry storm logs one `RETRY` per attempt, not one line per backoff slot.
- `exp save` during a run is allowed. It writes the RAM profile, including a timer you just changed. Role and route edits are blocked until `exp stop`, so a save during a run cannot capture a half-edited route.
- Boot-loop delay: five quick resets, then the next boots wait before the radio starts. The shell is up during the wait. After five minutes of a real run the counter clears.

## Optimization review

Checked after the host tests, not left as a TODO:

- No `malloc`. Pools, dedup, routes, and the RX queue are static.
- The radio thread does not hold the mutex across TX/RX, so `exp status` works during a listen.
- The modem buffer is copied in the callback. The store never aliases it.
- One encode of a data frame; retries flip the `RETX` bit in that buffer instead of rebuilding it.
- Store scan is O(slots). Left that way. A linked list would be more code on the ACK path for no airtime win at this size.
- Receive is not cancelled to rush an ACK. That was the alternative, and it races the downstream ACK. The slice bound is the deliberate trade.
- `stale_ack` is a counter, not an info line.
- Default image does not reserve the spec's 64 KB. 320 slots is about 30 KB including metadata. Confirm with `ram_report` before raising it.
- Host tests cover the codec, sequence wrap, alarm reserve, drop-oldest, a 3-packet hop, a lost ACK then duplicate delivery of one, relay custody, `QUEUE_FULL` keeping the source frame, and probe-before-UP. They do not run the modem. Build this image in nRF Connect before the first bench session; that compile is the check this workspace cannot run (west is not on the path here).

```text
gcc -std=c11 -Wall -Wextra -Werror -DSF_HOST -I../src -o host_test host_test.c ^
  ../src/sf_codec.c ../src/sf_dedup.c ../src/sf_store.c ../src/sf_link.c ../src/sf_node.c
```
