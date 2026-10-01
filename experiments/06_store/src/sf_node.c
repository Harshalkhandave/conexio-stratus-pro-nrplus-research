/*
 * Copyright (c) 2026 Conexio Technologies, Inc
 *
 * SPDX-License-Identifier: Apache-2.0
 */

#include "sf_node.h"
#include "sf_codec.h"

#include <errno.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#ifndef EALREADY
#define EALREADY 114
#endif
#ifndef EBUSY
#define EBUSY 16
#endif
#ifndef ENOSPC
#define ENOSPC 28
#endif
#ifndef E2BIG
#define E2BIG 7
#endif
#ifndef ENOENT
#define ENOENT 2
#endif
#ifndef EINVAL
#define EINVAL 22
#endif
#ifndef EAGAIN
#define EAGAIN 11
#endif

static void emit(struct sf_node *n, const char *fmt, ...)
{
	va_list ap;

	if (n->emit == NULL) {
		return;
	}
	va_start(ap, fmt);
	(void)vsnprintf(n->line, sizeof(n->line), fmt, ap);
	va_end(ap);
	n->emit(n->emit_ctx, n->line);
}

static int64_t now_us(const struct sf_node *n)
{
	return n->clock_us != NULL ? n->clock_us() : 0;
}

static uint32_t rnd(const struct sf_node *n)
{
	return n->rng != NULL ? n->rng() : 0u;
}

static void arm_rx(struct sf_action *act, uint32_t ms)
{
	act->kind = SF_ACT_RX;
	act->inflight = false;
	act->want_ack = false;
	act->tx_len = 0;
	act->rx_ms = ms == 0u ? 1u : ms;
}

static void arm_tx(struct sf_action *act, const uint8_t *buf, uint16_t len, bool inflight)
{
	act->kind = SF_ACT_TX;
	act->inflight = inflight;
	act->want_ack = inflight;
	act->rx_ms = 0;
	act->tx_len = len;
	if (len > sizeof(act->tx)) {
		len = (uint16_t)sizeof(act->tx);
		act->tx_len = len;
	}
	memcpy(act->tx, buf, len);
}

static void on_link_change(void *ctx, const struct sf_link *link, uint8_t old_state,
			   const char *reason)
{
	struct sf_node *n = ctx;

	emit(n, "LINK_STATE: node=%u next=%u old=%s new=%s reason=%s", n->cfg.node_id, link->next_id,
	     sf_link_name(old_state), sf_link_name(link->state), reason != NULL ? reason : "-");
}

static void on_expired(void *ctx, const struct sf_slot *slot)
{
	struct sf_node *n = ctx;

	n->ct.dropped_expired++;
	emit(n, "DROP_EXPIRED: node=%u seq=%u src=%u class=%s", n->cfg.node_id, slot->seq, slot->src,
	     sf_class_name(slot->class_));
}

void sf_node_init(struct sf_node *n, const struct sf_cfg *cfg, const struct sf_route *routes,
		  unsigned int nroutes, uint16_t epoch, struct sf_store store)
{
	unsigned int i;

	memset(n, 0, sizeof(*n));
	n->cfg = *cfg;
	n->store = store;
	n->epoch = epoch;
	n->ct.epoch = epoch;
	sf_dedup_init(&n->dedup);
	sf_link_init(&n->links);
	n->alarm_tokens_m = (uint32_t)cfg->alarm_burst * 1000u;
	for (i = 0; i < nroutes && i < SF_ROUTE_CAP; i++) {
		n->route[i] = routes[i];
	}
}

void sf_node_set_emit(struct sf_node *n, sf_emit_fn fn, void *ctx)
{
	n->emit = fn;
	n->emit_ctx = ctx;
}

void sf_node_set_rng(struct sf_node *n, sf_rng_fn fn)
{
	n->rng = fn;
}

void sf_node_set_clock(struct sf_node *n, sf_us_fn fn)
{
	n->clock_us = fn;
}

bool sf_node_running(const struct sf_node *n)
{
	return n->running;
}

uint16_t sf_node_epoch(const struct sf_node *n)
{
	return n->epoch;
}

const struct sf_cfg *sf_node_cfg(const struct sf_node *n)
{
	return &n->cfg;
}

const struct sf_counters *sf_node_counters(const struct sf_node *n)
{
	return &n->ct;
}

const struct sf_store *sf_node_store(const struct sf_node *n)
{
	return &n->store;
}

static void clear_inflight(struct sf_node *n)
{
	n->inf.active = false;
	n->inf.waiting_backoff = false;
	n->inf.len = 0;
}

static void summary(struct sf_node *n)
{
	emit(n,
	     "SUMMARY: node=%u role=%s generated=%u delivered=%u stored=%u drained=%u "
	     "dropped_overflow=%u dropped_expired=%u dropped_ttl=%u dropped_flushed=%u "
	     "rejected_at_source=%u rejected_full=%u still_stored=%u in_flight=%u retries=%u "
	     "dup_rx=%u rx_gap=%u epoch=%u",
	     n->cfg.node_id, sf_role_name(n->cfg.role), n->ct.generated, n->ct.delivered,
	     n->ct.stored_total, n->ct.drained_total, n->ct.dropped_overflow, n->ct.dropped_expired,
	     n->ct.dropped_ttl, n->ct.dropped_flushed, n->ct.rejected_at_source, n->ct.rejected_full,
	     sf_store_used(&n->store), n->inf.active ? 1u : 0u, n->ct.retries, n->ct.dup_rx,
	     n->ct.rx_gap, n->epoch);
}

uint16_t sf_node_flush(struct sf_node *n, int64_t now, const char *reason)
{
	uint16_t dropped;

	(void)now;
	dropped = sf_store_flush(&n->store);
	if (n->inf.from_store) {
		clear_inflight(n);
	}
	if (dropped > 0) {
		n->ct.dropped_flushed += dropped;
		emit(n, "FLUSH: node=%u dropped=%u reason=%s", n->cfg.node_id, dropped,
		     reason != NULL ? reason : "-");
	}
	return dropped;
}

int sf_node_start(struct sf_node *n, int64_t now, uint32_t count_or_zero_for_cfg)
{
	uint16_t flushed;

	if (n->running) {
		return -EALREADY;
	}
	if (n->cfg.role > SF_ROLE_SINK) {
		return -EINVAL;
	}
	if (n->cfg.role == SF_ROLE_SOURCE && n->cfg.dest_id == 0) {
		return -EINVAL;
	}
	flushed = sf_store_flush(&n->store);
	clear_inflight(n);
	n->ack_n = 0;
	memset(&n->ct, 0, sizeof(n->ct));
	n->ct.epoch = n->epoch;
	if (flushed > 0) {
		emit(n, "FLUSH: node=%u dropped=%u reason=start", n->cfg.node_id, flushed);
	}
	n->holdoff_ms[0] = 0;
	n->holdoff_ms[1] = 0;
	n->last_gen_ms = 0;
	n->gap_until_ms = 0;
	n->next_hello_ms = now;
	n->alarm_ts_ms = now;
	n->alarm_tokens_m = (uint32_t)n->cfg.alarm_burst * 1000u;
	n->run_count = count_or_zero_for_cfg != 0u ? count_or_zero_for_cfg : n->cfg.count;
	n->running = true;
	return 0;
}

void sf_node_stop(struct sf_node *n, int64_t now, const char *reason)
{
	(void)now;
	if (!n->running) {
		return;
	}
	n->running = false;
	clear_inflight(n);
	emit(n, "STOP: node=%u reason=%s", n->cfg.node_id, reason != NULL ? reason : "user");
	summary(n);
}

