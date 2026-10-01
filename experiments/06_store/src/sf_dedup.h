/*
 * Copyright (c) 2026 Conexio Technologies, Inc
 *
 * SPDX-License-Identifier: Apache-2.0
 */

#ifndef SF_DEDUP_H_
#define SF_DEDUP_H_

#include "sf_types.h"

enum sf_dedup_result {
	SF_DEDUP_NEW = 0,
	SF_DEDUP_DUP = 1,
	SF_DEDUP_STALE_EPOCH = 2,
};

struct sf_stream {
	bool used;
	uint16_t src;
	uint8_t class_;
	uint16_t epoch;
	uint16_t last_seq;
	int64_t last_ms;
};

struct sf_dedup {
	struct sf_stream item[SF_STREAM_CAP];
	uint32_t evictions;
	uint32_t gaps;
	uint32_t stale_epoch;
	uint32_t dups;
	uint8_t src_reset;
	uint16_t src_reset_id;
	uint16_t src_reset_old;
	uint16_t src_reset_new;
};

struct sf_dedup_out {
	enum sf_dedup_result result;
	uint16_t gap;
	bool src_reset;
	uint16_t old_epoch;
	uint16_t new_epoch;
};

void sf_dedup_init(struct sf_dedup *d);
/* Commit is false for a lookup that must not move last_seq (store failure). */
void sf_dedup_check(struct sf_dedup *d, uint16_t src, uint8_t class_, uint16_t epoch,
		    uint16_t seq, int64_t now, uint32_t idle_ms, bool enabled,
		    struct sf_dedup_out *out);
void sf_dedup_commit(struct sf_dedup *d, uint16_t src, uint8_t class_, uint16_t epoch,
		     uint16_t seq, int64_t now);
void sf_dedup_sweep(struct sf_dedup *d, int64_t now, uint32_t idle_ms);

#endif /* SF_DEDUP_H_ */
