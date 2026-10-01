/*
 * Copyright (c) 2026 Conexio Technologies, Inc
 *
 * SPDX-License-Identifier: Apache-2.0
 *
 * Zephyr side of the engine: Kconfig defaults, NVS, the lock, and the
 * modem receive queue. The radio thread is the only TX caller.
 */

#include "sf_port.h"

#include "sf_persist.h"
#include "sf_store.h"

#include <errno.h>
#include <stdio.h>
#include <string.h>

#include <zephyr/kernel.h>
#include <zephyr/logging/log.h>
#include <zephyr/sys/util.h>

LOG_MODULE_REGISTER(app, CONFIG_SF_LOG_LEVEL);

BUILD_ASSERT(CONFIG_CARRIER != 0, "Set CONFIG_CARRIER in overlay-us.conf or overlay-eu.conf");
BUILD_ASSERT(CONFIG_SF_SMALL_ALARM_SLOTS <= CONFIG_SF_SMALL_SLOTS, "alarm reserve exceeds small pool");
BUILD_ASSERT(CONFIG_SF_LARGE_SLOTS == 0 ||
		     CONFIG_SF_LARGE_ALARM_SLOTS <= CONFIG_SF_LARGE_SLOTS,
	     "alarm reserve exceeds large pool");
BUILD_ASSERT(CONFIG_SF_SMALL_PAYLOAD + SF_HDR_LEN <= CONFIG_SF_PHY_MTU, "small payload exceeds PHY MTU");
BUILD_ASSERT(CONFIG_SF_LARGE_SLOTS == 0 || CONFIG_SF_LARGE_PAYLOAD + SF_HDR_LEN <= CONFIG_SF_PHY_MTU,
	     "large payload exceeds PHY MTU");
BUILD_ASSERT(CONFIG_SF_PAYLOAD_LEN <= CONFIG_SF_SMALL_PAYLOAD || CONFIG_SF_LARGE_SLOTS > 0,
	     "default payload does not fit the pools");
BUILD_ASSERT(CONFIG_SF_LINK_MAX <= 8 && CONFIG_SF_ROUTE_MAX <= 8, "raise the caps in sf_types.h together");

static struct sf_node node;
static struct sf_slot small_slots[CONFIG_SF_SMALL_SLOTS];
static uint8_t small_mem[CONFIG_SF_SMALL_SLOTS][CONFIG_SF_SMALL_PAYLOAD];
#if CONFIG_SF_LARGE_SLOTS > 0
static struct sf_slot large_slots[CONFIG_SF_LARGE_SLOTS];
static uint8_t large_mem[CONFIG_SF_LARGE_SLOTS][CONFIG_SF_LARGE_PAYLOAD];
#endif

struct sf_rx_msg {
	uint16_t len;
	int16_t rssi_x2;
	uint8_t data[CONFIG_SF_PHY_MTU];
};

K_MSGQ_DEFINE(sf_rxq, sizeof(struct sf_rx_msg), CONFIG_SF_RX_QUEUE, 4);
K_MUTEX_DEFINE(sf_lock);
K_SEM_DEFINE(sf_run_sem, 0, 1);

static struct k_spinlock rx_lock;
static uint32_t rx_queue_drop;
static uint32_t rng_state;
static bool stable_noted;
static int64_t run_up_since;

static void emit_line(void *ctx, const char *line)
{
	ARG_UNUSED(ctx);
	LOG_INF("%s", line);
}

static uint32_t rng32(void)
{
	if (rng_state == 0) {
		rng_state = 0xA5A5u ^ (k_cycle_get_32() | 1u);
	}
	rng_state ^= rng_state << 13;
	rng_state ^= rng_state >> 17;
	rng_state ^= rng_state << 5;
	return rng_state;
}

static int64_t clock_us(void)
{
	return (int64_t)k_ticks_to_us_near64(k_uptime_ticks());
}

static void lock(void)
{
	k_mutex_lock(&sf_lock, K_FOREVER);
}