static uint16_t resolve_next(const struct sf_node *n, uint16_t dst)
{
	unsigned int i;

	if (dst == 0 || dst == SF_ID_BCAST) {
		return 0;
	}
	for (i = 0; i < SF_ROUTE_CAP; i++) {
		if (n->route[i].used && n->route[i].dst == dst) {
			return n->route[i].next;
		}
	}
	if (n->cfg.direct_fallback) {
		return dst;
	}
	return 0;
}

static bool hello_enabled(const struct sf_node *n)
{
	if (n->cfg.hello_ms == 0 || n->cfg.hello_mode == SF_HELLO_OFF) {
		return false;
	}
	if (n->cfg.hello_mode == SF_HELLO_ON) {
		return true;
	}
	return n->cfg.role == SF_ROLE_RELAY || n->cfg.role == SF_ROLE_SINK;
}

static uint32_t jittered(const struct sf_node *n, uint32_t period)
{
	uint32_t window;
	uint32_t base;

	if (period < 10u) {
		return period;
	}
	window = period / 5u;
	base = period - (period / 10u);
	if (window == 0u) {
		return period;
	}
	return base + (rnd(n) % (window + 1u));
}

static uint32_t backoff_ms(const struct sf_node *n, uint8_t attempt)
{
	uint32_t span = n->cfg.backoff_max_ms;
	uint32_t min = n->cfg.backoff_min_ms;
	uint32_t cap = n->cfg.backoff_cap_ms;
	uint8_t i;

	for (i = 2; i < attempt; i++) {
		if (cap > 0 && span > cap / 2u) {
			span = cap;
			break;
		}
		span *= 2u;
	}
	if (cap > 0 && span > cap) {
		span = cap;
	}
	if (span < min) {
		span = min;
	}
	if (span <= min) {
		return min;
	}
	return min + (rnd(n) % (span - min + 1u));
}

static void fill_payload(struct sf_node *n, uint8_t *dst, uint16_t len, uint16_t seq)
{
	if (len == 0) {
		return;
	}
	memset(dst, 0xA5, len);
	dst[0] = (uint8_t)(seq & 0xffu);
	if (len > 1) {
		dst[1] = (uint8_t)(n->cfg.node_id & 0xffu);
	}
	(void)seq;
}

static int enqueue_local(struct sf_node *n, int64_t now, uint8_t class_, uint16_t seq)
{
	struct sf_slot meta;
	uint8_t payload[SF_PAYLOAD_MAX];
	struct sf_dropped dropped;
	uint16_t next;
	uint16_t len = n->cfg.payload_len;
	uint32_t order = 0;
	int rc;

	next = resolve_next(n, n->cfg.dest_id);
	if (next == 0) {
		n->ct.rejected_at_source++;
		return -ENOENT;
	}
	if (len > SF_PAYLOAD_MAX) {
		len = SF_PAYLOAD_MAX;
	}
	memset(&meta, 0, sizeof(meta));
	meta.src = n->cfg.node_id;
	meta.dst = n->cfg.dest_id;
	meta.next = next;
	meta.seq = seq;
	meta.epoch = n->epoch;
	meta.hops = 0;
	meta.ttl = n->cfg.ttl;
	meta.class_ = class_;
	meta.len = len;
	meta.stored_ms = now;
	fill_payload(n, payload, len, seq);
	if (sf_link_ensure(&n->links, next, now, n->cfg.assume_up != 0) == NULL) {
		n->ct.rejected_at_source++;
		return -ENOSPC;
	}
	rc = sf_store_put(&n->store, &meta, payload, n->cfg.policy,
			  n->inf.active ? n->inf.order : 0u, &dropped, &order);
	if (rc == -3) {
		n->ct.rejected_at_source++;
		return -ENOSPC;
	}
	if (rc != 0) {
		n->ct.rejected_at_source++;
		return -E2BIG;
	}
	if (dropped.dropped) {
		n->ct.dropped_overflow++;
		emit(n, "CUSTODY_BROKEN: node=%u seq=%u src=%u class=%s reason=drop_oldest",
		     n->cfg.node_id, dropped.seq, dropped.src, sf_class_name(dropped.class_));
		if (n->inf.active && n->inf.order == dropped.order) {
			clear_inflight(n);
		}
	}
	n->ct.stored_total++;
	n->ct.generated++;
	if (sf_store_used(&n->store) > n->ct.queue_peak) {
		n->ct.queue_peak = sf_store_used(&n->store);
	}
	emit(n, "STORED: node=%u seq=%u src=%u class=%s depth=%u", n->cfg.node_id, seq,
	     n->cfg.node_id, sf_class_name(class_), sf_store_used(&n->store));
	return 0;
}

static void maybe_generate(struct sf_node *n, int64_t now)
{
	uint8_t class_;
	uint32_t interval;

	if (!n->running || n->cfg.role != SF_ROLE_SOURCE) {
		return;
	}
	if (n->run_count != 0 && n->ct.generated >= n->run_count) {
		return;
	}
	interval = n->cfg.interval_ms;
	if (interval == 0) {
		return;
	}
	if (n->last_gen_ms != 0 && (now - n->last_gen_ms) < (int64_t)interval) {
		return;
	}
	class_ = n->cfg.gen_class == SF_CLASS_ALARM ? SF_CLASS_ALARM : SF_CLASS_TEL;
	if (enqueue_local(n, now, class_, n->seq_next[class_]) == 0) {
		n->seq_next[class_]++;
		n->last_gen_ms = now;
	} else if (n->last_gen_ms == 0 || interval == 0) {
		/* Avoid a tight loop when the first put fails. */
		n->last_gen_ms = now;
	}
}

static bool maybe_finish(struct sf_node *n, int64_t now)
{
	if (!n->running || n->cfg.role != SF_ROLE_SOURCE || n->run_count == 0) {
		return false;
	}
	if (n->ct.generated < n->run_count) {
		return false;
	}
	if (sf_store_used(&n->store) != 0 || n->inf.active || n->ack_n != 0) {
		return false;
	}
	sf_node_stop(n, now, "count_reached");
	return true;
}

static int queue_ack(struct sf_node *n, const struct sf_frame *req, uint8_t status)
{
	struct sf_frame ack;
	int len;

	if (n->ack_n >= SF_ACKQ_CAP) {
		n->ack_dropped++;
		return -ENOSPC;
	}
	memset(&ack, 0, sizeof(ack));
	ack.ver = SF_PROTO_VERSION;
	ack.type = SF_TYPE_ACK;
	ack.src = req->src;
	ack.dst = req->dst;
	ack.prev = n->cfg.node_id;
	ack.next = req->prev;
	ack.seq = req->seq;
	ack.epoch = req->epoch;
	ack.class_ = req->class_;
	ack.status = status;
	ack.queue_free = sf_store_free_for(&n->store, req->payload_len, req->class_);
	ack.node_epoch = n->epoch;
	len = sf_codec_encode(&ack, n->ackq[n->ack_n].buf, sizeof(n->ackq[0].buf), n->cfg.phy_mtu);
	if (len < 0) {
		return -EINVAL;
	}
	n->ackq[n->ack_n].len = (uint16_t)len;
	n->ack_n++;
	return 0;
}

