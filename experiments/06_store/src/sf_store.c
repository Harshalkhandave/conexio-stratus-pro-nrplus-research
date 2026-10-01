/*
 * Copyright (c) 2026 Conexio Technologies, Inc
 *
 * SPDX-License-Identifier: Apache-2.0
 */

#include "sf_store.h"

#include <string.h>

static uint16_t pool_used(const struct sf_pool *p)
{
	return (uint16_t)(p->tel_used + p->alm_used);
}

static uint16_t tel_cap(const struct sf_pool *p)
{
	if (p->nslots <= p->alarm_reserved) {
		return 0;
	}
	return (uint16_t)(p->nslots - p->alarm_reserved);
}

void sf_pool_init(struct sf_pool *p, struct sf_slot *slots, uint8_t *mem, uint16_t nslots,
		  uint16_t cap, uint16_t alarm_reserved)
{
	uint16_t i;

	p->slot = slots;
	p->mem = mem;
	p->nslots = nslots;
	p->cap = cap;
	p->alarm_reserved = alarm_reserved;
	p->tel_used = 0;
	p->alm_used = 0;
	p->next_order = 1;
	for (i = 0; i < nslots; i++) {
		slots[i].order = 0;
	}
}

void sf_store_init(struct sf_store *s, struct sf_pool small, struct sf_pool large)
{
	s->small = small;
	s->large = large;
	s->peak = 0;
}

const uint8_t *sf_store_payload(const struct sf_pool *p, uint16_t index)
{
	if (p->mem == NULL || p->cap == 0) {
		return NULL;
	}
	return &p->mem[(size_t)index * p->cap];
}

static uint8_t *payload_mut(struct sf_pool *p, uint16_t index)
{
	return &p->mem[(size_t)index * p->cap];
}

uint16_t sf_store_used(const struct sf_store *s)
{
	return (uint16_t)(pool_used(&s->small) + pool_used(&s->large));
}

static struct sf_pool *pool_for(struct sf_store *s, uint16_t len)
{
	if (len <= s->small.cap && s->small.nslots > 0) {
		return &s->small;
	}
	if (s->large.nslots > 0 && len <= s->large.cap) {
		return &s->large;
	}
	return NULL;
}

static const struct sf_pool *pool_for_const(const struct sf_store *s, uint16_t len)
{
	if (len <= s->small.cap && s->small.nslots > 0) {
		return &s->small;
	}
	if (s->large.nslots > 0 && len <= s->large.cap) {
		return &s->large;
	}
	return NULL;
}

uint16_t sf_store_free_for(const struct sf_store *s, uint16_t len, uint8_t class_)
{
	const struct sf_pool *p = pool_for_const(s, len);
	uint16_t used;

	if (p == NULL) {
		return 0;
	}
	used = pool_used(p);
	if (used >= p->nslots) {
		return 0;
	}
	if (class_ == SF_CLASS_ALARM) {
		return (uint16_t)(p->nslots - used);
	}
	if (p->tel_used >= tel_cap(p)) {
		return 0;
	}
	return (uint16_t)(tel_cap(p) - p->tel_used);
}

uint8_t sf_store_free_pct(const struct sf_store *s)
{
	uint32_t slots = (uint32_t)s->small.nslots + s->large.nslots;
	uint32_t used;

	if (slots == 0) {
		return 0;
	}
	used = sf_store_used(s);
	if (used >= slots) {
		return 0;
	}
	return (uint8_t)(((slots - used) * 100u) / slots);
}

static void note_peak(struct sf_store *s)
{
	uint16_t used = sf_store_used(s);

	if (used > s->peak) {
		s->peak = used;
	}
}

static void release_slot(struct sf_pool *p, struct sf_slot *slot)
{
	if (slot->order == 0) {
		return;
	}
	if (slot->class_ == SF_CLASS_ALARM) {
		if (p->alm_used > 0) {
			p->alm_used--;
		}
	} else if (p->tel_used > 0) {
		p->tel_used--;
	}
	slot->order = 0;
}

