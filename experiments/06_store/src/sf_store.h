/*
 * Copyright (c) 2026 Conexio Technologies, Inc
 *
 * SPDX-License-Identifier: Apache-2.0
 *
 * Two RAM pools. order==0 is a free slot. Orders start at 1.
 * Telemetry may use only (nslots - alarm_reserved) slots in a pool.
 * Alarm may use any free slot. No malloc.
 */

#ifndef SF_STORE_H_
#define SF_STORE_H_

#include "sf_types.h"

struct sf_slot {
	uint32_t order;
	uint16_t src;
	uint16_t dst;
	uint16_t next;
	uint16_t seq;
	uint16_t epoch;
	uint8_t hops;
	uint8_t ttl;
	uint8_t class_;
	uint16_t len;
	int64_t stored_ms;
};

struct sf_pool {
	struct sf_slot *slot;
	uint8_t *mem;
	uint16_t nslots;
	uint16_t cap;
	uint16_t alarm_reserved;
	uint16_t tel_used;
	uint16_t alm_used;
	uint32_t next_order;
};

struct sf_store {
	struct sf_pool small;
	struct sf_pool large;
	uint16_t peak;
};

struct sf_view {
	bool ok;
	uint32_t order;
	uint16_t src;
	uint16_t dst;
	uint16_t next;
	uint16_t seq;
	uint16_t epoch;
	uint8_t hops;
	uint8_t ttl;
	uint8_t class_;
	uint16_t len;
	const uint8_t *payload;
	int64_t stored_ms;
};

struct sf_dropped {
	bool dropped;
	uint32_t order;
	uint16_t src;
	uint16_t seq;
	uint16_t epoch;
	uint8_t class_;
};

typedef void (*sf_expire_fn)(void *ctx, const struct sf_slot *slot);

void sf_pool_init(struct sf_pool *p, struct sf_slot *slots, uint8_t *mem, uint16_t nslots,
		  uint16_t cap, uint16_t alarm_reserved);
void sf_store_init(struct sf_store *s, struct sf_pool small, struct sf_pool large);

uint16_t sf_store_used(const struct sf_store *s);
uint16_t sf_store_free_for(const struct sf_store *s, uint16_t len, uint8_t class_);
uint8_t sf_store_free_pct(const struct sf_store *s);

int sf_store_put(struct sf_store *s, const struct sf_slot *meta, const uint8_t *payload,
		 uint8_t policy, uint32_t protect_order, struct sf_dropped *dropped,
		 uint32_t *new_order);
bool sf_store_peek(struct sf_store *s, int64_t now, uint32_t tel_ttl_ms, uint32_t protect_order,
		   sf_expire_fn on_expire, void *ctx, struct sf_view *out);
bool sf_store_pop_order(struct sf_store *s, uint32_t order);
const uint8_t *sf_store_payload(const struct sf_pool *p, uint16_t index);
uint16_t sf_store_expire(struct sf_store *s, int64_t now, uint32_t tel_ttl_ms,
			 uint32_t protect_order, sf_expire_fn on_expire, void *ctx);
uint16_t sf_store_flush(struct sf_store *s);

#endif /* SF_STORE_H_ */