static void note_neighbor(struct sf_node *n, uint16_t id, uint16_t epoch, bool have_epoch,
			  int16_t rssi_x2, int64_t now)
{
	struct sf_neigh *slot = NULL;
	struct sf_neigh *oldest = NULL;
	unsigned int i;

	if (id == 0 || id == n->cfg.node_id) {
		return;
	}
	for (i = 0; i < SF_NEIGH_CAP; i++) {
		if (n->neigh[i].used && n->neigh[i].id == id) {
			slot = &n->neigh[i];
			break;
		}
		if (!n->neigh[i].used && slot == NULL) {
			slot = &n->neigh[i];
		}
		if (n->neigh[i].used && (oldest == NULL || n->neigh[i].last_ms < oldest->last_ms)) {
			oldest = &n->neigh[i];
		}
	}
	if (slot == NULL) {
		slot = oldest;
	}
	if (slot == NULL) {
		return;
	}
	if (slot->used && slot->id == id && slot->have_epoch && have_epoch && epoch != slot->epoch &&
	    sf_delta16(epoch, slot->epoch) > 0) {
		struct sf_link *link;

		emit(n, "NEIGHBOR_RESET: node=%u id=%u old=%u new=%u", n->cfg.node_id, id, slot->epoch,
		     epoch);
		link = sf_link_find(&n->links, id);
		if (link != NULL) {
			sf_link_force_probe(link, now, on_link_change, n);
		}
	}
	slot->used = true;
	slot->id = id;
	slot->rssi_x2 = rssi_x2;
	slot->last_ms = now;
	slot->heard++;
	if (have_epoch) {
		slot->have_epoch = true;
		slot->epoch = epoch;
	}
}

static void log_gap_reset(struct sf_node *n, const struct sf_frame *f, const struct sf_dedup_out *d)
{
	n->ct.rx_gap = n->dedup.gaps;
	n->ct.stream_evictions = n->dedup.evictions;
	if (d->src_reset) {
		emit(n, "SRC_RESET: node=%u src=%u old=%u new=%u", n->cfg.node_id, f->src, d->old_epoch,
		     d->new_epoch);
	}
	if (d->gap > 0) {
		emit(n, "RX_GAP: node=%u src=%u class=%s n=%u", n->cfg.node_id, f->src,
		     sf_class_name(f->class_), d->gap);
	}
}

static void accept_sink(struct sf_node *n, int64_t now, const struct sf_frame *f, int16_t rssi_x2)
{
	int rssi_i = rssi_x2 / 2;
	int rssi_f = (rssi_x2 & 1) != 0 ? 5 : 0;

	n->ct.delivered++;
	emit(n,
	     "DELIVER: node=%u seq=%u src=%u prev=%u hops=%u rssi=%d.%d class=%s epoch=%u time=%lld time_us=%lld",
	     n->cfg.node_id, f->seq, f->src, f->prev, f->hops, rssi_i, rssi_f, sf_class_name(f->class_),
	     f->epoch, (long long)now, (long long)now_us(n));
	(void)queue_ack(n, f, SF_ACK_ACCEPTED);
}


static bool take_custody(struct sf_node *n, int64_t now, const struct sf_frame *f)
{
	struct sf_slot meta;
	struct sf_dropped dropped;
	uint16_t next;
	uint32_t order = 0;
	int rc;

	next = resolve_next(n, f->dst);
	if (next == 0) {
		n->ct.nack_route++;
		emit(n, "NACK_TX: node=%u status=NO_ROUTE seq=%u src=%u", n->cfg.node_id, f->seq, f->src);
		(void)queue_ack(n, f, SF_ACK_NO_ROUTE);
		return false;
	}
	memset(&meta, 0, sizeof(meta));
	meta.src = f->src;
	meta.dst = f->dst;
	meta.next = next;
	meta.seq = f->seq;
	meta.epoch = f->epoch;
	meta.hops = (uint8_t)(f->hops + 1u);
	meta.ttl = (uint8_t)(f->ttl - 1u);
	meta.class_ = f->class_;
	meta.len = f->payload_len;
	meta.stored_ms = now;
	if (sf_link_ensure(&n->links, next, now, n->cfg.assume_up != 0) == NULL) {
		n->ct.nack_route++;
		emit(n, "NACK_TX: node=%u status=NO_ROUTE seq=%u src=%u", n->cfg.node_id, f->seq, f->src);
		(void)queue_ack(n, f, SF_ACK_NO_ROUTE);
		return false;
	}
	rc = sf_store_put(&n->store, &meta, f->payload, n->cfg.policy,
			  n->inf.active ? n->inf.order : 0u, &dropped, &order);
	if (rc == -2) {
		n->ct.rx_bad_hdr++;
		if (f->class_ <= SF_CLASS_ALARM) {
			n->holdoff_ms[f->class_] = now + (int64_t)n->cfg.nack_holdoff_ms;
		}
		emit(n, "BAD_FRAME: node=%u reason=payload len=%u", n->cfg.node_id, f->payload_len);
		(void)queue_ack(n, f, SF_ACK_QUEUE_FULL);
		return false;
	}
	if (rc != 0) {
		n->ct.rejected_full++;
		n->ct.nack_full++;
		if (f->class_ <= SF_CLASS_ALARM) {
			n->holdoff_ms[f->class_] = now + (int64_t)n->cfg.nack_holdoff_ms;
		}
		emit(n, "NACK_TX: node=%u status=QUEUE_FULL seq=%u src=%u", n->cfg.node_id, f->seq,
		     f->src);
		(void)queue_ack(n, f, SF_ACK_QUEUE_FULL);
		return false;
	}
	if (dropped.dropped) {
		n->ct.dropped_overflow++;
		emit(n, "CUSTODY_BROKEN: node=%u seq=%u src=%u class=%s reason=drop_oldest",
		     n->cfg.node_id, dropped.seq, dropped.src, sf_class_name(dropped.class_));
		if (n->inf.active && dropped.order == n->inf.order) {
			clear_inflight(n);
		}
	}
	n->ct.stored_total++;
	if (sf_store_used(&n->store) > n->ct.queue_peak) {
		n->ct.queue_peak = sf_store_used(&n->store);
	}
	emit(n, "STORED: node=%u seq=%u src=%u class=%s depth=%u", n->cfg.node_id, f->seq, f->src,
	     sf_class_name(f->class_), sf_store_used(&n->store));
	(void)queue_ack(n, f, SF_ACK_ACCEPTED);
	return true;
}

static void handle_data(struct sf_node *n, int64_t now, const struct sf_frame *f, int16_t rssi_x2)
{
	struct sf_dedup_out d;
	bool commit = false;

	if (f->class_ > SF_CLASS_ALARM) {
		n->ct.rx_bad_hdr++;
		emit(n, "BAD_FRAME: node=%u reason=class value=%u", n->cfg.node_id, f->class_);
		return;
	}
	if (f->prev == n->cfg.node_id || f->next != n->cfg.node_id) {
		/* Overhearing a frame aimed at another hop is not a delivery. */
		n->ct.rx_not_mine++;
		return;
	}
	if (f->dst != n->cfg.node_id && n->cfg.role != SF_ROLE_RELAY) {
		n->ct.rx_not_mine++;
		return;
	}

	sf_dedup_check(&n->dedup, f->src, f->class_, f->epoch, f->seq, now, n->cfg.stream_idle_ms,
		       n->cfg.dedup_on != 0, &d);
	n->ct.dup_rx = n->dedup.dups;
	n->ct.rx_stale_epoch = n->dedup.stale_epoch;
	if (d.result == SF_DEDUP_DUP || d.result == SF_DEDUP_STALE_EPOCH) {
		(void)queue_ack(n, f, SF_ACK_DUPLICATE);
		return;
	}

	if (f->dst == n->cfg.node_id) {
		commit = true;
		accept_sink(n, now, f, rssi_x2);
	} else if (f->ttl == 0) {
		commit = true;
		n->ct.dropped_ttl++;
		emit(n, "DROP_TTL: node=%u seq=%u src=%u", n->cfg.node_id, f->seq, f->src);
		(void)queue_ack(n, f, SF_ACK_TTL_EXPIRED);
	} else {
		commit = take_custody(n, now, f);
	}
	if (commit) {
		sf_dedup_commit(&n->dedup, f->src, f->class_, f->epoch, f->seq, now);
		log_gap_reset(n, f, &d);
	}
}


