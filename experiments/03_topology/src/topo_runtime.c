/*
 * Copyright (c) 2026 Conexio Technologies, Inc
 *
 * SPDX-License-Identifier: Apache-2.0
 */

#include "topo_runtime.h"

#include <limits.h>
#include <string.h>
#include <zephyr/kernel.h>
#include <zephyr/sys/printk.h>
#include <zephyr/sys/util.h>

#if IS_ENABLED(CONFIG_TOPO_PERSIST)
#include "topo_persist.h"
#endif

static struct topo_runtime rt;
static uint16_t g_device_id;
static struct k_mutex rt_lock;
static struct k_sem start_sem;

K_MSGQ_DEFINE(fwd_q, sizeof(struct topo_fwd_item), TOPO_FWD_QUEUE_MAX, 4);

static enum topo_role default_role(void)
{
	if (IS_ENABLED(CONFIG_TOPO_ROLE_RELAY)) {
		return TOPO_ROLE_RELAY_V;
	}
	if (IS_ENABLED(CONFIG_TOPO_ROLE_SINK)) {
		return TOPO_ROLE_SINK_V;
	}
	return TOPO_ROLE_SOURCE_V;
}

static void reset_stats_locked(void)
{
	rt.sequence = 0;
	rt.data_sent = 0;
	rt.hello_sent = 0;
	rt.fwd_sent = 0;
	rt.rx_ok = 0;
	rt.rx_fail = 0;
	rt.deliver_ok = 0;
	rt.fwd_drop_dup = 0;
	rt.fwd_drop_ttl = 0;
	rt.fwd_enqueue = 0;
	rt.fwd_drop_full = 0;
	rt.last_from = 0;
	rt.rssi_min_x2 = INT32_MAX;
	rt.rssi_max_x2 = INT32_MIN;
	rt.rssi_sum_x2 = 0;
	rt.rssi_n = 0;
	rt.q_depth_peak = 0;
	memset(rt.seen, 0, sizeof(rt.seen));
	/* Keep neighbors across start so Exp1 map persists; clear on demand later if needed. */
}

void topo_runtime_init(void)
{
	k_mutex_init(&rt_lock);
	k_sem_init(&start_sem, 0, 1);
	topo_runtime_restore_defaults();
}

void topo_runtime_restore_defaults(void)
{
	k_mutex_lock(&rt_lock, K_FOREVER);
	rt.running = false;
	rt.role = default_role();
	rt.dest_id = (uint16_t)CONFIG_TOPO_DEST_ID;
	rt.max_hops = (uint8_t)CONFIG_TOPO_MAX_HOPS;
	rt.tx_interval_ms = CONFIG_TX_INTERVAL_MS;
	rt.hello_interval_ms = CONFIG_HELLO_INTERVAL_MS;
	rt.tx_count = CONFIG_TX_TRANSMISSIONS;
	rt.tx_power = (uint8_t)CONFIG_TX_POWER;
	rt.mcs = (uint8_t)CONFIG_MCS;
	rt.packet_size = (uint16_t)CONFIG_TOPO_PACKET_SIZE;
	rt.dedup = IS_ENABLED(CONFIG_TOPO_DEDUP);
	rt.source_rx = true;
	rt.rx_window_ms = 2000;
	rt.fwd_mode = TOPO_FWD_CUT_THROUGH;
	rt.fwd_batch_ms = 2000;
	memset(rt.neigh, 0, sizeof(rt.neigh));
	reset_stats_locked();
	k_mutex_unlock(&rt_lock);
}

struct topo_runtime *topo_runtime_get(void)
{
	return &rt;
}

void topo_runtime_lock(void)
{
	k_mutex_lock(&rt_lock, K_FOREVER);
}

void topo_runtime_unlock(void)
{
	k_mutex_unlock(&rt_lock);
}

void topo_set_device_id(uint16_t id)
{
	g_device_id = id;
}

uint16_t topo_device_id(void)
{
	return g_device_id;
}

const char *topo_role_str(enum topo_role role)
{
	switch (role) {
	case TOPO_ROLE_SOURCE_V:
		return "source";
	case TOPO_ROLE_RELAY_V:
		return "relay";
	case TOPO_ROLE_SINK_V:
		return "sink";
	default:
		return "unknown";
	}
}

bool topo_role_from_str(const char *s, enum topo_role *out)
{
	if (strcmp(s, "source") == 0 || strcmp(s, "src") == 0) {
		*out = TOPO_ROLE_SOURCE_V;
		return true;
	}
	if (strcmp(s, "relay") == 0 || strcmp(s, "router") == 0) {
		*out = TOPO_ROLE_RELAY_V;
		return true;
	}
	if (strcmp(s, "sink") == 0 || strcmp(s, "gateway") == 0) {
		*out = TOPO_ROLE_SINK_V;
		return true;
	}
	return false;
}