static void unlock(void)
{
	k_mutex_unlock(&sf_lock);
}

static void fill_kconfig(struct sf_cfg *c)
{
	memset(c, 0, sizeof(*c));
#if IS_ENABLED(CONFIG_SF_ROLE_RELAY)
	c->role = SF_ROLE_RELAY;
#elif IS_ENABLED(CONFIG_SF_ROLE_SINK)
	c->role = SF_ROLE_SINK;
#else
	c->role = SF_ROLE_SOURCE;
#endif
	c->dest_id = CONFIG_SF_DEST_ID;
	c->payload_len = CONFIG_SF_PAYLOAD_LEN;
	c->interval_ms = CONFIG_SF_INTERVAL_MS;
	c->count = CONFIG_SF_COUNT;
	c->hello_ms = CONFIG_SF_HELLO_MS;
	c->hello_mode = IS_ENABLED(CONFIG_SF_HELLO_TX_ON) ? SF_HELLO_ON : SF_HELLO_AUTO;
	c->ttl = CONFIG_SF_TTL;
	c->policy = IS_ENABLED(CONFIG_SF_POLICY_DROP_OLDEST) ? SF_POLICY_DROP_OLDEST : SF_POLICY_REJECT;
	c->assume_up = IS_ENABLED(CONFIG_SF_ASSUME_UP) ? 1u : 0u;
	c->direct_fallback = IS_ENABLED(CONFIG_SF_DIRECT_FALLBACK) ? 1u : 0u;
	c->gen_class = IS_ENABLED(CONFIG_SF_GEN_CLASS_ALARM) ? SF_CLASS_ALARM : SF_CLASS_TEL;
	c->dedup_on = IS_ENABLED(CONFIG_SF_DEDUPE) ? 1u : 0u;
	c->tx_power = CONFIG_TX_POWER;
	c->mcs = CONFIG_MCS;
	c->ack_timeout_ms = CONFIG_SF_ACK_TIMEOUT_MS;
	c->max_attempts = CONFIG_SF_MAX_ATTEMPTS;
	c->backoff_min_ms = CONFIG_SF_BACKOFF_MIN_MS;
	c->backoff_max_ms = CONFIG_SF_BACKOFF_MAX_MS;
	c->backoff_cap_ms = CONFIG_SF_BACKOFF_CAP_MS;
	c->nack_holdoff_ms = CONFIG_SF_NACK_HOLDOFF_MS;
	c->inter_tx_listen_ms = CONFIG_SF_INTER_TX_LISTEN_MS;
	c->rx_slice_ms = CONFIG_SF_RX_SLICE_MS;
	c->hello_dead_ms = CONFIG_SF_HELLO_DEAD_MS;
	c->t_probe_ms = CONFIG_SF_T_PROBE_MS;
	c->probe_fast_ms = CONFIG_SF_PROBE_FAST_MS;
	c->n_up = CONFIG_SF_N_UP;
	c->holddown_min_ms = CONFIG_SF_HOLDDOWN_MIN_MS;
	c->holddown_max_ms = CONFIG_SF_HOLDDOWN_MAX_MS;
	c->holddown_reset_ms = CONFIG_SF_HOLDDOWN_RESET_MS;
	c->telemetry_ttl_ms = CONFIG_SF_TELEMETRY_TTL_MS;
	c->stream_idle_ms = CONFIG_SF_STREAM_IDLE_MS;
	c->alarm_rate = CONFIG_SF_ALARM_RATE;
	c->alarm_burst = CONFIG_SF_ALARM_BURST;
	c->phy_mtu = CONFIG_SF_PHY_MTU;
}