static void handle_ack(struct sf_node *n, int64_t now, const struct sf_frame *f)
{
	uint32_t hold;
	int64_t rtt;

	if (!n->inf.active) {
		n->ct.rx_stale_ack++;
		return;
	}
	if (f->prev != n->inf.next_id || f->src != n->inf.src || f->seq != n->inf.seq ||
	    f->epoch != n->inf.epoch || f->class_ != n->inf.class_) {
		n->ct.rx_stale_ack++;
		return;
	}
	rtt = n->inf.tx_done_ms > 0 ? (now - n->inf.tx_done_ms) : 0;
	emit(n, "ACK_RX: node=%u status=%s seq=%u from=%u rtt_ms=%lld class=%s", n->cfg.node_id,
	     sf_ack_name(f->status), f->seq, f->prev, (long long)rtt, sf_class_name(f->class_));

	if (n->inf.type == SF_TYPE_PROBE) {
		if (f->status == SF_ACK_PROBE_REPLY) {
			struct sf_link *link = sf_link_find(&n->links, n->inf.next_id);

			sf_link_probe_ok(link, now, n->cfg.n_up, n->cfg.probe_fast_ms, on_link_change, n);
			clear_inflight(n);
			if (n->cfg.inter_tx_listen_ms > 0) {
				n->gap_until_ms = now + (int64_t)n->cfg.inter_tx_listen_ms;
			}
			return;
		}
		n->ct.rx_stale_ack++;
		return;
	}

	switch (f->status) {
	case SF_ACK_ACCEPTED:
	case SF_ACK_DUPLICATE:
		if (n->inf.from_store && sf_store_pop_order(&n->store, n->inf.order)) {
			n->ct.drained_total++;
		}
		clear_inflight(n);
		if (n->cfg.inter_tx_listen_ms > 0) {
			n->gap_until_ms = now + (int64_t)n->cfg.inter_tx_listen_ms;
		}
		break;
	case SF_ACK_TTL_EXPIRED:
		if (n->inf.from_store) {
			(void)sf_store_pop_order(&n->store, n->inf.order);
		}
		n->ct.dropped_ttl++;
		emit(n, "DROP_TTL: node=%u seq=%u src=%u reason=peer", n->cfg.node_id, f->seq, f->src);
		clear_inflight(n);
		if (n->cfg.inter_tx_listen_ms > 0) {
			n->gap_until_ms = now + (int64_t)n->cfg.inter_tx_listen_ms;
		}
		break;
	case SF_ACK_QUEUE_FULL:
	case SF_ACK_NO_ROUTE:
		hold = n->cfg.nack_holdoff_ms;
		if (f->status == SF_ACK_QUEUE_FULL && f->queue_free == 0 && hold < 60000u) {
			hold *= 2u;
		}
		if (f->class_ <= SF_CLASS_ALARM) {
			n->holdoff_ms[f->class_] = now + (int64_t)hold;
		}
		emit(n, "NACK_RX: node=%u status=%s seq=%u from=%u hold_ms=%u", n->cfg.node_id,
		     sf_ack_name(f->status), f->seq, f->prev, hold);
		clear_inflight(n);
		break;
	default:
		n->ct.rx_stale_ack++;
		break;
	}
}

static void handle_hello(struct sf_node *n, int64_t now, const struct sf_frame *f, int16_t rssi_x2)
{
	struct sf_link *link = sf_link_find(&n->links, f->src);

	note_neighbor(n, f->src, f->epoch, true, rssi_x2, now);
	if (link != NULL) {
		sf_link_note_hello(link, now);
	}
}

static void handle_probe(struct sf_node *n, int64_t now, const struct sf_frame *f, int16_t rssi_x2)
{
	(void)now;
	note_neighbor(n, f->src, f->epoch, true, rssi_x2, now);
	if (f->next != n->cfg.node_id) {
		n->ct.rx_not_mine++;
		return;
	}
	(void)queue_ack(n, f, SF_ACK_PROBE_REPLY);
}

void sf_node_on_rx(struct sf_node *n, int64_t now, const uint8_t *data, uint16_t len, int16_t rssi_x2)
{
	struct sf_frame f;
	int rc;
	int rssi_i = rssi_x2 / 2;
	int rssi_f = (rssi_x2 & 1) != 0 ? 5 : 0;

	rc = sf_codec_decode(data, len, n->cfg.phy_mtu, &f);
	if (rc != SF_CODEC_OK) {
		n->ct.rx_bad_hdr++;
		emit(n, "BAD_FRAME: node=%u reason=%d len=%u rssi=%d.%d", n->cfg.node_id, rc, len, rssi_i,
		     rssi_f);
		return;
	}
	emit(n,
	     "RX: node=%u type=%s seq=%u src=%u dst=%u prev=%u next=%u hop=%u ttl=%u rssi=%d.%d class=%s epoch=%u time=%lld time_us=%lld",
	     n->cfg.node_id, sf_type_name(f.type), f.seq, f.src, f.dst, f.prev, f.next, f.hops, f.ttl,
	     rssi_i, rssi_f, sf_class_name(f.class_), f.epoch, (long long)now, (long long)now_us(n));

	if (f.type == SF_TYPE_ACK) {
		note_neighbor(n, f.prev, f.node_epoch, true, rssi_x2, now);
		handle_ack(n, now, &f);
		return;
	}
	if (f.type == SF_TYPE_HELLO) {
		handle_hello(n, now, &f, rssi_x2);
		return;
	}
	if (f.type == SF_TYPE_PROBE) {
		handle_probe(n, now, &f, rssi_x2);
		return;
	}
	if (f.type == SF_TYPE_DATA) {
		if (f.prev != 0) {
			note_neighbor(n, f.prev, 0, false, rssi_x2, now);
		}
		handle_data(n, now, &f, rssi_x2);
	}
}

static bool encode_ctrl(struct sf_node *n, struct sf_frame *f, uint8_t *buf, uint16_t *len)
{
	int nlen = sf_codec_encode(f, buf, SF_PAYLOAD_MAX, n->cfg.phy_mtu);

	if (nlen < 0) {
		return false;
	}
	*len = (uint16_t)nlen;
	return true;
}

