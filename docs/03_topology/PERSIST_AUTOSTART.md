# Persist & autostart (Week 4 reboot / power-fail)

**Firmware:** `experiments/03_topology` (`CONFIG_TOPO_PERSIST=y`)  
**Storage:** Zephyr **settings** over **NVS** (`settings_storage` flash partition)

Shell settings are normally **RAM-only**. With persist enabled you can save a profile so that after **reset or power loss** the board restores role/RF and optionally **auto-starts** (listen/transmit) without retyping commands.

---

## Why

Week 4 healing tests (reboot A/B, power-cycle relay) need nodes to come back in a known role and resume RX/TX by themselves. Manual `exp start` after every reboot breaks timing measurements.

---

## Commands

| Command | Meaning |
|---------|---------|
| `exp autostart on\|off` | Set RAM flag (does **not** write flash alone) |
| `exp sett autostart on\|off` | Same as above |
| `exp save` | Write current role + RF + autostart to flash |
| `exp load` | Reload flash profile into RAM (stop run first) |
| `exp factory` | Erase flash profile; restore Kconfig defaults in RAM |
| `exp status` | Shows `autostart=` and `persist=` (1 = profile present) |

RAM changes (`exp role`, `exp sett …`) print a reminder: **exp save to persist**.

---

## Boot behavior

1. Apply **Kconfig** defaults.  
2. If a valid flash profile exists → **load** it (overrides RAM).  
3. Auto-start if either:
   - `CONFIG_TOPO_WAIT_FOR_START=n`, or  
   - saved / loaded **`autostart=1`**
4. Source still needs `dest_id ≠ 0` or autostart is **skipped** (warning in log).

```text
power on
   → modem / PHY up
   → persist: loaded role=… dest=… autostart=1
   → persist: auto-start role=…
```

If `autostart=0` and `WAIT_FOR_START=y`: idle until `exp start` (Week 3 lab style).

---

## Example — sink that always listens after reboot

```text
exp role sink
exp sett hello 0
exp autostart on
exp save
exp status
# … power-cycle or reset …
# Expect: persist: loaded … autostart=1
#         persist: auto-start role=sink
```

## Example — source that resumes TX after reboot

```text
exp role source
exp sett dest 44720
exp sett power 10
exp sett count 0
exp sett hello 0
exp autostart on
exp save
```

## Example — relay for Week 4 “remove B / restore B”

```text
exp role relay
exp sett max_hops 3
exp sett hello 0
exp autostart on
exp save
```

## Disable autostart but keep RF profile

```text
exp autostart off
exp save
```

## Wipe saved profile

```text
exp stop
exp factory
```

---

## What is saved

Role, `dest`, `max_hops`, `power`, `mcs`, `size`, `interval`, `hello`, `count`, `autostart`.

**Not** saved: live counters, neighbor table, sequence (reset on each start).

---

## Verification checklist

1. Configure + `exp save` → `exp status` shows `persist=1`.  
2. Reset board (button or power).  
3. Boot log shows `persist: loaded …` and, if enabled, `persist: auto-start …`.  
4. `exp status` → `running=1` (when autostart on) and same role/dest/power.  
5. `exp factory` → reboot → no loaded profile; waits for `exp start`.

---

## Relation to Week 3 vs Week 4

| Mode | Typical use |
|------|-------------|
| No save / autostart off | Week 3 interactive lab + visualizer |
| Save + autostart on | Week 4 reboot / power-fail / healing runs |

Visualizer can still `exp stop` / change settings; remember to **`exp save`** again if the new defaults should survive the next failure test.
