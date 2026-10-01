/*
 * Copyright (c) 2026 Conexio Technologies, Inc
 *
 * SPDX-License-Identifier: Apache-2.0
 */

#include "sf_dedup.h"

void sf_dedup_init(struct sf_dedup *d)
{
	unsigned int i;

	for (i = 0; i < SF_STREAM_CAP; i++) {
		d->item[i].used = false;
	}
	d->evictions = 0;
	d->gaps = 0;
	d->stale_epoch = 0;
	d->dups = 0;
	d->src_reset = 0;
}

static struct sf_stream *find_stream(struct sf_dedup *d, uint16_t src, uint8_t class_)
{
	unsigned int i;

	for (i = 0; i < SF_STREAM_CAP; i++) {
		if (d->item[i].used && d->item[i].src == src && d->item[i].class_ == class_) {
			return &d->item[i];
		}
	}
	return NULL;
}

static struct sf_stream *alloc_stream(struct sf_dedup *d, int64_t now, uint32_t idle_ms)
{
	unsigned int i;
	struct sf_stream *oldest = NULL;

	for (i = 0; i < SF_STREAM_CAP; i++) {
		if (!d->item[i].used) {
			return &d->item[i];
		}
		if (idle_ms > 0 && (now - d->item[i].last_ms) >= (int64_t)idle_ms) {
			d->item[i].used = false;
			d->evictions++;
			return &d->item[i];
		}
		if (oldest == NULL || d->item[i].last_ms < oldest->last_ms) {
			oldest = &d->item[i];
		}
	}
	if (oldest != NULL) {
		oldest->used = false;
		d->evictions++;
		return oldest;
	}
	return NULL;
}

void sf_dedup_check(struct sf_dedup *d, uint16_t src, uint8_t class_, uint16_t epoch,
		    uint16_t seq, int64_t now, uint32_t idle_ms, bool enabled,
		    struct sf_dedup_out *out)
{
	struct sf_stream *s;

	out->result = SF_DEDUP_NEW;
	out->gap = 0;
	out->src_reset = false;
	out->old_epoch = 0;
	out->new_epoch = epoch;
	if (!enabled) {
		return;
	}

	s = find_stream(d, src, class_);
	if (s == NULL) {
		return;
	}
	if (idle_ms > 0 && (now - s->last_ms) >= (int64_t)idle_ms) {
		s->used = false;
		d->evictions++;
		return;
	}

	if (epoch != s->epoch) {
		if (sf_delta16(epoch, s->epoch) > 0) {
			out->src_reset = true;
			out->old_epoch = s->epoch;
			out->new_epoch = epoch;
			out->result = SF_DEDUP_NEW;
			return;
		}
		out->result = SF_DEDUP_STALE_EPOCH;
		d->stale_epoch++;
		return;
	}

	{
		int16_t delta = sf_delta16(seq, s->last_seq);

		if (delta <= 0) {
			out->result = SF_DEDUP_DUP;
			d->dups++;
			s->last_ms = now;
			return;
		}
		if (delta > 1) {
			out->gap = (uint16_t)(delta - 1);
		}
		out->result = SF_DEDUP_NEW;
	}
}

void sf_dedup_commit(struct sf_dedup *d, uint16_t src, uint8_t class_, uint16_t epoch,
		     uint16_t seq, int64_t now)
{
	struct sf_stream *s = find_stream(d, src, class_);

	if (s == NULL) {
		s = alloc_stream(d, now, 0);
		if (s == NULL) {
			return;
		}
		s->src = src;
		s->class_ = class_;
	} else if (epoch == s->epoch) {
		int16_t delta = sf_delta16(seq, s->last_seq);

		if (delta > 1) {
			d->gaps += (uint32_t)(delta - 1);
		}
	}
	s->used = true;
	s->epoch = epoch;
	s->last_seq = seq;
	s->last_ms = now;
}

void sf_dedup_sweep(struct sf_dedup *d, int64_t now, uint32_t idle_ms)
{
	unsigned int i;

	if (idle_ms == 0) {
		return;
	}
	for (i = 0; i < SF_STREAM_CAP; i++) {
		if (d->item[i].used && (now - d->item[i].last_ms) >= (int64_t)idle_ms) {
			d->item[i].used = false;
			d->evictions++;
		}
	}
}