static bool arm_data(struct sf_node *n, int64_t now, const struct sf_view *v, struct sf_action *act)
{
	struct sf_frame f;
	uint8_t buf[SF_PAYLOAD_MAX];
	uint16_t len = 0;

	memset(&f, 0, sizeof(f));
	f.ver = SF_PROTO_VERSION;
	f.type = SF_TYPE_DATA;
	f.class_ = v->class_;
	f.src = v->src;
	f.dst = v->dst;
	f.prev = n->cfg.node_id;
	f.next = v->next;
	f.seq = v->seq;
	f.epoch = v->epoch;
	f.hops = v->hops;
	f.ttl = v->ttl;
	f.payload_len = v->len;
	if (v->len > 0 && v->payload != NULL) {
		memcpy(f.payload, v->payload, v->len);
	}
	if (!encode_ctrl(n, &f, buf, &len)) {
		return false;
	}
	n->inf.active = true;
	n->inf.from_store = true;
	n->inf.waiting_backoff = false;
	n->inf.type = SF_TYPE_DATA;
	n->inf.attempts = 1;
	n->inf.class_ = v->class_;
	n->inf.next_id = v->next;
	n->inf.src = v->src;
	n->inf.seq = v->seq;
	n->inf.epoch = v->epoch;
	n->inf.order = v->order;
	n->inf.deadline_ms = INT64_MAX;
	n->inf.tx_done_ms = 0;
	n->inf.len = len;
	memcpy(n->inf.buf, buf, len);
	arm_tx(act, buf, len, true);
	emit(n,
	     "TX: node=%u type=DATA seq=%u src=%u dst=%u prev=%u next=%u hop=%u ttl=%u class=%s epoch=%u retx=0 time=%lld time_us=%lld",
	     n->cfg.node_id, v->seq, v->src, v->dst, n->cfg.node_id, v->next, v->hops, v->ttl,
	     sf_class_name(v->class_), v->epoch, (long long)now, (long long)now_us(n));
	return true;
}

static bool arm_probe(struct sf_node *n, int64_t now, struct sf_link *link, struct sf_action *act)
{
	struct sf_frame f;
	uint8_t buf[SF_PAYLOAD_MAX];
	uint16_t len = 0;

	memset(&f, 0, sizeof(f));
	f.ver = SF_PROTO_VERSION;
	f.type = SF_TYPE_PROBE;
	f.src = n->cfg.node_id;
	f.dst = link->next_id;
	f.prev = n->cfg.node_id;
	f.next = link->next_id;
	f.seq = (uint16_t)(++n->probe_nonce);
	f.epoch = n->epoch;
	f.ttl = 1;
	if (!encode_ctrl(n, &f, buf, &len)) {
		return false;
	}
	n->inf.active = true;
	n->inf.from_store = false;
	n->inf.waiting_backoff = false;
	n->inf.type = SF_TYPE_PROBE;
	n->inf.attempts = 1;
	n->inf.class_ = 0;
	n->inf.next_id = link->next_id;
	n->inf.src = n->cfg.node_id;
	n->inf.seq = f.seq;
	n->inf.epoch = n->epoch;
	n->inf.order = 0;
	n->inf.deadline_ms = INT64_MAX;
	n->inf.len = len;
	memcpy(n->inf.buf, buf, len);
	link->next_probe_ms = now + (int64_t)n->cfg.probe_fast_ms;
	n->ct.probe_tx++;
	arm_tx(act, buf, len, true);
	emit(n, "TX: node=%u type=PROBE seq=%u next=%u epoch=%u time=%lld time_us=%lld", n->cfg.node_id,
	     f.seq, link->next_id, n->epoch, (long long)now, (long long)now_us(n));
	return true;
}

static bool arm_hello(struct sf_node *n, int64_t now, struct sf_action *act)
{
	struct sf_frame f;
	uint8_t buf[SF_PAYLOAD_MAX];
	uint16_t len = 0;

	memset(&f, 0, sizeof(f));
	f.ver = SF_PROTO_VERSION;
	f.type = SF_TYPE_HELLO;
	f.src = n->cfg.node_id;
	f.dst = SF_ID_BCAST;
	f.prev = n->cfg.node_id;
	f.next = SF_ID_BCAST;
	f.epoch = n->epoch;
	f.role = n->cfg.role;
	f.free_pct = sf_store_free_pct(&n->store);
	if (!encode_ctrl(n, &f, buf, &len)) {
		return false;
	}
	n->ct.hello_tx++;
	n->next_hello_ms = now + (int64_t)jittered(n, n->cfg.hello_ms);
	arm_tx(act, buf, len, false);
	emit(n, "TX: node=%u type=HELLO role=%s free_pct=%u epoch=%u time=%lld time_us=%lld",
	     n->cfg.node_id, sf_role_name(n->cfg.role), f.free_pct, n->epoch, (long long)now,
	     (long long)now_us(n));
	return true;
}

static void fail_inflight(struct sf_node *n, int64_t now)
{
	struct sf_link *link = sf_link_find(&n->links, n->inf.next_id);

	sf_link_fail(link, now, "max_attempts", n->cfg.holddown_min_ms, n->cfg.holddown_max_ms,
		     n->cfg.holddown_reset_ms, n->cfg.t_probe_ms, on_link_change, n);
	clear_inflight(n);
}

static bool service_timeout(struct sf_node *n, int64_t now, struct sf_action *act)
{
	uint32_t delay;

	if (!n->inf.active || n->inf.waiting_backoff || n->inf.deadline_ms == INT64_MAX) {
		return false;
	}
	if (now < n->inf.deadline_ms) {
		return false;
	}
	if (n->inf.attempts >= n->cfg.max_attempts) {
		fail_inflight(n, now);
		return false;
	}
	n->inf.attempts++;
	n->inf.buf[1] = (uint8_t)(n->inf.buf[1] | SF_FLAG_RETX);
	n->ct.retries++;
	delay = backoff_ms(n, n->inf.attempts);
	emit(n, "RETRY: node=%u seq=%u attempt=%u backoff_ms=%u", n->cfg.node_id, n->inf.seq,
	     n->inf.attempts, delay);
	if (delay > 0) {
		n->inf.waiting_backoff = true;
		n->inf.backoff_until_ms = now + (int64_t)delay;
		return false;
	}
	n->inf.deadline_ms = INT64_MAX;
	n->inf.waiting_backoff = false;
	arm_tx(act, n->inf.buf, n->inf.len, true);
	return true;
}

void sf_node_on_tx_done(struct sf_node *n, int64_t now, bool ok, bool was_inflight)
{
	if (!was_inflight || !n->inf.active) {
		if (n->cfg.inter_tx_listen_ms > 0) {
			n->gap_until_ms = now + (int64_t)n->cfg.inter_tx_listen_ms;
		}
		return;
	}
	n->inf.tx_done_ms = now;
	if (!ok) {
		n->inf.deadline_ms = now;
		return;
	}
	n->inf.deadline_ms = now + (int64_t)n->cfg.ack_timeout_ms;
	n->inf.waiting_backoff = false;
}

