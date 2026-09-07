# Range / link characterization (`02_range`)

Procedure and data for RF range and link tests using **`experiments/01_baseline`** firmware.

## Board setup (once)

| Board | Overlays |
|-------|----------|
| TX | `overlay-us.conf` (or EU) + `overlay-tx-only.conf` |
| RX | same region + `overlay-rx-only.conf` |

Rebuild only when changing region or role. Use the shell / campaign script to change interval, power, count, size.

## How you should test parameters

**Recommended:** automated campaign (you only confirm placement).

If **TX and RX USB are on different PCs**, use the split scripts (`range_rx.py` + `range_tx.py`) — see [`../../tools/range_campaign/README.md`](../../tools/range_campaign/README.md).

If both COM ports are on **one PC**:

```text
cd tools/range_campaign
python -m pip install -r requirements.txt
copy matrix.example.yaml matrix.yaml
python range_campaign.py --tx COMx --rx COMy --matrix matrix.yaml
```

**Manual (single condition):**

1. Place boards.
2. Capture RX serial if desired.
3. On both: `exp stop` then `exp sett …` as needed.
4. RX: `exp start 0`  (listen)
5. TX: `exp start 1000`
6. When TX prints `SUMMARY`, on RX: `exp stop`
7. PDR ≈ `rx_ok / tx_sent × 100`

## Suggested first matrix

Start small, then expand:

1. LOS 5 m, 10 m, 20 m (1000 packets, fixed power)
2. Same distance with 1–2 walls
3. Optional: orientation at one mid distance
4. Optional: power sweep at one fixed distance

## Notes

- Do not use simultaneous `tx_rx` on both boards for PDR.
- `tx_time` / `rx_time` are not one-way latency (no shared clock).
- Keep other serial apps closed while the campaign script holds the COM ports.

Firmware: [`../01_baseline/README.md`](../01_baseline/README.md).
