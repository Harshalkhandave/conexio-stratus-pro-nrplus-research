/*
 * Copyright (c) 2026 Conexio Technologies, Inc
 *
 * SPDX-License-Identifier: Apache-2.0
 *
 * Two settings keys share the NVS partition:
 *   sf/cfg    profile (exp save / load / factory)
 *   sf/epoch  boot epoch and boot-loop counter (factory does not delete this)
 */

#include "sf_persist.h"

#include <errno.h>
#include <string.h>

#include <zephyr/kernel.h>
#include <zephyr/logging/log.h>
#include <zephyr/settings/settings.h>
#include <zephyr/sys/util.h>

LOG_MODULE_REGISTER(sf_persist, CONFIG_SF_LOG_LEVEL);

#if IS_ENABLED(CONFIG_SF_PERSIST)

#define SF_CFG_MAGIC   0x53463631u /* 'SF61' */
#define SF_EPOCH_MAGIC 0x53465045u /* 'SFPE' */
#define SF_VERSION     1u

struct sf_persist_route {
	uint16_t dst;
	uint16_t next;
} __packed;

struct sf_persist_blob {
	uint32_t magic;
	uint16_t version;
	uint16_t nbytes;
	uint8_t autostart;
	uint8_t role;
	uint8_t policy;
	uint8_t assume_up;
	uint8_t direct;
	uint8_t gen_class;
	uint8_t hello_mode;
	uint8_t dedup_on;
	uint8_t tx_power;
	uint8_t mcs;
	uint8_t ttl;
	uint8_t max_attempts;
	uint8_t n_up;
	uint8_t alarm_burst;
	uint16_t dest_id;
	uint16_t payload_len;
	uint32_t interval_ms;
	uint32_t hello_ms;
	uint32_t count;
	uint32_t ack_timeout_ms;
	uint32_t backoff_min_ms;
	uint32_t backoff_max_ms;
	uint32_t backoff_cap_ms;
	uint32_t nack_holdoff_ms;
	uint32_t gap_ms;
	uint32_t rx_slice_ms;
	uint32_t hello_dead_ms;
	uint32_t t_probe_ms;
	uint32_t probe_fast_ms;
	uint32_t hold_min_ms;
	uint32_t hold_max_ms;
	uint32_t hold_reset_ms;
	uint32_t tel_ttl_ms;
	uint32_t stream_idle_ms;
	uint32_t alarm_rate;
	uint8_t nroutes;
	uint8_t pad[3];
	struct sf_persist_route route[CONFIG_SF_ROUTE_MAX];
} __packed;

struct sf_epoch_blob {
	uint32_t magic;
	uint16_t version;
	uint16_t epoch;
	uint16_t boots;
	uint16_t pad;
} __packed;

BUILD_ASSERT(sizeof(struct sf_persist_blob) < 512, "profile blob too large for settings");
BUILD_ASSERT(sizeof(struct sf_epoch_blob) == 12, "epoch blob size");

static struct sf_persist_blob g_cfg;
static struct sf_epoch_blob g_epoch;
static bool g_have_cfg;
static bool g_have_epoch;
static bool g_autostart;
static bool g_present;
static bool g_inited;

static int on_set(const char *name, size_t len, settings_read_cb read_cb, void *cb_arg)
{
	const char *next;
	ssize_t n;

	if (settings_name_steq(name, "cfg", &next) && next == NULL) {
		if (len != sizeof(g_cfg)) {
			LOG_WRN("sf/cfg size %u, image expects %u — profile ignored", (unsigned)len,
				(unsigned)sizeof(g_cfg));
			return -EINVAL;
		}
		n = read_cb(cb_arg, &g_cfg, sizeof(g_cfg));
		if (n < 0 || (size_t)n != sizeof(g_cfg)) {
			return n < 0 ? (int)n : -EINVAL;
		}
		if (g_cfg.magic != SF_CFG_MAGIC || g_cfg.version != SF_VERSION) {
			LOG_WRN("sf/cfg bad magic or version");
			return -EINVAL;
		}
		g_have_cfg = true;
		return 0;
	}
	if (settings_name_steq(name, "epoch", &next) && next == NULL) {
		if (len != sizeof(g_epoch)) {
			return -EINVAL;
		}
		n = read_cb(cb_arg, &g_epoch, sizeof(g_epoch));
		if (n < 0 || (size_t)n != sizeof(g_epoch)) {
			return n < 0 ? (int)n : -EINVAL;
		}
		if (g_epoch.magic != SF_EPOCH_MAGIC || g_epoch.version != SF_VERSION) {
			return -EINVAL;
		}
		g_have_epoch = true;
		return 0;
	}
	return -ENOENT;
}

