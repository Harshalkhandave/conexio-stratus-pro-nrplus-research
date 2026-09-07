/*
 * Copyright (c) 2026 Conexio Technologies, Inc
 *
 * SPDX-License-Identifier: Apache-2.0
 */

#ifndef EXP_RUNTIME_H_
#define EXP_RUNTIME_H_

#include <stdbool.h>
#include <stdint.h>

struct exp_runtime {
	bool running;
	uint32_t tx_interval_ms;
	uint32_t tx_count; /* 0 = forever */
	uint8_t tx_power;
	uint8_t mcs;
	uint16_t packet_size;
	uint8_t message_type;

	uint32_t sequence;
	uint32_t tx_sent;
	uint32_t rx_ok;
	uint32_t rx_fail;
	uint32_t rx_gaps;
	uint16_t last_from;
	int32_t rssi_min_x2;
	int32_t rssi_max_x2;
	int64_t rssi_sum_x2;
	uint32_t rssi_n;
};

void exp_runtime_init(void);
struct exp_runtime *exp_runtime_get(void);
void exp_runtime_lock(void);
void exp_runtime_unlock(void);

void exp_runtime_reset_stats(void);

/** count_override: UINT32_MAX = keep current count setting */
void exp_request_start(uint32_t count_override);
void exp_request_stop(void);
bool exp_is_running(void);
void exp_wait_until_start(void);

void exp_print_status(void);
void exp_print_summary(const char *reason);

const char *exp_mode_str(void);
uint16_t exp_device_id(void);
void exp_set_device_id(uint16_t id);

#endif /* EXP_RUNTIME_H_ */