static void init_store(struct sf_store *store)
{
	struct sf_pool small;
	struct sf_pool large;

	sf_pool_init(&small, small_slots, &small_mem[0][0], CONFIG_SF_SMALL_SLOTS,
		     CONFIG_SF_SMALL_PAYLOAD, CONFIG_SF_SMALL_ALARM_SLOTS);
#if CONFIG_SF_LARGE_SLOTS > 0
	sf_pool_init(&large, large_slots, &large_mem[0][0], CONFIG_SF_LARGE_SLOTS,
		     CONFIG_SF_LARGE_PAYLOAD, CONFIG_SF_LARGE_ALARM_SLOTS);
#else
	sf_pool_init(&large, NULL, NULL, 0, 0, 0);
#endif
	sf_store_init(store, small, large);
}

void sf_port_boot(uint16_t node_id)
{
	struct sf_cfg cfg;
	struct sf_store store;
	struct sf_route none;

	memset(&none, 0, sizeof(none));
	struct sf_persist_view view;
	const struct sf_route *routes = NULL;
	unsigned int nroutes = 0;
	uint16_t epoch = 1;
	uint32_t delay_ms = 0;

	if (node_id == 0 || node_id == SF_ID_BCAST) {
		LOG_WRN("device id %u is reserved, using 1", node_id);
		node_id = 1;
	}
	fill_kconfig(&cfg);
	cfg.node_id = node_id;
	memset(&view, 0, sizeof(view));
	if (IS_ENABLED(CONFIG_SF_PERSIST)) {
		(void)sf_persist_init();
		epoch = sf_persist_boot_epoch(&delay_ms);
		if (delay_ms > 0) {
			k_sleep(K_MSEC(delay_ms));
		}
		if (sf_persist_load(&view)) {
			uint16_t mtu = cfg.phy_mtu;

			cfg = view.cfg;
			cfg.node_id = node_id;
			cfg.phy_mtu = mtu;
			if (cfg.backoff_min_ms > cfg.backoff_max_ms) {
				cfg.backoff_max_ms = cfg.backoff_min_ms;
			}
			routes = view.route;
			nroutes = view.nroutes;
		}
	}
	init_store(&store);
	sf_node_init(&node, &cfg, routes != NULL ? routes : &none, nroutes, epoch, store);
	sf_node_set_emit(&node, emit_line, NULL);
	sf_node_set_rng(&node, rng32);
	sf_node_set_clock(&node, clock_us);
	LOG_INF("NR+ store-and-forward node=%u epoch=%u role=%s payload=%u", node_id, epoch,
		sf_role_name(cfg.role), cfg.payload_len);
	LOG_INF("carrier=%d net=%u ack_timeout=%u assume_up=%u direct=%u", CONFIG_CARRIER,
		CONFIG_NETWORK_ID, cfg.ack_timeout_ms, cfg.assume_up, cfg.direct_fallback);
}

uint16_t sf_port_node_id(void)
{
	return node.cfg.node_id;
}

bool sf_port_autostart_ok(void)
{
	if (!IS_ENABLED(CONFIG_SF_PERSIST) || !sf_persist_autostart()) {
		return false;
	}
	if (node.cfg.role == SF_ROLE_SOURCE && node.cfg.dest_id == 0) {
		LOG_WRN("autostart skipped: source has no dest");
		return false;
	}
	return true;
}

int sf_port_start(uint32_t count_or_zero)
{
	int rc;

	lock();
	rc = sf_node_start(&node, k_uptime_get(), count_or_zero);
	if (rc == 0) {
		run_up_since = k_uptime_get();
		stable_noted = false;
	}
	unlock();
	if (rc == 0) {
		k_sem_give(&sf_run_sem);
		LOG_INF("run started role=%s dest=%u", sf_role_name(node.cfg.role), node.cfg.dest_id);
	}
	return rc;
}

void sf_port_stop(const char *reason)
{
	lock();
	sf_node_stop(&node, k_uptime_get(), reason);
	unlock();
}

bool sf_port_running(void)
{
	bool running;

	lock();
	running = sf_node_running(&node);
	unlock();
	return running;
}

void sf_port_wait_until_started(void)
{
	k_sem_take(&sf_run_sem, K_FOREVER);
}

