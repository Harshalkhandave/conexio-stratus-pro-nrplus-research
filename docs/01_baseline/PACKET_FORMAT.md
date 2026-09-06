# Packet format — baseline firmware

Defined in `experiments/01_baseline/src/experiment_packet.h`.

## Application PDU

| Field | Type | Size | Description |
|-------|------|------|-------------|
| `device_id` | `uint16_t` | 2 | Sender ID (hwinfo or override) |
| `message_type` | `uint8_t` | 1 | Default `1` = baseline probe |
| `flags` | `uint8_t` | 1 | Reserved (`0`) |
| `sequence` | `uint32_t` | 4 | Monotonic TX counter; resets on reboot |
| `tx_time_ms` | `uint32_t` | 4 | Sender `k_uptime_get()` when the packet is built |
| `payload_len` | `uint16_t` | 2 | Trailing pad bytes after the header |
| `checksum` | `uint8_t` | 1 | XOR of all preceding header bytes |

**Header size: 15 bytes.**  
`CONFIG_EXPERIMENT_PACKET_SIZE` (15–32) may append zero padding; `payload_len = size - 15`.

Endianness: native little-endian on Cortex-M33.

### Checksum

```c
checksum = XOR of bytes [0 .. sizeof(header) - 2]
```

### Sequence numbering

`sequence` is written into the packet before transmit. After TX completes, the firmware increments the counter for the next packet.

With `CONFIG_TX_TRANSMISSIONS = N`, sequences are **0 … N−1** (N packets total). Gaps on the receiver indicate loss.

## PHY control header

Fields set on each transmit (type-1 layout as used in the application):

- `short_network_id` = `CONFIG_NETWORK_ID & 0xff`
- `transmitter_id_*` = device ID
- `transmit_power` = `CONFIG_TX_POWER`
- `df_mcs` = `CONFIG_MCS`
- `packet_length` = 3 subslots (allows padded PDUs)

## Extensibility

Additional fields (sensor samples, hop count, stronger CRC) can be added in later firmware revisions. Prefer bumping `message_type` or documenting a format version so existing log parsers remain compatible.

## Legacy note

The upstream Nordic `hello_dect` sample used an ASCII payload (`"Hello DECT! N"`). That format is not used by this application.