SETTINGS_STATIC_HANDLER_DEFINE(sf_store, "sf", NULL, on_set, NULL, NULL);

static int ensure(void)
{
	int rc;

	if (g_inited) {
		return 0;
	}
	rc = settings_subsys_init();
	if (rc != 0 && rc != -EALREADY) {
		LOG_ERR("settings init %d", rc);
		return rc;
	}
	rc = settings_load();
	if (rc != 0) {
		LOG_WRN("settings_load %d", rc);
		return rc;
	}
	g_inited = true;
	return 0;
}

int sf_persist_init(void)
{
	return ensure();
}

static bool cfg_sane(const struct sf_persist_blob *b)
{
	if (b->role > SF_ROLE_SINK || b->tx_power > 13 || b->mcs > 7) {
		return false;
	}
	if (b->ttl < 1 || b->ttl > 16 || b->max_attempts < 1 || b->n_up < 1) {
		return false;
	}
	if (b->payload_len == 0 || b->payload_len > CONFIG_SF_PHY_MTU - SF_HDR_LEN) {
		return false;
	}
	if (b->payload_len > CONFIG_SF_SMALL_PAYLOAD &&
	    (CONFIG_SF_LARGE_SLOTS == 0 || b->payload_len > CONFIG_SF_LARGE_PAYLOAD)) {
		return false;
	}
	if (b->nroutes > CONFIG_SF_ROUTE_MAX) {
		return false;
	}
	if (b->ack_timeout_ms == 0 || b->rx_slice_ms == 0) {
		return false;
	}
	return true;
}

bool sf_persist_load(struct sf_persist_view *out)
{
	unsigned int i;

	memset(out, 0, sizeof(*out));
	if (!g_have_cfg || !cfg_sane(&g_cfg)) {
		if (g_have_cfg) {
			LOG_WRN("saved profile failed sanity checks");
		}
		return false;
	}
	out->cfg.role = g_cfg.role;
	out->cfg.policy = g_cfg.policy == SF_POLICY_DROP_OLDEST ? SF_POLICY_DROP_OLDEST : SF_POLICY_REJECT;
	out->cfg.assume_up = g_cfg.assume_up ? 1u : 0u;
	out->cfg.direct_fallback = g_cfg.direct ? 1u : 0u;
	out->cfg.gen_class = g_cfg.gen_class == SF_CLASS_ALARM ? SF_CLASS_ALARM : SF_CLASS_TEL;
	out->cfg.hello_mode = g_cfg.hello_mode <= SF_HELLO_OFF ? g_cfg.hello_mode : SF_HELLO_AUTO;
	out->cfg.dedup_on = g_cfg.dedup_on ? 1u : 0u;
	out->cfg.tx_power = g_cfg.tx_power;
	out->cfg.mcs = g_cfg.mcs;
	out->cfg.ttl = g_cfg.ttl;
	out->cfg.max_attempts = g_cfg.max_attempts;
	out->cfg.n_up = g_cfg.n_up;
	out->cfg.alarm_burst = g_cfg.alarm_burst;
	out->cfg.dest_id = g_cfg.dest_id;
	out->cfg.payload_len = g_cfg.payload_len;
	out->cfg.interval_ms = g_cfg.interval_ms;
	out->cfg.hello_ms = g_cfg.hello_ms;
	out->cfg.count = g_cfg.count;
	out->cfg.ack_timeout_ms = g_cfg.ack_timeout_ms;
	out->cfg.backoff_min_ms = g_cfg.backoff_min_ms;
	out->cfg.backoff_max_ms = g_cfg.backoff_max_ms;
	out->cfg.backoff_cap_ms = g_cfg.backoff_cap_ms;
	out->cfg.nack_holdoff_ms = g_cfg.nack_holdoff_ms;
	out->cfg.inter_tx_listen_ms = g_cfg.gap_ms;
	out->cfg.rx_slice_ms = g_cfg.rx_slice_ms;
	out->cfg.hello_dead_ms = g_cfg.hello_dead_ms;
	out->cfg.t_probe_ms = g_cfg.t_probe_ms;
	out->cfg.probe_fast_ms = g_cfg.probe_fast_ms == 0 ? 1u : g_cfg.probe_fast_ms;
	out->cfg.holddown_min_ms = g_cfg.hold_min_ms;
	out->cfg.holddown_max_ms = g_cfg.hold_max_ms;
	out->cfg.holddown_reset_ms = g_cfg.hold_reset_ms;
	out->cfg.telemetry_ttl_ms = g_cfg.tel_ttl_ms;
	out->cfg.stream_idle_ms = g_cfg.stream_idle_ms;
	out->cfg.alarm_rate = g_cfg.alarm_rate;
	out->nroutes = g_cfg.nroutes;
	for (i = 0; i < g_cfg.nroutes && i < SF_ROUTE_CAP; i++) {
		out->route[i].used = true;
		out->route[i].dst = g_cfg.route[i].dst;
		out->route[i].next = g_cfg.route[i].next;
	}
	g_autostart = g_cfg.autostart != 0;
	g_present = true;
	out->autostart = g_autostart;
	out->present = true;
	LOG_INF("loaded profile role=%u dest=%u autostart=%u routes=%u", g_cfg.role, g_cfg.dest_id,
		g_cfg.autostart, g_cfg.nroutes);
	return true;
}