void sf_node_poll(struct sf_node *n, int64_t now, struct sf_action *act)
{
	struct sf_view view;
	uint32_t protect;

	memset(act, 0, sizeof(*act));
	arm_rx(act, n->cfg.rx_slice_ms);
	if (maybe_finish(n, now)) {
		return;
	}
	protect = n->inf.active && n->inf.from_store ? n->inf.order : 0u;
	(void)sf_store_expire(&n->store, now, n->cfg.telemetry_ttl_ms, protect, on_expired, n);
	sf_dedup_sweep(&n->dedup, now, n->cfg.stream_idle_ms);
	n->ct.stream_evictions = n->dedup.evictions;
	if (n->running) {
		maybe_generate(n, now);
	}
	sf_link_tick(&n->links, now, n->cfg.hello_dead_ms, n->cfg.t_probe_ms, n->cfg.holddown_min_ms,
		     n->cfg.holddown_max_ms, n->cfg.holddown_reset_ms, on_link_change, n);

	if (n->ack_n > 0) {
		struct sf_ack_slot slot = n->ackq[0];
		unsigned int i;

		for (i = 1; i < n->ack_n; i++) {
			n->ackq[i - 1] = n->ackq[i];
		}
		n->ack_n--;
		n->ct.ack_tx++;
		arm_tx(act, slot.buf, slot.len, false);
		emit(n, "ACK_TX: node=%u status=%s seq=%u len=%u time=%lld", n->cfg.node_id,
		     slot.len >= SF_ACK_LEN ? sf_ack_name(slot.buf[16]) : "SHORT",
		     slot.len >= SF_HDR_LEN ? (unsigned)(slot.buf[10] | (slot.buf[11] << 8)) : 0u, slot.len,
		     (long long)now);
		return;
	}

	if (n->inf.active && n->inf.waiting_backoff) {
		if (now < n->inf.backoff_until_ms) {
			uint32_t left = (uint32_t)(n->inf.backoff_until_ms - now);

			arm_rx(act, left);
			return;
		}
		n->inf.waiting_backoff = false;
		n->inf.deadline_ms = INT64_MAX;
		arm_tx(act, n->inf.buf, n->inf.len, true);
		return;
	}

	if (service_timeout(n, now, act)) {
		return;
	}
	if (n->inf.waiting_backoff) {
		uint32_t left = 1;

		if (n->inf.backoff_until_ms > now) {
			left = (uint32_t)(n->inf.backoff_until_ms - now);
		}
		arm_rx(act, left);
		return;
	}
	if (n->inf.active) {
		uint32_t left = n->cfg.ack_timeout_ms;

		if (n->inf.deadline_ms != INT64_MAX && n->inf.deadline_ms > now) {
			left = (uint32_t)(n->inf.deadline_ms - now);
		}
		arm_rx(act, left);
		return;
	}

	if (n->gap_until_ms > now) {
		arm_rx(act, (uint32_t)(n->gap_until_ms - now));
		return;
	}

	if (n->running && hello_enabled(n) && now >= n->next_hello_ms) {
		if (arm_hello(n, now, act)) {
			return;
		}
	}

	if (n->running) {
		unsigned int i;

		for (i = 0; i < SF_LINK_CAP; i++) {
			struct sf_link *link = &n->links.item[i];

			if (!link->used || link->state != SF_LINK_PROBING) {
				continue;
			}
			if (now < link->next_probe_ms) {
				continue;
			}
			if (arm_probe(n, now, link, act)) {
				return;
			}
		}
	}

	if (n->running &&
	    sf_store_peek(&n->store, now, n->cfg.telemetry_ttl_ms, 0, on_expired, n, &view)) {
		struct sf_link *link = sf_link_find(&n->links, view.next);
		uint8_t class_ = view.class_ <= SF_CLASS_ALARM ? view.class_ : SF_CLASS_TEL;

		if (link != NULL && link->state == SF_LINK_UP && now >= n->holdoff_ms[class_]) {
			if (arm_data(n, now, &view, act)) {
				return;
			}
		}
	}

	if (maybe_finish(n, now)) {
		return;
	}
	arm_rx(act, n->cfg.rx_slice_ms);
}

int sf_node_alarm(struct sf_node *n, int64_t now)
{
	uint32_t add;
	int64_t elapsed;

	if (!n->running || n->cfg.role != SF_ROLE_SOURCE) {
		return -EINVAL;
	}
	if (n->cfg.alarm_rate == 0 || n->cfg.alarm_burst == 0) {
		return -EAGAIN;
	}
	elapsed = now - n->alarm_ts_ms;
	if (elapsed > 0) {
		add = n->cfg.alarm_rate * (uint32_t)elapsed;
		if (n->alarm_tokens_m <= UINT32_MAX - add) {
			n->alarm_tokens_m += add;
		}
		n->alarm_ts_ms = now;
	}
	if (n->alarm_tokens_m > (uint32_t)n->cfg.alarm_burst * 1000u) {
		n->alarm_tokens_m = (uint32_t)n->cfg.alarm_burst * 1000u;
	}
	if (n->alarm_tokens_m < 1000u) {
		n->ct.rejected_at_source++;
		return -EAGAIN;
	}
	if (enqueue_local(n, now, SF_CLASS_ALARM, n->seq_next[SF_CLASS_ALARM]) != 0) {
		return -ENOSPC;
	}
	n->alarm_tokens_m -= 1000u;
	n->seq_next[SF_CLASS_ALARM]++;
	return 0;
}


static int parse_u32(const char *s, uint32_t *out)
{
	char *end = NULL;
	unsigned long v;

	if (s == NULL || *s == '\0') {
		return -EINVAL;
	}
	v = strtoul(s, &end, 0);
	if (end == s || *end != '\0') {
		return -EINVAL;
	}
	*out = (uint32_t)v;
	return 0;
}

static int parse_onoff(const char *s, uint8_t *out)
{
	if (strcmp(s, "on") == 0 || strcmp(s, "1") == 0) {
		*out = 1;
		return 0;
	}
	if (strcmp(s, "off") == 0 || strcmp(s, "0") == 0) {
		*out = 0;
		return 0;
	}
	return -EINVAL;
}

static bool key_blocked(const char *key)
{
	static const char *const blocked[] = {
		"dest", "size", "ttl", "direct", "assume_up", "dedup", "class", "hello_tx", "role",
	};
	unsigned int i;

	for (i = 0; i < sizeof(blocked) / sizeof(blocked[0]); i++) {
		if (strcmp(key, blocked[i]) == 0) {
			return true;
		}
	}
	return false;
}

static int set_err(char *err, size_t err_len, const char *msg)
{
	if (err != NULL && err_len > 0) {
		(void)snprintf(err, err_len, "%s", msg);
	}
	return -EINVAL;
}

void sf_node_apply_cfg(struct sf_node *n, const struct sf_cfg *cfg)
{
	uint16_t id = n->cfg.node_id;

	n->cfg = *cfg;
	n->cfg.node_id = id;
}

void sf_node_route_clear(struct sf_node *n)
{
	unsigned int i;

	for (i = 0; i < SF_ROUTE_CAP; i++) {
		n->route[i].used = false;
	}
}

int sf_node_route_set(struct sf_node *n, uint16_t dst, uint16_t next, char *err, size_t err_len)
{
	unsigned int i;
	int free_i = -1;

	if (n->running) {
		if (err != NULL && err_len > 0) {
			(void)snprintf(err, err_len, "%s", "stop the run before changing routes");
		}
		return -EBUSY;
	}
	if (dst == 0 || dst == SF_ID_BCAST || next == 0 || next == SF_ID_BCAST) {
		return set_err(err, err_len, "dst and next must be 1..65534");
	}
	for (i = 0; i < SF_ROUTE_CAP; i++) {
		if (n->route[i].used && n->route[i].dst == dst) {
			n->route[i].next = next;
			return 0;
		}
		if (!n->route[i].used && free_i < 0) {
			free_i = (int)i;
		}
	}
	if (free_i < 0) {
		return set_err(err, err_len, "route table full");
	}
	n->route[free_i].used = true;
	n->route[free_i].dst = dst;
	n->route[free_i].next = next;
	return 0;
}

int sf_node_route_del(struct sf_node *n, uint16_t dst)
{
	unsigned int i;

	if (n->running) {
		return -EBUSY;
	}
	for (i = 0; i < SF_ROUTE_CAP; i++) {
		if (n->route[i].used && n->route[i].dst == dst) {
			n->route[i].used = false;
			return 0;
		}
	}
	return -ENOENT;
}

unsigned int sf_node_route_export(const struct sf_node *n, struct sf_route *out, unsigned int cap)
{
	unsigned int i;
	unsigned int nout = 0;

	for (i = 0; i < SF_ROUTE_CAP && nout < cap; i++) {
		if (n->route[i].used) {
			out[nout++] = n->route[i];
		}
	}
	return nout;
}

