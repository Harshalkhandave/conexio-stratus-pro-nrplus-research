/*
 * Copyright (c) 2026 Conexio Technologies, Inc
 *
 * SPDX-License-Identifier: Apache-2.0
 */

#ifndef SF_PERSIST_H_
#define SF_PERSIST_H_

#include "sf_types.h"

#include <stdbool.h>
#include <stdint.h>

struct sf_persist_view {
	struct sf_cfg cfg;
	struct sf_route route[SF_ROUTE_CAP];
	unsigned int nroutes;
	bool autostart;
	bool present;
};

int sf_persist_init(void);
bool sf_persist_load(struct sf_persist_view *out);
int sf_persist_save(const struct sf_cfg *cfg, const struct sf_route *routes, unsigned int nroutes,
		    bool autostart);
int sf_persist_clear(void);
bool sf_persist_present(void);

uint16_t sf_persist_boot_epoch(uint32_t *delay_ms);
void sf_persist_mark_stable(void);

bool sf_persist_autostart(void);
void sf_persist_autostart_set(bool on);

#endif /* SF_PERSIST_H_ */