void sf_port_poll(struct sf_action *act)
{
	lock();
	sf_node_poll(&node, k_uptime_get(), act);
	unlock();
}

void sf_port_on_tx_done(bool ok, bool was_inflight)
{
	lock();
	sf_node_on_tx_done(&node, k_uptime_get(), ok, was_inflight);
	unlock();
}

void sf_port_on_pdc(const uint8_t *data, uint16_t len, int16_t rssi_x2)
{
	/* Static so the modem callback does not put a 249-byte frame on its stack.
	 * The queue copies the bytes out before we return to the modem.
	 */
	static struct sf_rx_msg rx_slot;
	k_spinlock_key_t key;

	if (data == NULL || len == 0) {
		return;
	}
	if (len > CONFIG_SF_PHY_MTU) {
		len = CONFIG_SF_PHY_MTU;
	}
	key = k_spin_lock(&rx_lock);
	rx_slot.len = len;
	rx_slot.rssi_x2 = rssi_x2;
	memcpy(rx_slot.data, data, len);
	if (k_msgq_put(&sf_rxq, &rx_slot, K_NO_WAIT) != 0) {
		rx_queue_drop++;
	}
	k_spin_unlock(&rx_lock, key);
}

void sf_port_drain_rx(void)
{
	struct sf_rx_msg msg;

	while (k_msgq_get(&sf_rxq, &msg, K_NO_WAIT) == 0) {
		lock();
		sf_node_on_rx(&node, k_uptime_get(), msg.data, msg.len, msg.rssi_x2);
		unlock();
	}
}

void sf_port_radio(uint8_t *power, uint8_t *mcs)
{
	lock();
	*power = node.cfg.tx_power;
	*mcs = node.cfg.mcs;
	unlock();
}

void sf_port_note_stable_if_due(void)
{
	if (stable_noted || !sf_node_running(&node)) {
		return;
	}
	if ((k_uptime_get() - run_up_since) < (int64_t)CONFIG_SF_BOOT_STABLE_S * 1000) {
		return;
	}
	stable_noted = true;
	if (IS_ENABLED(CONFIG_SF_PERSIST)) {
		sf_persist_mark_stable();
	}
}

int sf_port_set(const char *key, const char *value, char *err, size_t err_len)
{
	int rc;

	lock();
	rc = sf_node_set(&node, key, value, err, err_len);
	unlock();
	return rc;
}

int sf_port_route_set(uint16_t dst, uint16_t next, char *err, size_t err_len)
{
	int rc;

	lock();
	rc = sf_node_route_set(&node, dst, next, err, err_len);
	unlock();
	return rc;
}

int sf_port_route_del(uint16_t dst)
{
	int rc;

	lock();
	rc = sf_node_route_del(&node, dst);
	unlock();
	return rc;
}

int sf_port_alarm(void)
{
	int rc;

	lock();
	rc = sf_node_alarm(&node, k_uptime_get());
	unlock();
	return rc;
}

uint16_t sf_port_flush(const char *reason)
{
	uint16_t n;

	lock();
	n = sf_node_flush(&node, k_uptime_get(), reason);
	unlock();
	return n;
}

int sf_port_save(void)
{
	struct sf_cfg cfg;
	struct sf_route routes[SF_ROUTE_CAP];
	unsigned int nroutes;
	bool auto_on;

	if (!IS_ENABLED(CONFIG_SF_PERSIST)) {
		return -ENOTSUP;
	}
	memset(routes, 0, sizeof(routes));
	lock();
	cfg = *sf_node_cfg(&node);
	nroutes = sf_node_route_export(&node, routes, SF_ROUTE_CAP);
	auto_on = sf_persist_autostart();
	unlock();
	ARG_UNUSED(nroutes);
	return sf_persist_save(&cfg, routes, SF_ROUTE_CAP, auto_on);
}