const char *topo_fwd_mode_str(enum topo_fwd_mode mode)
{
	switch (mode) {
	case TOPO_FWD_CUT_THROUGH:
		return "cut_through";
	case TOPO_FWD_BATCH:
		return "batch";
	default:
		return "unknown";
	}
}

bool topo_fwd_mode_from_str(const char *s, enum topo_fwd_mode *out)
{
	if (!s || !out) {
		return false;
	}
	if (strcmp(s, "cut_through") == 0 || strcmp(s, "immediate") == 0) {
		*out = TOPO_FWD_CUT_THROUGH;
		return true;
	}
	if (strcmp(s, "batch") == 0) {
		*out = TOPO_FWD_BATCH;
		return true;
	}
	return false;
}

void topo_runtime_reset_stats(void)
{
	k_mutex_lock(&rt_lock, K_FOREVER);
	reset_stats_locked();
	k_mutex_unlock(&rt_lock);
}

void topo_request_start(uint32_t count_override)
{
	struct topo_fwd_item discard;

	k_mutex_lock(&rt_lock, K_FOREVER);
	if (count_override != UINT32_MAX) {
		rt.tx_count = count_override;
	}
	reset_stats_locked();
	rt.running = true;
	k_mutex_unlock(&rt_lock);

	while (k_msgq_get(&fwd_q, &discard, K_NO_WAIT) == 0) {
		/* drain stale forwards */
	}
	k_sem_give(&start_sem);
}

void topo_request_stop(void)
{
	k_mutex_lock(&rt_lock, K_FOREVER);
	rt.running = false;
	k_mutex_unlock(&rt_lock);
	k_sem_give(&start_sem);
}

bool topo_is_running(void)
{
	bool r;

	k_mutex_lock(&rt_lock, K_FOREVER);
	r = rt.running;
	k_mutex_unlock(&rt_lock);
	return r;
}

void topo_wait_until_start(void)
{
	while (!topo_is_running()) {
		k_sem_take(&start_sem, K_FOREVER);
	}
}

void topo_neigh_note(uint16_t id, int32_t rssi_x2, uint8_t msg_type)
{
	struct topo_neighbor *slot = NULL;
	struct topo_neighbor *free_slot = NULL;
	uint32_t oldest_ms = UINT32_MAX;
	struct topo_neighbor *oldest = NULL;
	uint32_t now = (uint32_t)k_uptime_get();

	if (id == 0 || id == g_device_id) {
		return;
	}

	k_mutex_lock(&rt_lock, K_FOREVER);

	for (int i = 0; i < TOPO_NEIGH_MAX; i++) {
		if (rt.neigh[i].used && rt.neigh[i].id == id) {
			slot = &rt.neigh[i];
			break;
		}
		if (!rt.neigh[i].used && free_slot == NULL) {
			free_slot = &rt.neigh[i];
		}
		if (rt.neigh[i].used && rt.neigh[i].last_seen_ms < oldest_ms) {
			oldest_ms = rt.neigh[i].last_seen_ms;
			oldest = &rt.neigh[i];
		}
	}

	if (slot == NULL) {
		slot = free_slot != NULL ? free_slot : oldest;
		if (slot == NULL) {
			k_mutex_unlock(&rt_lock);
			return;
		}
		slot->used = true;
		slot->id = id;
		slot->hello_n = 0;
		slot->data_n = 0;
	}

	slot->last_rssi_x2 = rssi_x2;
	slot->last_seen_ms = now;
	if (msg_type == TOPO_MSG_HELLO) {
		slot->hello_n++;
	} else if (msg_type == TOPO_MSG_DATA) {
		slot->data_n++;
	}

	k_mutex_unlock(&rt_lock);
}

bool topo_seen_is_dup(uint16_t src, uint32_t sequence)
{
	struct topo_seen *slot = NULL;
	struct topo_seen *free_slot = NULL;

	k_mutex_lock(&rt_lock, K_FOREVER);

	/* When dedup is disabled, always treat as new. */
	if (!rt.dedup) {
		k_mutex_unlock(&rt_lock);
		return false;
	}

	for (int i = 0; i < TOPO_SEEN_MAX; i++) {
		if (rt.seen[i].used && rt.seen[i].src == src && rt.seen[i].sequence == sequence) {
			rt.fwd_drop_dup++;
			k_mutex_unlock(&rt_lock);
			return true;
		}
		if (!rt.seen[i].used && free_slot == NULL) {
			free_slot = &rt.seen[i];
		}
		if (rt.seen[i].used && slot == NULL) {
			/* overwrite candidate if table full */
			slot = &rt.seen[i];
		}
	}

	if (free_slot != NULL) {
		free_slot->used = true;
		free_slot->src = src;
		free_slot->sequence = sequence;
	} else if (slot != NULL) {
		slot->src = src;
		slot->sequence = sequence;
	}

	k_mutex_unlock(&rt_lock);
	return false;
}