int sf_node_set(struct sf_node *n, const char *key, const char *value, char *err, size_t err_len)
{
	uint32_t v;
	uint8_t bit;

	if (key == NULL || value == NULL) {
		return set_err(err, err_len, "missing key or value");
	}
	if (n->running && key_blocked(key)) {
		if (err != NULL && err_len > 0) {
			(void)snprintf(err, err_len, "stop the run before changing %s", key);
		}
		return -EBUSY;
	}
	if (strcmp(key, "role") == 0) {
		uint8_t role;

		if (strcmp(value, "source") == 0 || strcmp(value, "src") == 0) {
			role = SF_ROLE_SOURCE;
		} else if (strcmp(value, "relay") == 0 || strcmp(value, "router") == 0) {
			role = SF_ROLE_RELAY;
		} else if (strcmp(value, "sink") == 0 || strcmp(value, "gateway") == 0) {
			role = SF_ROLE_SINK;
		} else {
			return set_err(err, err_len, "role is source|relay|sink");
		}
		if (role != n->cfg.role) {
			(void)sf_node_flush(n, 0, "role");
		}
		n->cfg.role = role;
		return 0;
	}
	if (strcmp(key, "policy") == 0) {
		if (strcmp(value, "reject") == 0) {
			n->cfg.policy = SF_POLICY_REJECT;
		} else if (strcmp(value, "drop_oldest") == 0) {
			n->cfg.policy = SF_POLICY_DROP_OLDEST;
		} else {
			return set_err(err, err_len, "policy is reject|drop_oldest");
		}
		return 0;
	}
	if (strcmp(key, "class") == 0) {
		if (strcmp(value, "tel") == 0 || strcmp(value, "telemetry") == 0) {
			n->cfg.gen_class = SF_CLASS_TEL;
		} else if (strcmp(value, "alarm") == 0) {
			n->cfg.gen_class = SF_CLASS_ALARM;
		} else {
			return set_err(err, err_len, "class is tel|alarm");
		}
		return 0;
	}
	if (strcmp(key, "hello_tx") == 0) {
		if (strcmp(value, "auto") == 0) {
			n->cfg.hello_mode = SF_HELLO_AUTO;
		} else if (strcmp(value, "on") == 0) {
			n->cfg.hello_mode = SF_HELLO_ON;
		} else if (strcmp(value, "off") == 0) {
			n->cfg.hello_mode = SF_HELLO_OFF;
		} else {
			return set_err(err, err_len, "hello_tx is auto|on|off");
		}
		return 0;
	}
	if (strcmp(key, "direct") == 0 || strcmp(key, "assume_up") == 0 || strcmp(key, "dedup") == 0) {
		if (parse_onoff(value, &bit) != 0) {
			return set_err(err, err_len, "value is on|off");
		}
		if (strcmp(key, "direct") == 0) {
			n->cfg.direct_fallback = bit;
		} else if (strcmp(key, "assume_up") == 0) {
			n->cfg.assume_up = bit;
		} else {
			n->cfg.dedup_on = bit;
		}
		return 0;
	}
	if (parse_u32(value, &v) != 0) {
		return set_err(err, err_len, "value is not an integer");
	}
	if (strcmp(key, "dest") == 0 && v <= 65535u) {
		n->cfg.dest_id = (uint16_t)v;
	} else if (strcmp(key, "interval") == 0) {
		n->cfg.interval_ms = v;
	} else if (strcmp(key, "hello") == 0) {
		n->cfg.hello_ms = v;
	} else if (strcmp(key, "count") == 0) {
		n->cfg.count = v;
	} else if (strcmp(key, "power") == 0 && v <= 13u) {
		n->cfg.tx_power = (uint8_t)v;
	} else if (strcmp(key, "mcs") == 0 && v <= 7u) {
		n->cfg.mcs = (uint8_t)v;
	} else if (strcmp(key, "size") == 0) {
		uint16_t max = (uint16_t)(n->cfg.phy_mtu > SF_HDR_LEN ? n->cfg.phy_mtu - SF_HDR_LEN : 0);
		bool fits = v <= n->store.small.cap ||
			    (n->store.large.nslots > 0 && v <= n->store.large.cap);

		if (v == 0 || v > max || !fits) {
			return set_err(err, err_len, "size does not fit the configured pools or PHY MTU");
		}
		n->cfg.payload_len = (uint16_t)v;
	} else if (strcmp(key, "ttl") == 0 && v >= 1u && v <= 16u) {
		n->cfg.ttl = (uint8_t)v;
	} else if (strcmp(key, "ack_timeout") == 0 && v >= 1u) {
		n->cfg.ack_timeout_ms = v;
	} else if (strcmp(key, "attempts") == 0 && v >= 1u && v <= 8u) {
		n->cfg.max_attempts = (uint8_t)v;
	} else if (strcmp(key, "backoff_min") == 0) {
		n->cfg.backoff_min_ms = v;
	} else if (strcmp(key, "backoff_max") == 0) {
		n->cfg.backoff_max_ms = v;
	} else if (strcmp(key, "backoff_cap") == 0) {
		n->cfg.backoff_cap_ms = v;
	} else if (strcmp(key, "nack_holdoff") == 0) {
		n->cfg.nack_holdoff_ms = v;
	} else if (strcmp(key, "gap") == 0) {
		n->cfg.inter_tx_listen_ms = v;
	} else if (strcmp(key, "rx_slice") == 0 && v >= 1u) {
		n->cfg.rx_slice_ms = v;
	} else if (strcmp(key, "hello_dead") == 0) {
		n->cfg.hello_dead_ms = v;
	} else if (strcmp(key, "t_probe") == 0) {
		n->cfg.t_probe_ms = v;
	} else if (strcmp(key, "probe_fast") == 0) {
		n->cfg.probe_fast_ms = v;
	} else if (strcmp(key, "n_up") == 0 && v >= 1u && v <= 8u) {
		n->cfg.n_up = (uint8_t)v;
	} else if (strcmp(key, "hold_min") == 0) {
		n->cfg.holddown_min_ms = v;
	} else if (strcmp(key, "hold_max") == 0) {
		n->cfg.holddown_max_ms = v;
	} else if (strcmp(key, "hold_reset") == 0) {
		n->cfg.holddown_reset_ms = v;
	} else if (strcmp(key, "tel_ttl") == 0) {
		n->cfg.telemetry_ttl_ms = v;
	} else if (strcmp(key, "stream_idle") == 0) {
		n->cfg.stream_idle_ms = v;
	} else if (strcmp(key, "alarm_rate") == 0) {
		n->cfg.alarm_rate = v;
	} else if (strcmp(key, "alarm_burst") == 0 && v <= 255u) {
		n->cfg.alarm_burst = (uint8_t)v;
	} else {
		return set_err(err, err_len, "unknown key or value out of range");
	}
	if (n->cfg.backoff_min_ms > n->cfg.backoff_max_ms) {
		n->cfg.backoff_max_ms = n->cfg.backoff_min_ms;
	}
	return 0;
}

static void say(sf_print_fn fn, void *ctx, const char *fmt, ...)
{
	char line[200];
	va_list ap;

	va_start(ap, fmt);
	(void)vsnprintf(line, sizeof(line), fmt, ap);
	va_end(ap);
	fn(ctx, line);
}

