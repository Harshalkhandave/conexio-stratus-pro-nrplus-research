/*
 * Copyright (c) 2026 Conexio Technologies, Inc
 *
 * SPDX-License-Identifier: Apache-2.0
 *
 * Protocol engine. No Zephyr calls: the radio thread and the host test both
 * drive poll / on_tx_done / on_rx. One DATA or PROBE frame is in flight.
 */

#ifndef SF_NODE_H_
#define SF_NODE_H_

#include "sf_link.h"
#include "sf_store.h"
#include "sf_dedup.h"

#include <stddef.h>

enum sf_act_kind {
	SF_ACT_RX = 0,
	SF_ACT_TX = 1,
};

struct sf_action {
	uint8_t kind;
	bool inflight; /* TX is the tracked DATA/PROBE, not an ACK or HELLO */
	bool want_ack;
	uint32_t rx_ms;
	uint16_t tx_len;
	uint8_t tx[SF_PAYLOAD_MAX];
};

typedef void (*sf_emit_fn)(void *ctx, const char *line);
typedef void (*sf_print_fn)(void *ctx, const char *line);
typedef uint32_t (*sf_rng_fn)(void);
typedef int64_t (*sf_us_fn)(void);

struct sf_node;

void sf_node_init(struct sf_node *n, const struct sf_cfg *cfg, const struct sf_route *routes,
		  unsigned int nroutes, uint16_t epoch, struct sf_store store);
void sf_node_set_emit(struct sf_node *n, sf_emit_fn fn, void *ctx);
void sf_node_set_rng(struct sf_node *n, sf_rng_fn fn);
void sf_node_set_clock(struct sf_node *n, sf_us_fn fn);

int sf_node_start(struct sf_node *n, int64_t now, uint32_t count_or_zero_for_cfg);
void sf_node_stop(struct sf_node *n, int64_t now, const char *reason);
bool sf_node_running(const struct sf_node *n);
uint16_t sf_node_epoch(const struct sf_node *n);
const struct sf_cfg *sf_node_cfg(const struct sf_node *n);
const struct sf_counters *sf_node_counters(const struct sf_node *n);
const struct sf_store *sf_node_store(const struct sf_node *n);

void sf_node_poll(struct sf_node *n, int64_t now, struct sf_action *act);
void sf_node_on_tx_done(struct sf_node *n, int64_t now, bool ok, bool was_inflight);
void sf_node_on_rx(struct sf_node *n, int64_t now, const uint8_t *data, uint16_t len,
		   int16_t rssi_x2);

int sf_node_alarm(struct sf_node *n, int64_t now);
uint16_t sf_node_flush(struct sf_node *n, int64_t now, const char *reason);

int sf_node_set(struct sf_node *n, const char *key, const char *value, char *err, size_t err_len);
int sf_node_route_set(struct sf_node *n, uint16_t dst, uint16_t next, char *err, size_t err_len);
int sf_node_route_del(struct sf_node *n, uint16_t dst);
void sf_node_route_clear(struct sf_node *n);
void sf_node_apply_cfg(struct sf_node *n, const struct sf_cfg *cfg);

void sf_node_dump_cfg(const struct sf_node *n, sf_print_fn fn, void *ctx);
void sf_node_status(const struct sf_node *n, int64_t now, sf_print_fn fn, void *ctx);
void sf_node_report_sf(const struct sf_node *n, sf_print_fn fn, void *ctx);
void sf_node_report_link(const struct sf_node *n, sf_print_fn fn, void *ctx);
void sf_node_report_neigh(const struct sf_node *n, sf_print_fn fn, void *ctx);
void sf_node_report_route(const struct sf_node *n, sf_print_fn fn, void *ctx);

unsigned int sf_node_route_export(const struct sf_node *n, struct sf_route *out, unsigned int cap);

/* Opaque size: the test and the port allocate sf_node by this header's struct.
 * The full struct is in the header so the firmware can put it in BSS.
 */
struct sf_ack_slot {
	uint16_t len;
	uint8_t buf[32];
};

struct sf_inflight {
	bool active;
	bool from_store;
	bool waiting_backoff;
	uint8_t type;
	uint8_t attempts;
	uint8_t class_;
	uint16_t next_id;
	uint16_t src;
	uint16_t seq;
	uint16_t epoch;
	uint32_t order;
	int64_t deadline_ms;
	int64_t backoff_until_ms;
	int64_t tx_done_ms;
	uint16_t len;
	uint8_t buf[SF_PAYLOAD_MAX];
};

struct sf_neigh {
	bool used;
	bool have_epoch;
	uint16_t id;
	uint16_t epoch;
	int16_t rssi_x2;
	int64_t last_ms;
	uint32_t heard;
};

struct sf_node {
	struct sf_cfg cfg;
	struct sf_store store;
	struct sf_dedup dedup;
	struct sf_link_table links;
	struct sf_route route[SF_ROUTE_CAP];
	struct sf_neigh neigh[SF_NEIGH_CAP];
	struct sf_counters ct;
	struct sf_inflight inf;
	struct sf_ack_slot ackq[SF_ACKQ_CAP];
	uint8_t ack_n;
	uint32_t ack_dropped;
	uint16_t seq_next[2];
	uint16_t epoch;
	uint32_t probe_nonce;
	uint32_t run_count;
	uint32_t alarm_tokens_m;
	int64_t alarm_ts_ms;
	int64_t last_gen_ms;
	int64_t next_hello_ms;
	int64_t gap_until_ms;
	int64_t holdoff_ms[2];
	bool running;
	char line[240];
	sf_emit_fn emit;
	void *emit_ctx;
	sf_rng_fn rng;
	sf_us_fn clock_us;
};

#endif /* SF_NODE_H_ */