bool topo_fwd_enqueue(const struct topo_packet *pkt)
{
	struct topo_fwd_item item = { .pkt = *pkt };
	int err;

	err = k_msgq_put(&fwd_q, &item, K_NO_WAIT);
	k_mutex_lock(&rt_lock, K_FOREVER);
	if (err) {
		rt.fwd_drop_full++;
		k_mutex_unlock(&rt_lock);
		return false;
	}
	rt.fwd_enqueue++;
	uint16_t depth = (uint16_t)k_msgq_num_used_get(&fwd_q);
	if (depth > rt.q_depth_peak) {
		rt.q_depth_peak = depth;
	}
	k_mutex_unlock(&rt_lock);
	return true;
}

bool topo_fwd_dequeue(struct topo_fwd_item *out)
{
	return k_msgq_get(&fwd_q, out, K_NO_WAIT) == 0;
}

void topo_print_status(void)
{
	struct topo_runtime snap;

	k_mutex_lock(&rt_lock, K_FOREVER);
	snap = rt;
	k_mutex_unlock(&rt_lock);

	printk("exp status:\n");
	printk("  role=%s running=%d device_id=%u dest_id=%u max_hops=%u\n",
	       topo_role_str(snap.role), snap.running, g_device_id, snap.dest_id, snap.max_hops);
	printk("  carrier=%d net=0x%x\n", CONFIG_CARRIER, CONFIG_NETWORK_ID);
	printk("  interval_ms=%u hello_ms=%u count=%u (0=forever)\n", snap.tx_interval_ms,
	       snap.hello_interval_ms, snap.tx_count);
	printk("  power=%u mcs=%u size=%u dedup=%d source_rx=%d rx_win=%u fwd=%s\n", snap.tx_power, snap.mcs, snap.packet_size,
	       snap.dedup ? 1 : 0, snap.source_rx ? 1 : 0, snap.rx_window_ms,
	       topo_fwd_mode_str(snap.fwd_mode));
#if IS_ENABLED(CONFIG_TOPO_PERSIST)
	printk("  autostart=%d persist=%d\n", topo_autostart_get() ? 1 : 0,
	       topo_persist_present() ? 1 : 0);
#endif
	printk("  seq_next=%u data_sent=%u hello_sent=%u fwd_sent=%u\n", snap.sequence,
	       snap.data_sent, snap.hello_sent, snap.fwd_sent);
	printk("  rx_ok=%u rx_fail=%u deliver=%u fwd_dup=%u fwd_ttl=%u fwd_qfull=%u q_peak=%u\n",
	       snap.rx_ok, snap.rx_fail, snap.deliver_ok, snap.fwd_drop_dup, snap.fwd_drop_ttl,
	       snap.fwd_drop_full, snap.q_depth_peak);
}

bool topo_should_autostart(void)
{
	/* Kconfig overlay can force auto-start without NVS. */
	if (!IS_ENABLED(CONFIG_TOPO_WAIT_FOR_START)) {
		return true;
	}
#if IS_ENABLED(CONFIG_TOPO_PERSIST)
	return topo_autostart_get();
#else
	return false;
#endif
}

void topo_print_neighbors(void)
{
	struct topo_neighbor snap[TOPO_NEIGH_MAX];
	int n = 0;

	k_mutex_lock(&rt_lock, K_FOREVER);
	memcpy(snap, rt.neigh, sizeof(snap));
	k_mutex_unlock(&rt_lock);

	printk("exp neigh:\n");
	for (int i = 0; i < TOPO_NEIGH_MAX; i++) {
		int rssi_i;
		int rssi_f;

		if (!snap[i].used) {
			continue;
		}
		n++;
		rssi_i = snap[i].last_rssi_x2 / 2;
		rssi_f = (snap[i].last_rssi_x2 & 1) * 5;
		printk("  id=%u rssi=%d.%d last_ms=%u hello=%u data=%u\n", snap[i].id, rssi_i,
		       rssi_f, snap[i].last_seen_ms, snap[i].hello_n, snap[i].data_n);
	}
	if (n == 0) {
		printk("  (none)\n");
	}
}

void topo_print_summary(const char *reason)
{
	struct topo_runtime snap;
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

	printk("SUMMARY: role=%s reason=%s device_id=%u dest=%u data_sent=%u hello_sent=%u "
	       "fwd_sent=%u rx_ok=%u rx_fail=%u deliver=%u q_peak=%u "
	       "rssi_min=%d.%d rssi_avg=%d.%d rssi_max=%d.%d\n",
	       topo_role_str(snap.role), reason, g_device_id, snap.dest_id, snap.data_sent,
	       snap.hello_sent, snap.fwd_sent, snap.rx_ok, snap.rx_fail, snap.deliver_ok, snap.q_depth_peak,
	       min_i, min_f, avg_i, avg_f, max_i, max_f);
}