void sf_node_dump_cfg(const struct sf_node *n, sf_print_fn fn, void *ctx)
{
	const struct sf_cfg *c = &n->cfg;
	const char *hello = c->hello_mode == SF_HELLO_ON ? "on" :
			    c->hello_mode == SF_HELLO_OFF ? "off" : "auto";

	say(fn, ctx, "role=%s", sf_role_name(c->role));
	say(fn, ctx, "dest=%u", c->dest_id);
	say(fn, ctx, "interval=%u", c->interval_ms);
	say(fn, ctx, "hello=%u", c->hello_ms);
	say(fn, ctx, "count=%u", c->count);
	say(fn, ctx, "power=%u", c->tx_power);
	say(fn, ctx, "mcs=%u", c->mcs);
	say(fn, ctx, "size=%u", c->payload_len);
	say(fn, ctx, "ttl=%u", c->ttl);
	say(fn, ctx, "policy=%s", c->policy == SF_POLICY_DROP_OLDEST ? "drop_oldest" : "reject");
	say(fn, ctx, "assume_up=%s", c->assume_up ? "on" : "off");
	say(fn, ctx, "direct=%s", c->direct_fallback ? "on" : "off");
	say(fn, ctx, "class=%s", sf_class_name(c->gen_class));
	say(fn, ctx, "hello_tx=%s", hello);
	say(fn, ctx, "dedup=%s", c->dedup_on ? "on" : "off");
	say(fn, ctx, "ack_timeout=%u", c->ack_timeout_ms);
	say(fn, ctx, "attempts=%u", c->max_attempts);
	say(fn, ctx, "backoff_min=%u", c->backoff_min_ms);
	say(fn, ctx, "backoff_max=%u", c->backoff_max_ms);
	say(fn, ctx, "backoff_cap=%u", c->backoff_cap_ms);
	say(fn, ctx, "nack_holdoff=%u", c->nack_holdoff_ms);
	say(fn, ctx, "gap=%u", c->inter_tx_listen_ms);
	say(fn, ctx, "rx_slice=%u", c->rx_slice_ms);
	say(fn, ctx, "hello_dead=%u", c->hello_dead_ms);
	say(fn, ctx, "t_probe=%u", c->t_probe_ms);
	say(fn, ctx, "probe_fast=%u", c->probe_fast_ms);
	say(fn, ctx, "n_up=%u", c->n_up);
	say(fn, ctx, "hold_min=%u", c->holddown_min_ms);
	say(fn, ctx, "hold_max=%u", c->holddown_max_ms);
	say(fn, ctx, "hold_reset=%u", c->holddown_reset_ms);
	say(fn, ctx, "tel_ttl=%u", c->telemetry_ttl_ms);
	say(fn, ctx, "stream_idle=%u", c->stream_idle_ms);
	say(fn, ctx, "alarm_rate=%u", c->alarm_rate);
	say(fn, ctx, "alarm_burst=%u", c->alarm_burst);
}

void sf_node_status(const struct sf_node *n, int64_t now, sf_print_fn fn, void *ctx)
{
	(void)now;
	say(fn, ctx, "node=%u role=%s running=%u epoch=%u proto=%u", n->cfg.node_id,
	    sf_role_name(n->cfg.role), n->running ? 1u : 0u, n->epoch, SF_PROTO_VERSION);
	say(fn, ctx, "dest=%u size=%u ttl=%u power=%u mcs=%u interval=%u count=%u hello=%u",
	    n->cfg.dest_id, n->cfg.payload_len, n->cfg.ttl, n->cfg.tx_power, n->cfg.mcs,
	    n->cfg.interval_ms, n->running ? n->run_count : n->cfg.count, n->cfg.hello_ms);
	say(fn, ctx, "generated=%u delivered=%u stored=%u drained=%u depth=%u peak=%u in_flight=%u",
	    n->ct.generated, n->ct.delivered, n->ct.stored_total, n->ct.drained_total,
	    sf_store_used(&n->store), n->ct.queue_peak, n->inf.active ? 1u : 0u);
	say(fn, ctx, "retries=%u dup_rx=%u rx_gap=%u bad=%u stale_ack=%u rejected_src=%u rejected_full=%u",
	    n->ct.retries, n->ct.dup_rx, n->ct.rx_gap, n->ct.rx_bad_hdr, n->ct.rx_stale_ack,
	    n->ct.rejected_at_source, n->ct.rejected_full);
	say(fn, ctx, "drop_overflow=%u drop_expired=%u drop_ttl=%u drop_flush=%u", n->ct.dropped_overflow,
	    n->ct.dropped_expired, n->ct.dropped_ttl, n->ct.dropped_flushed);
	if (n->inf.active) {
		say(fn, ctx, "inflight type=%s seq=%u next=%u attempt=%u", sf_type_name(n->inf.type),
		    n->inf.seq, n->inf.next_id, n->inf.attempts);
	}
}

void sf_node_report_sf(const struct sf_node *n, sf_print_fn fn, void *ctx)
{
	say(fn, ctx, "small_used=%u small_slots=%u small_cap=%u alarm_rsv=%u",
	    (unsigned)(n->store.small.tel_used + n->store.small.alm_used), n->store.small.nslots,
	    n->store.small.cap, n->store.small.alarm_reserved);
	say(fn, ctx, "tel_used=%u alm_used=%u tel_free64=%u alm_free64=%u", n->store.small.tel_used,
	    n->store.small.alm_used, sf_store_free_for(&n->store, 1, SF_CLASS_TEL),
	    sf_store_free_for(&n->store, 1, SF_CLASS_ALARM));
	say(fn, ctx, "large_used=%u large_slots=%u peak=%u policy=%s",
	    (unsigned)(n->store.large.tel_used + n->store.large.alm_used), n->store.large.nslots,
	    n->store.peak, n->cfg.policy == SF_POLICY_DROP_OLDEST ? "drop_oldest" : "reject");
	say(fn, ctx, "free_pct=%u ack_dropped=%u", sf_store_free_pct(&n->store), n->ack_dropped);
}

void sf_node_report_link(const struct sf_node *n, sf_print_fn fn, void *ctx)
{
	unsigned int i;
	bool any = false;

	for (i = 0; i < SF_LINK_CAP; i++) {
		const struct sf_link *l = &n->links.item[i];

		if (!l->used) {
			continue;
		}
		any = true;
		say(fn, ctx, "next=%u state=%s consec=%u heard_hello=%u streak=%u", l->next_id,
		    sf_link_name(l->state), l->consec, l->heard_hello ? 1u : 0u, l->down_streak);
	}
	if (!any) {
		say(fn, ctx, "no links yet");
	}
}

void sf_node_report_neigh(const struct sf_node *n, sf_print_fn fn, void *ctx)
{
	unsigned int i;
	bool any = false;

	for (i = 0; i < SF_NEIGH_CAP; i++) {
		const struct sf_neigh *h = &n->neigh[i];
		int rssi_i;
		int rssi_f;

		if (!h->used) {
			continue;
		}
		any = true;
		rssi_i = h->rssi_x2 / 2;
		rssi_f = (h->rssi_x2 & 1) != 0 ? 5 : 0;
		say(fn, ctx, "id=%u rssi=%d.%d epoch=%u heard=%u", h->id, rssi_i, rssi_f,
		    h->have_epoch ? h->epoch : 0u, h->heard);
	}
	if (!any) {
		say(fn, ctx, "no neighbours yet");
	}
}

void sf_node_report_route(const struct sf_node *n, sf_print_fn fn, void *ctx)
{
	unsigned int i;
	bool any = false;

	for (i = 0; i < SF_ROUTE_CAP; i++) {
		if (!n->route[i].used) {
			continue;
		}
		any = true;
		say(fn, ctx, "dst=%u next=%u", n->route[i].dst, n->route[i].next);
	}
	if (!any) {
		say(fn, ctx, "no routes (direct=%s)", n->cfg.direct_fallback ? "on" : "off");
	}
}
