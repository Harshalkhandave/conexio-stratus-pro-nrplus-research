/*
 * Copyright (c) 2026 Conexio Technologies, Inc
 *
 * SPDX-License-Identifier: Apache-2.0
 */

#ifndef SF_PORT_H_
#define SF_PORT_H_

#include "sf_node.h"

#include <stdbool.h>
#include <stdint.h>

void sf_port_boot(uint16_t node_id);
uint16_t sf_port_node_id(void);
bool sf_port_autostart_ok(void);

int sf_port_start(uint32_t count_or_zero);
void sf_port_stop(const char *reason);
bool sf_port_running(void);
void sf_port_wait_until_started(void);

void sf_port_poll(struct sf_action *act);
void sf_port_on_tx_done(bool ok, bool was_inflight);
void sf_port_on_pdc(const uint8_t *data, uint16_t len, int16_t rssi_x2);
void sf_port_drain_rx(void);
void sf_port_radio(uint8_t *power, uint8_t *mcs);
void sf_port_note_stable_if_due(void);

int sf_port_set(const char *key, const char *value, char *err, size_t err_len);
int sf_port_route_set(uint16_t dst, uint16_t next, char *err, size_t err_len);
int sf_port_route_del(uint16_t dst);
int sf_port_alarm(void);
uint16_t sf_port_flush(const char *reason);
int sf_port_save(void);
int sf_port_load(char *err, size_t err_len);
int sf_port_factory(char *err, size_t err_len);
void sf_port_autostart_set(bool on);
bool sf_port_autostart_get(void);
bool sf_port_profile_present(void);

void sf_port_print_status(sf_print_fn fn, void *ctx);
void sf_port_print_cfg(sf_print_fn fn, void *ctx);
void sf_port_print_sf(sf_print_fn fn, void *ctx);
void sf_port_print_link(sf_print_fn fn, void *ctx);
void sf_port_print_neigh(sf_print_fn fn, void *ctx);
void sf_port_print_route(sf_print_fn fn, void *ctx);

#endif /* SF_PORT_H_ */