int sf_persist_save(const struct sf_cfg *cfg, const struct sf_route *routes, unsigned int nroutes,
		    bool autostart)
{
	struct sf_persist_blob b;
	unsigned int i;
	unsigned int n = 0;
	int rc;

	rc = ensure();
	if (rc != 0) {
		return rc;
	}
	memset(&b, 0, sizeof(b));
	b.magic = SF_CFG_MAGIC;
	b.version = SF_VERSION;
	b.nbytes = sizeof(b);
	b.autostart = autostart ? 1u : 0u;
	b.role = cfg->role;
	b.policy = cfg->policy;
	b.assume_up = cfg->assume_up;
	b.direct = cfg->direct_fallback;
	b.gen_class = cfg->gen_class;
	b.hello_mode = cfg->hello_mode;
	b.dedup_on = cfg->dedup_on;
	b.tx_power = cfg->tx_power;
	b.mcs = cfg->mcs;
	b.ttl = cfg->ttl;
	b.max_attempts = cfg->max_attempts;
	b.n_up = cfg->n_up;
	b.alarm_burst = cfg->alarm_burst;
	b.dest_id = cfg->dest_id;
	b.payload_len = cfg->payload_len;
	b.interval_ms = cfg->interval_ms;
	b.hello_ms = cfg->hello_ms;
	b.count = cfg->count;
	b.ack_timeout_ms = cfg->ack_timeout_ms;
	b.backoff_min_ms = cfg->backoff_min_ms;
	b.backoff_max_ms = cfg->backoff_max_ms;
	b.backoff_cap_ms = cfg->backoff_cap_ms;
	b.nack_holdoff_ms = cfg->nack_holdoff_ms;
	b.gap_ms = cfg->inter_tx_listen_ms;
	b.rx_slice_ms = cfg->rx_slice_ms;
	b.hello_dead_ms = cfg->hello_dead_ms;
	b.t_probe_ms = cfg->t_probe_ms;
	b.probe_fast_ms = cfg->probe_fast_ms;
	b.hold_min_ms = cfg->holddown_min_ms;
	b.hold_max_ms = cfg->holddown_max_ms;
	b.hold_reset_ms = cfg->holddown_reset_ms;
	b.tel_ttl_ms = cfg->telemetry_ttl_ms;
	b.stream_idle_ms = cfg->stream_idle_ms;
	b.alarm_rate = cfg->alarm_rate;
	for (i = 0; i < SF_ROUTE_CAP && n < CONFIG_SF_ROUTE_MAX; i++) {
		if (!routes[i].used) {
			continue;
		}
		b.route[n].dst = routes[i].dst;
		b.route[n].next = routes[i].next;
		n++;
	}
	b.nroutes = (uint8_t)n;
	rc = settings_save_one("sf/cfg", &b, sizeof(b));
	if (rc != 0) {
		LOG_ERR("save profile %d", rc);
		return rc;
	}
	g_cfg = b;
	g_have_cfg = true;
	g_present = true;
	g_autostart = autostart;
	return 0;
}

