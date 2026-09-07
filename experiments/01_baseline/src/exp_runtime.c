/*
 * Copyright (c) 2026 Conexio Technologies, Inc
 *
 * SPDX-License-Identifier: Apache-2.0
 */

#include "exp_runtime.h"

#include <limits.h>
#include <zephyr/kernel.h>
#include <zephyr/sys/printk.h>
#include <zephyr/sys/util.h>

static struct exp_runtime rt;
static uint16_t g_device_id;
static struct k_mutex rt_lock;
static struct k_sem start_sem;

static void reset_stats_locked(void)
{
	rt.sequence = 0;
	rt.tx_sent = 0;
	rt.rx_ok = 0;
	rt.rx_fail = 0;
	rt.rx_gaps = 0;
	rt.last_from = 0;
	rt.rssi_min_x2 = INT32_MAX;
	rt.rssi_max_x2 = INT32_MIN;
	rt.rssi_sum_x2 = 0;
	rt.rssi_n = 0;
}

void exp_runtime_init(void)
{
	k_mutex_init(&rt_lock);
	k_sem_init(&start_sem, 0, 1);

	rt.running = false;
	rt.tx_interval_ms = CONFIG_TX_INTERVAL_MS;
	rt.tx_count = CONFIG_TX_TRANSMISSIONS;
	rt.tx_power = (uint8_t)CONFIG_TX_POWER;
	rt.mcs = (uint8_t)CONFIG_MCS;
	rt.packet_size = (uint16_t)CONFIG_EXPERIMENT_PACKET_SIZE;
	rt.message_type = (uint8_t)CONFIG_EXPERIMENT_MESSAGE_TYPE;
	reset_stats_locked();
}

struct exp_runtime *exp_runtime_get(void)
{
	return &rt;
}

void exp_runtime_lock(void)
{
	k_mutex_lock(&rt_lock, K_FOREVER);
}

void exp_runtime_unlock(void)
{
	k_mutex_unlock(&rt_lock);
}

void exp_set_device_id(uint16_t id)
{
	g_device_id = id;
}

uint16_t exp_device_id(void)
{
	return g_device_id;
}

const char *exp_mode_str(void)
{
	if (IS_ENABLED(CONFIG_EXPERIMENT_TEST_MODE_TX_ONLY)) {
		return "tx_only";
	}
	if (IS_ENABLED(CONFIG_EXPERIMENT_TEST_MODE_RX_ONLY)) {
		return "rx_only";
	}
	return "tx_rx";
}

void exp_runtime_reset_stats(void)
{
	k_mutex_lock(&rt_lock, K_FOREVER);
	reset_stats_locked();
	k_mutex_unlock(&rt_lock);
}

void exp_request_start(uint32_t count_override)
{
	k_mutex_lock(&rt_lock, K_FOREVER);
	if (count_override != UINT32_MAX) {
		rt.tx_count = count_override;
	}
	reset_stats_locked();
	rt.running = true;
	k_mutex_unlock(&rt_lock);
	k_sem_give(&start_sem);
}

void exp_request_stop(void)
{
	k_mutex_lock(&rt_lock, K_FOREVER);
	rt.running = false;
	k_mutex_unlock(&rt_lock);
	k_sem_give(&start_sem);
}

bool exp_is_running(void)
{
	bool r;

	k_mutex_lock(&rt_lock, K_FOREVER);
	r = rt.running;
	k_mutex_unlock(&rt_lock);
	return r;
}

void exp_wait_until_start(void)
{
	while (!exp_is_running()) {
		k_sem_take(&start_sem, K_FOREVER);
	}
}

void exp_print_status(void)
{
	struct exp_runtime snap;

	k_mutex_lock(&rt_lock, K_FOREVER);
	snap = rt;
	k_mutex_unlock(&rt_lock);

	printk("exp status:\n");
	printk("  mode=%s running=%d device_id=%u\n", exp_mode_str(), snap.running, g_device_id);
	printk("  carrier=%d net=0x%x\n", CONFIG_CARRIER, CONFIG_NETWORK_ID);
	printk("  interval_ms=%u count=%u (0=forever)\n", snap.tx_interval_ms, snap.tx_count);
	printk("  power=%u mcs=%u size=%u type=%u\n", snap.tx_power, snap.mcs, snap.packet_size,
	       snap.message_type);
	printk("  seq_next=%u tx_sent=%u rx_ok=%u rx_fail=%u gaps=%u\n", snap.sequence, snap.tx_sent,
	       snap.rx_ok, snap.rx_fail, snap.rx_gaps);
}

void exp_print_summary(const char *reason)
{
	struct exp_runtime snap;
	int avg_i = 0;
	int avg_f = 0;
	int min_i = 0;
	int min_f = 0;
	int max_i = 0;
	int max_f = 0;

	k_mutex_lock(&rt_lock, K_FOREVER);
	snap = rt;
	k_mutex_unlock(&rt_lock);

	if (snap.rssi_n > 0) {
		int32_t avg_x2 = (int32_t)(snap.rssi_sum_x2 / (int64_t)snap.rssi_n);

		avg_i = avg_x2 / 2;
		avg_f = (avg_x2 & 1) * 5;
		min_i = snap.rssi_min_x2 / 2;
		min_f = (snap.rssi_min_x2 & 1) * 5;
		max_i = snap.rssi_max_x2 / 2;
		max_f = (snap.rssi_max_x2 & 1) * 5;
	}

	if (IS_ENABLED(CONFIG_EXPERIMENT_TEST_MODE_RX_ONLY)) {
		printk("SUMMARY: role=rx reason=%s device_id=%u from=%u ok=%u fail=%u gaps=%u "
		       "rssi_min=%d.%d rssi_avg=%d.%d rssi_max=%d.%d\n",
		       reason, g_device_id, snap.last_from, snap.rx_ok, snap.rx_fail, snap.rx_gaps,
		       min_i, min_f, avg_i, avg_f, max_i, max_f);
	} else if (IS_ENABLED(CONFIG_EXPERIMENT_TEST_MODE_TX_ONLY)) {
		printk("SUMMARY: role=tx reason=%s device_id=%u sent=%u count_cfg=%u\n", reason,
		       g_device_id, snap.tx_sent, snap.tx_count);
	} else {
		printk("SUMMARY: role=tx_rx reason=%s device_id=%u sent=%u rx_ok=%u rx_fail=%u "
		       "gaps=%u\n",
		       reason, g_device_id, snap.tx_sent, snap.rx_ok, snap.rx_fail, snap.rx_gaps);
	}
}