static bool expired(const struct sf_slot *slot, int64_t now, uint32_t tel_ttl_ms)
{
	if (slot->class_ != SF_CLASS_TEL || tel_ttl_ms == 0) {
		return false;
	}
	return (now - slot->stored_ms) >= (int64_t)tel_ttl_ms;
}

static uint16_t expire_pool(struct sf_pool *p, int64_t now, uint32_t tel_ttl_ms,
			    uint32_t protect_order, sf_expire_fn on_expire, void *ctx)
{
	uint16_t i;
	uint16_t n = 0;

	if (p->nslots == 0 || tel_ttl_ms == 0) {
		return 0;
	}
	for (i = 0; i < p->nslots; i++) {
		struct sf_slot *slot = &p->slot[i];

		if (slot->order == 0 || slot->order == protect_order) {
			continue;
		}
		if (!expired(slot, now, tel_ttl_ms)) {
			continue;
		}
		if (on_expire != NULL) {
			on_expire(ctx, slot);
		}
		release_slot(p, slot);
		n++;
	}
	return n;
}

uint16_t sf_store_expire(struct sf_store *s, int64_t now, uint32_t tel_ttl_ms,
			 uint32_t protect_order, sf_expire_fn on_expire, void *ctx)
{
	return (uint16_t)(expire_pool(&s->small, now, tel_ttl_ms, protect_order, on_expire, ctx) +
			  expire_pool(&s->large, now, tel_ttl_ms, protect_order, on_expire, ctx));
}

static int find_free(struct sf_pool *p)
{
	uint16_t i;

	for (i = 0; i < p->nslots; i++) {
		if (p->slot[i].order == 0) {
			return (int)i;
		}
	}
	return -1;
}

static int find_oldest(struct sf_pool *p, uint8_t class_, uint32_t protect_order)
{
	uint16_t i;
	int best = -1;

	for (i = 0; i < p->nslots; i++) {
		if (p->slot[i].order == 0 || p->slot[i].class_ != class_) {
			continue;
		}
		if (p->slot[i].order == protect_order) {
			continue;
		}
		if (best < 0 || p->slot[i].order < p->slot[best].order) {
			best = (int)i;
		}
	}
	return best;
}

static bool class_full(const struct sf_pool *p, uint8_t class_)
{
	if (pool_used(p) >= p->nslots) {
		return true;
	}
	if (class_ != SF_CLASS_ALARM && p->tel_used >= tel_cap(p)) {
		return true;
	}
	return false;
}

int sf_store_put(struct sf_store *s, const struct sf_slot *meta, const uint8_t *payload,
		 uint8_t policy, uint32_t protect_order, struct sf_dropped *dropped,
		 uint32_t *new_order)
{
	struct sf_pool *p;
	int idx;

	if (dropped != NULL) {
		dropped->dropped = false;
	}
	if (new_order != NULL) {
		*new_order = 0;
	}
	if (meta == NULL || (meta->len > 0 && payload == NULL)) {
		return -1;
	}
	p = pool_for(s, meta->len);
	if (p == NULL) {
		return -2;
	}
	if (class_full(p, meta->class_)) {
		if (meta->class_ != SF_CLASS_TEL || policy != SF_POLICY_DROP_OLDEST) {
			return -3;
		}
		idx = find_oldest(p, SF_CLASS_TEL, protect_order);
		if (idx < 0) {
			return -3;
		}
		if (dropped != NULL) {
			dropped->dropped = true;
			dropped->order = p->slot[idx].order;
			dropped->src = p->slot[idx].src;
			dropped->seq = p->slot[idx].seq;
			dropped->epoch = p->slot[idx].epoch;
			dropped->class_ = p->slot[idx].class_;
		}
		release_slot(p, &p->slot[idx]);
	}
	idx = find_free(p);
	if (idx < 0) {
		return -3;
	}
	p->slot[idx] = *meta;
	p->slot[idx].order = p->next_order++;
	if (p->next_order == 0) {
		p->next_order = 1;
	}
	if (meta->len > 0) {
		memcpy(payload_mut(p, (uint16_t)idx), payload, meta->len);
	}
	if (meta->class_ == SF_CLASS_ALARM) {
		p->alm_used++;
	} else {
		p->tel_used++;
	}
	note_peak(s);
	if (new_order != NULL) {
		*new_order = p->slot[idx].order;
	}
	return 0;
}