int sf_persist_clear(void)
{
	int rc = settings_delete("sf/cfg");

	g_have_cfg = false;
	g_present = false;
	g_autostart = false;
	if (rc == -ENOENT) {
		return 0;
	}
	return rc;
}

bool sf_persist_present(void)
{
	return g_present;
}

uint16_t sf_persist_boot_epoch(uint32_t *delay_ms)
{
	uint16_t epoch;
	uint16_t boots;
	uint32_t delay = 0;
	int rc;

	if (delay_ms != NULL) {
		*delay_ms = 0;
	}
	rc = ensure();
	if (rc != 0) {
		return 1;
	}
	if (!g_have_epoch) {
		uint32_t mix = (k_cycle_get_32() ^ 0x9E3779B9u) | 1u;

		epoch = (uint16_t)mix;
		if (epoch == 0) {
			epoch = 1;
		}
		boots = 1;
		LOG_INF("epoch first boot %u", epoch);
	} else {
		epoch = (uint16_t)(g_epoch.epoch + 1u);
		if (epoch == 0) {
			epoch = 1;
		}
		boots = (uint16_t)(g_epoch.boots + 1u);
	}
	if (boots > CONFIG_SF_BOOT_LOOP_MAX && CONFIG_SF_BOOT_DELAY_CAP_S > 0) {
		uint32_t k = (uint32_t)(boots - CONFIG_SF_BOOT_LOOP_MAX);
		uint32_t shift = k > 6u ? 6u : k;

		delay = 1u << shift;
		if (delay > CONFIG_SF_BOOT_DELAY_CAP_S) {
			delay = CONFIG_SF_BOOT_DELAY_CAP_S;
		}
		LOG_WRN("boot-loop guard: %u boots, delaying radio %u s", boots, delay);
	}
	memset(&g_epoch, 0, sizeof(g_epoch));
	g_epoch.magic = SF_EPOCH_MAGIC;
	g_epoch.version = SF_VERSION;
	g_epoch.epoch = epoch;
	g_epoch.boots = boots;
	rc = settings_save_one("sf/epoch", &g_epoch, sizeof(g_epoch));
	if (rc != 0) {
		LOG_ERR("save epoch %d", rc);
	} else {
		g_have_epoch = true;
	}
	if (delay_ms != NULL) {
		*delay_ms = delay * 1000u;
	}
	return epoch;
}

void sf_persist_mark_stable(void)
{
	int rc;

	if (!g_have_epoch || g_epoch.boots == 0) {
		return;
	}
	g_epoch.boots = 0;
	rc = settings_save_one("sf/epoch", &g_epoch, sizeof(g_epoch));
	if (rc != 0) {
		LOG_WRN("clear boot counter %d", rc);
	} else {
		LOG_INF("boot-loop counter cleared");
	}
}

bool sf_persist_autostart(void)
{
	return g_autostart;
}

void sf_persist_autostart_set(bool on)
{
	g_autostart = on;
}

#else /* !CONFIG_SF_PERSIST */

int sf_persist_init(void)
{
	return 0;
}
bool sf_persist_load(struct sf_persist_view *out)
{
	memset(out, 0, sizeof(*out));
	return false;
}
int sf_persist_save(const struct sf_cfg *cfg, const struct sf_route *routes, unsigned int nroutes,
		    bool autostart)
{
	ARG_UNUSED(cfg);
	ARG_UNUSED(routes);
	ARG_UNUSED(nroutes);
	ARG_UNUSED(autostart);
	return -ENOTSUP;
}
int sf_persist_clear(void)
{
	return -ENOTSUP;
}
bool sf_persist_present(void)
{
	return false;
}
uint16_t sf_persist_boot_epoch(uint32_t *delay_ms)
{
	if (delay_ms != NULL) {
		*delay_ms = 0;
	}
	return 1;
}
void sf_persist_mark_stable(void)
{
}
bool sf_persist_autostart(void)
{
	return false;
}
void sf_persist_autostart_set(bool on)
{
	ARG_UNUSED(on);
}

#endif
