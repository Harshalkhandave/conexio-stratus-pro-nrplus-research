/*
 * Copyright (c) 2026 Conexio Technologies, Inc
 *
 * SPDX-License-Identifier: Apache-2.0
 */

#ifndef TOPO_RUNTIME_H_
#define TOPO_RUNTIME_H_

#include "topo_packet.h"

#include <stdbool.h>
#include <stdint.h>

enum topo_role {
	TOPO_ROLE_SOURCE_V = 0,
	TOPO_ROLE_RELAY_V = 1,
	TOPO_ROLE_SINK_V = 2,
};

enum topo_fwd_mode {
	TOPO_FWD_CUT_THROUGH = 0, /* cut-through real-time forwarding (<2 ms) */
	TOPO_FWD_BATCH = 1,       /* periodic batching forwarding */
};

#define TOPO_NEIGH_MAX 8
#define TOPO_SEEN_MAX 16
#define TOPO_FWD_QUEUE_MAX 32

struct topo_neighbor {
	uint16_t id;
	int32_t last_rssi_x2;
	uint32_t last_seen_ms;
	uint32_t hello_n;
	uint32_t data_n;
	bool used;
};

struct topo_seen {
	uint16_t src;
	uint32_t sequence;
	bool used;
};

struct topo_runtime {
	bool running;
	enum topo_role role;
	uint16_t dest_id;
	uint8_t max_hops;

	uint32_t tx_interval_ms;
	uint32_t hello_interval_ms;
	uint32_t tx_count; /* source DATA count; 0 = forever */
	uint8_t tx_power;
	uint8_t mcs;
	uint16_t packet_size;
	bool dedup; /* relay duplicate detection on/off */
	bool source_rx; /* backward compat flag: true if rx_window_ms > 0 */
	uint32_t rx_window_ms; /* source listen duration after TX (ms); 0 = pure TX burst */
	enum topo_fwd_mode fwd_mode; /* cut_through (immediate) vs batch */
	uint32_t fwd_batch_ms; /* batch listen duration when fwd_mode == batch */
	uint16_t q_depth_peak; /* peak forwarding queue depth observed during run */

	uint32_t sequence;
	uint32_t data_sent;
	uint32_t hello_sent;
	uint32_t fwd_sent;
	uint32_t rx_ok;
	uint32_t rx_fail;
	uint32_t deliver_ok;
	uint32_t fwd_drop_dup;
	uint32_t fwd_drop_ttl;
	uint32_t fwd_enqueue;
	uint32_t fwd_drop_full;

	uint16_t last_from;
	int32_t rssi_min_x2;
	int32_t rssi_max_x2;
	int64_t rssi_sum_x2;
	uint32_t rssi_n;

	struct topo_neighbor neigh[TOPO_NEIGH_MAX];
	struct topo_seen seen[TOPO_SEEN_MAX];
};

struct topo_fwd_item {
	struct topo_packet pkt;
};

void topo_runtime_init(void);
/** Restore Kconfig defaults into RAM without re-initing locks (after factory clear). */
void topo_runtime_restore_defaults(void);
struct topo_runtime *topo_runtime_get(void);
void topo_runtime_lock(void);
void topo_runtime_unlock(void);

void topo_runtime_reset_stats(void);

void topo_request_start(uint32_t count_override);
void topo_request_stop(void);
bool topo_is_running(void);
void topo_wait_until_start(void);

void topo_print_status(void);
void topo_print_summary(const char *reason);
void topo_print_neighbors(void);

/** Whether a saved flash profile should auto-start after boot. */
bool topo_should_autostart(void);

const char *topo_role_str(enum topo_role role);
bool topo_role_from_str(const char *s, enum topo_role *out);

const char *topo_fwd_mode_str(enum topo_fwd_mode mode);
bool topo_fwd_mode_from_str(const char *s, enum topo_fwd_mode *out);

uint16_t topo_device_id(void);
void topo_set_device_id(uint16_t id);

/** Update / insert neighbor from a verified RX. Call with lock held or unlocked (locks internally). */
void topo_neigh_note(uint16_t id, int32_t rssi_x2, uint8_t msg_type);

/**
 * Duplicate check for (src, sequence). Returns true if already seen (should not forward).
 * Records this pair when not a duplicate. Call unlocked — locks internally.
 */
bool topo_seen_is_dup(uint16_t src, uint32_t sequence);

bool topo_fwd_enqueue(const struct topo_packet *pkt);
bool topo_fwd_dequeue(struct topo_fwd_item *out);

#endif /* TOPO_RUNTIME_H_ */
