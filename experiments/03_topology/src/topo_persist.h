/*
 * Copyright (c) 2026 Conexio Technologies, Inc
 *
 * SPDX-License-Identifier: Apache-2.0
 */

#ifndef TOPO_PERSIST_H_
#define TOPO_PERSIST_H_

#include <stdbool.h>
#include <stdint.h>

/**
 * Load saved profile from flash into runtime (after topo_runtime_init defaults).
 * @return true if a valid profile was loaded
 */
bool topo_persist_load(void);

/** Save current runtime settings + autostart flag to flash. @return 0 on success */
int topo_persist_save(void);

/** Erase saved profile (factory). @return 0 on success */
int topo_persist_clear(void);

bool topo_persist_present(void);
bool topo_autostart_get(void);
void topo_autostart_set(bool on);

#endif /* TOPO_PERSIST_H_ */
