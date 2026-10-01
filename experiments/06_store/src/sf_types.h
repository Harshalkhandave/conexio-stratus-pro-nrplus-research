/*
 * Copyright (c) 2026 Conexio Technologies, Inc
 *
 * SPDX-License-Identifier: Apache-2.0
 *
 * Shared types for the store-and-forward core. This header is compiled both
 * by the Zephyr image and by the host test (gcc -DSF_HOST). Array ceilings
 * come from Kconfig on target; the host uses the #else values.
 */

#ifndef SF_TYPES_H_
#define SF_TYPES_H_

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#ifdef CONFIG_SF_ROUTE_MAX
#define SF_ROUTE_CAP   CONFIG_SF_ROUTE_MAX
#define SF_LINK_CAP    CONFIG_SF_LINK_MAX
#define SF_STREAM_CAP  CONFIG_SF_MAX_STREAMS
#define SF_NEIGH_CAP   CONFIG_SF_NEIGH_MAX
#define SF_ACKQ_CAP    CONFIG_SF_ACK_QUEUE
#define SF_PAYLOAD_MAX CONFIG_SF_PHY_MTU
#else
#define SF_ROUTE_CAP   8
#define SF_LINK_CAP    8
#define SF_STREAM_CAP  16
#define SF_NEIGH_CAP   8
#define SF_ACKQ_CAP    4
#define SF_PAYLOAD_MAX 249
#endif

#define SF_HDR_LEN       16
#define SF_HELLO_LEN     18
#define SF_ACK_LEN       21
#define SF_PROTO_VERSION 1

enum sf_type {
	SF_TYPE_DATA = 1,
	SF_TYPE_HELLO = 2,
	SF_TYPE_ACK = 3,
	SF_TYPE_PROBE = 4,
};

enum sf_flag {
	SF_FLAG_CUSTODY = 1 << 0,
	SF_FLAG_RETX = 1 << 1,
	SF_FLAG_SEC = 1 << 4,
};

enum sf_class {
	SF_CLASS_TEL = 0,
	SF_CLASS_ALARM = 1,
};

enum sf_ack_status {
	SF_ACK_ACCEPTED = 0x00,
	SF_ACK_DUPLICATE = 0x01,
	SF_ACK_QUEUE_FULL = 0x02,
	SF_ACK_TTL_EXPIRED = 0x03,
	SF_ACK_NO_ROUTE = 0x04,
	SF_ACK_PROBE_REPLY = 0x10,
};

enum sf_role {
	SF_ROLE_SOURCE = 0,
	SF_ROLE_RELAY = 1,
	SF_ROLE_SINK = 2,
};

enum sf_hello_mode {
	SF_HELLO_AUTO = 0,
	SF_HELLO_ON = 1,
	SF_HELLO_OFF = 2,
};

enum sf_policy {
	SF_POLICY_REJECT = 0,
	SF_POLICY_DROP_OLDEST = 1,
};

enum sf_link_state {
	SF_LINK_DOWN = 0,
	SF_LINK_PROBING = 1,
	SF_LINK_UP = 2,
};

#define SF_ID_BCAST 0xFFFFu

struct sf_cfg {
	uint16_t node_id;
	uint8_t role;
	uint16_t dest_id;
	uint16_t payload_len;
	uint32_t interval_ms;
	uint32_t count; /* 0 = generate until stop */
	uint32_t hello_ms;
	uint8_t hello_mode;
	uint8_t ttl;
	uint8_t policy;
	uint8_t assume_up;
	uint8_t direct_fallback;
	uint8_t gen_class;
	uint8_t dedup_on;
	uint8_t tx_power;
	uint8_t mcs;

	uint32_t ack_timeout_ms;
	uint8_t max_attempts;
	uint32_t backoff_min_ms;
	uint32_t backoff_max_ms;
	uint32_t backoff_cap_ms;
	uint32_t nack_holdoff_ms;
	uint32_t inter_tx_listen_ms;
	uint32_t rx_slice_ms;
	uint32_t hello_dead_ms;
	uint32_t t_probe_ms;
	uint32_t probe_fast_ms;
	uint8_t n_up;
	uint32_t holddown_min_ms;
	uint32_t holddown_max_ms;
	uint32_t holddown_reset_ms;
	uint32_t telemetry_ttl_ms;
	uint32_t stream_idle_ms;
	uint32_t alarm_rate; /* tokens per second; 0 disables exp alarm */
	uint8_t alarm_burst;
	uint16_t phy_mtu;
};

struct sf_route {
	uint16_t dst;
	uint16_t next;
	bool used;
};

struct sf_frame {
	uint8_t ver;
	uint8_t type;
	uint8_t flags;
	uint8_t class_;
	uint8_t retx;
	uint8_t hops;
	uint8_t ttl;
	uint16_t src;
	uint16_t dst;
	uint16_t prev;
	uint16_t next;
	uint16_t seq;
	uint16_t epoch;
	uint16_t payload_len;
	uint8_t payload[SF_PAYLOAD_MAX];
	uint8_t status;
	uint16_t queue_free;
	uint16_t node_epoch;
	uint8_t role;
	uint8_t free_pct;
};

struct sf_counters {
	uint32_t generated;
	uint32_t delivered;
	uint32_t stored_total;
	uint32_t drained_total;
	uint16_t queue_peak;
	uint32_t dropped_overflow;
	uint32_t dropped_expired;
	uint32_t dropped_ttl;
	uint32_t dropped_flushed;
	uint32_t rejected_at_source;
	uint32_t rejected_full;
	uint32_t retries;
	uint32_t dup_rx;
	uint32_t rx_gap;
	uint32_t rx_bad_hdr;
	uint32_t rx_stale_ack;
	uint32_t rx_stale_epoch;
	uint32_t rx_not_mine;
	uint32_t stream_evictions;
	uint32_t nack_full;
	uint32_t nack_route;
	uint32_t probe_tx;
	uint32_t hello_tx;
	uint32_t ack_tx;
	uint16_t epoch;
};

static inline int16_t sf_delta16(uint16_t newer, uint16_t older)
{
	int32_t d = (int32_t)newer - (int32_t)older;

	if (d > 32767) {
		d -= 65536;
	} else if (d < -32768) {
		d += 65536;
	}
	return (int16_t)d;
}

const char *sf_role_name(uint8_t role);
const char *sf_class_name(uint8_t class_);
const char *sf_ack_name(uint8_t status);
const char *sf_link_name(uint8_t state);
const char *sf_type_name(uint8_t type);

#endif /* SF_TYPES_H_ */
