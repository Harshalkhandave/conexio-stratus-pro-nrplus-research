# Sensor Integration and Padding Fix Log

## Ideology
The core ideology behind these changes is **protocol encapsulation and trust**. Because the DECT NR+ modem acts as a black box that enforces a rigid physical subslot grid (leading to unavoidable zero-padding), the application layer can no longer trust the hardware-reported frame length (`evt->len`). 

By expanding the Store-and-Forward header to 18 bytes and explicitly encoding our own `payload_len` field, we establish a robust boundary between the application data and the physical transmission mechanism. The receiver now discards trailing garbage padding exactly based on this encoded length, preventing `small_pool` buffer overflows.

Secondly, integrating the DHT11 sensor directly into the generation layer (using the Zephyr Sensor API) proves that the mesh network is capable of transmitting real-world, variable-sized data arrays without manual intervention, elevating the firmware to production readiness.

## Changes Implemented

### 1. Header Expansion (`sf_types.h`, `sf_codec.c`)
- **Change:** Increased `SF_HDR_LEN` from 16 to 18.
- **Change:** Increased `SF_HELLO_LEN` from 18 to 20.
- **Change:** Increased `SF_ACK_LEN` from 21 to 23.
- **Change:** Modified `sf_codec_encode` to serialize `f->payload_len` directly into bytes 16 and 17 of the header array (`out[16]`).
- **Change:** Modified `sf_codec_decode` to extract `f->payload_len` directly from bytes 16 and 17, entirely ignoring the padded `len` reported by the hardware.
- **Impact:** The padding bug is permanently fixed. Any size payload can now be transmitted without overflowing the relay's `small_pool` (which strictly checks the decoded `payload_len`).

### 2. User Configuration (`sf_node.c`, `sf_types.h`)
- **Change:** Modified `cmd_sett` handler in `sf_node.c` for `size` to enforce a strict minimum size of 18 (the header length).
- **Change:** The `size` setting now accurately reflects the *Total Packet Size* (Header + Payload). The actual application `payload_len` is calculated as `size - 18`.
- **Change:** Added a new setting `sensor on|off`. Added `uint8_t sensor_mode` to `struct sf_cfg`.
- **Change:** Modified `sf_node_dump_cfg` to print the new `sensor` mode and accurately output `size` as the Total Packet Size.

### 3. Sensor API Implementation (`sf_node.c`)
- **Change:** Included `<zephyr/drivers/sensor.h>`.
- **Change:** Implemented a new `fill_sensor_payload()` function that checks for the `aosong,dht` device. If present, it triggers `sensor_sample_fetch()` and writes exactly 16 bytes of data (2 `int32_t` values for temp and humidity) directly into the `sf_frame` payload.
- **Change:** Added logging at the **Source Node** immediately after fetching the data.
- **Change:** In `enqueue_local`, if `sensor_mode` is `1`, the firmware forces `len = 17` (1 byte sequence number + 16 bytes sensor data), overriding the user's manual size setting.

### 4. Sink Verification (`sf_node.c`)
- **Change:** In `accept_sink`, added a check for `f->payload_len == 17`. If true, the Sink unpacks the 16 bytes back into temporary `struct sensor_value` types and prints the exact temperature and humidity to the Zephyr console for immediate verification.

### 5. Zephyr Configuration (`prj.conf`, `boards/`)
- **Change:** Created `boards/conexio_stratus_pro_nrf9151.overlay` configuring the `dht11` sensor on GPIO0.26 (matching the standard Feather D2 pin). Users can seamlessly adjust this to their exact physical GPIO.
- **Change:** Appended `CONFIG_SENSOR=y`, `CONFIG_DHT=y`, and `CONFIG_CBPRINTF_FP_SUPPORT=y` to `prj.conf`.