static void consider(struct sf_pool *p, uint16_t index, struct sf_slot **best)
{
	struct sf_slot *slot = &p->slot[index];

	if (*best == NULL) {
		*best = slot;
		return;
	}
	if (slot->class_ == SF_CLASS_ALARM && (*best)->class_ != SF_CLASS_ALARM) {
		*best = slot;
		return;
	}
	if (slot->class_ != SF_CLASS_ALARM && (*best)->class_ == SF_CLASS_ALARM) {
		return;
	}
	if (slot->order < (*best)->order) {
		*best = slot;
	}
}

bool sf_store_peek(struct sf_store *s, int64_t now, uint32_t tel_ttl_ms, uint32_t protect_order,
		   sf_expire_fn on_expire, void *ctx, struct sf_view *out)
{
	struct sf_pool *pools[2];
	struct sf_slot *best = NULL;
	struct sf_pool *best_pool = NULL;
	int pass;

	out->ok = false;
	(void)sf_store_expire(s, now, tel_ttl_ms, protect_order, on_expire, ctx);
	pools[0] = &s->small;
	pools[1] = &s->large;
	for (pass = 0; pass < 2; pass++) {
		struct sf_pool *p = pools[pass];
		uint16_t i;

		if (p->nslots == 0) {
			continue;
		}
		for (i = 0; i < p->nslots; i++) {
			if (p->slot[i].order == 0 || p->slot[i].order == protect_order) {
				continue;
			}
			consider(p, i, &best);
			if (best == &p->slot[i]) {
				best_pool = p;
			}
		}
	}
	if (best == NULL || best_pool == NULL) {
		return false;
	}
	out->ok = true;
	out->order = best->order;
	out->src = best->src;
	out->dst = best->dst;
	out->next = best->next;
	out->seq = best->seq;
	out->epoch = best->epoch;
	out->hops = best->hops;
	out->ttl = best->ttl;
	out->class_ = best->class_;
	out->len = best->len;
	out->stored_ms = best->stored_ms;
	out->payload = NULL;
	{
		uint16_t i;

		for (i = 0; i < best_pool->nslots; i++) {
			if (&best_pool->slot[i] == best) {
				out->payload = sf_store_payload(best_pool, i);
				break;
			}
		}
	}
	return true;
}

bool sf_store_pop_order(struct sf_store *s, uint32_t order)
{
	struct sf_pool *pools[2] = {&s->small, &s->large};
	int pass;

	if (order == 0) {
		return false;
	}
	for (pass = 0; pass < 2; pass++) {
		struct sf_pool *p = pools[pass];
		uint16_t i;

		for (i = 0; i < p->nslots; i++) {
			if (p->slot[i].order == order) {
				release_slot(p, &p->slot[i]);
				return true;
			}
		}
	}
	return false;
}

uint16_t sf_store_flush(struct sf_store *s)
{
	uint16_t n = sf_store_used(s);
	uint16_t i;

	for (i = 0; i < s->small.nslots; i++) {
		s->small.slot[i].order = 0;
	}
	for (i = 0; i < s->large.nslots; i++) {
		s->large.slot[i].order = 0;
	}
	s->small.tel_used = 0;
	s->small.alm_used = 0;
	s->large.tel_used = 0;
	s->large.alm_used = 0;
	return n;
}