int sf_port_load(char *err, size_t err_len)
{
	struct sf_persist_view view;
	struct sf_cfg cfg;

	if (!IS_ENABLED(CONFIG_SF_PERSIST)) {
		return -ENOTSUP;
	}
	lock();
	if (sf_node_running(&node)) {
		unlock();
		if (err != NULL && err_len > 0) {
			(void)snprintf(err, err_len, "stop the run before load");
		}
		return -EBUSY;
	}
	if (!sf_persist_load(&view)) {
		unlock();
		if (err != NULL && err_len > 0) {
			(void)snprintf(err, err_len, "no valid profile");
		}
		return -ENOENT;
	}
	cfg = view.cfg;
	cfg.node_id = node.cfg.node_id;
	cfg.phy_mtu = node.cfg.phy_mtu;
	if (cfg.backoff_min_ms > cfg.backoff_max_ms) {
		cfg.backoff_max_ms = cfg.backoff_min_ms;
	}
	sf_node_apply_cfg(&node, &cfg);
	sf_node_route_clear(&node);
	{
		unsigned int i;

		for (i = 0; i < view.nroutes; i++) {
			(void)sf_node_route_set(&node, view.route[i].dst, view.route[i].next, NULL, 0);
		}
	}
	(void)sf_node_flush(&node, k_uptime_get(), "load");
	unlock();
	return 0;
}

int sf_port_factory(char *err, size_t err_len)
{
	struct sf_cfg cfg;
	int rc;

	if (!IS_ENABLED(CONFIG_SF_PERSIST)) {
		return -ENOTSUP;
	}
	lock();
	if (sf_node_running(&node)) {
		unlock();
		if (err != NULL && err_len > 0) {
			(void)snprintf(err, err_len, "stop the run before factory");
		}
		return -EBUSY;
	}
	unlock();
	rc = sf_persist_clear();
	if (rc != 0) {
		return rc;
	}
	fill_kconfig(&cfg);
	lock();
	cfg.node_id = node.cfg.node_id;
	cfg.phy_mtu = CONFIG_SF_PHY_MTU;
	sf_node_apply_cfg(&node, &cfg);
	sf_node_route_clear(&node);
	(void)sf_node_flush(&node, k_uptime_get(), "factory");
	unlock();
	sf_persist_autostart_set(false);
	return 0;
}

void sf_port_autostart_set(bool on)
{
	if (IS_ENABLED(CONFIG_SF_PERSIST)) {
		sf_persist_autostart_set(on);
	}
}

bool sf_port_autostart_get(void)
{
	return IS_ENABLED(CONFIG_SF_PERSIST) && sf_persist_autostart();
}

bool sf_port_profile_present(void)
{
	return IS_ENABLED(CONFIG_SF_PERSIST) && sf_persist_present();
}

void sf_port_print_status(sf_print_fn fn, void *ctx)
{
	char line[96];

	lock();
	sf_node_status(&node, k_uptime_get(), fn, ctx);
	(void)snprintf(line, sizeof(line), "rx_queue_drop=%u autostart=%u profile=%u carrier=%d",
		       rx_queue_drop, sf_port_autostart_get() ? 1u : 0u,
		       sf_port_profile_present() ? 1u : 0u, CONFIG_CARRIER);
	fn(ctx, line);
	unlock();
}

void sf_port_print_cfg(sf_print_fn fn, void *ctx)
{
	lock();
	sf_node_dump_cfg(&node, fn, ctx);
	unlock();
}

void sf_port_print_sf(sf_print_fn fn, void *ctx)
{
	lock();
	sf_node_report_sf(&node, fn, ctx);
	unlock();
}

void sf_port_print_link(sf_print_fn fn, void *ctx)
{
	lock();
	sf_node_report_link(&node, fn, ctx);
	unlock();
}

void sf_port_print_neigh(sf_print_fn fn, void *ctx)
{
	lock();
	sf_node_report_neigh(&node, fn, ctx);
	unlock();
}

void sf_port_print_route(sf_print_fn fn, void *ctx)
{
	lock();
	sf_node_report_route(&node, fn, ctx);
	unlock();
}
