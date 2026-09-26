/*
 * Copyright (c) 2026 Conexio Technologies, Inc
 *
 * SPDX-License-Identifier: Apache-2.0
 *
 * Persist topology role / RF / autostart across reset using Zephyr settings (NVS).
 */

#include "topo_persist.h"

#include "topo_runtime.h"

#include <errno.h>
#include <string.h>
#include <zephyr/kernel.h>
#include <zephyr/logging/log.h>
#include <zephyr/settings/settings.h>
#include <zephyr/sys/printk.h>

LOG_MODULE_REGISTER(topo_persist, CONFIG_DECT_PHY_TOPO_LOG_LEVEL);

#define TOPO_PERSIST_MAGIC   0x4F504F54u /* 'TOPO' */
#define TOPO_PERSIST_VERSION 1u
#define TOPO_PERSIST_KEY     "topo/cfg"

struct topo_persist_cfg {
	uint32_t magic;
	uint16_t version;
	uint8_t autostart;
	uint8_t role;
	uint16_t dest_id;
	uint8_t max_hops;
	uint8_t tx_power;
	uint8_t mcs;
	uint16_t packet_size;
	uint32_t tx_interval_ms;
	uint32_t hello_interval_ms;
	uint32_t tx_count;
	uint8_t dedup;
	uint8_t reserved[8];
} __packed;

BUILD_ASSERT(sizeof(struct topo_persist_cfg) == 36, "persist blob size");

static bool g_autostart;
static bool g_present;
static struct topo_persist_cfg g_loaded;
static bool g_have_loaded_blob;

static int persist_set_handler(const char *name, size_t len, settings_read_cb read_cb, void *cb_arg)
{
	const char *next;
	int rc;
	ssize_t n;

	if (settings_name_steq(name, "cfg", &next) && !next) {
		if (len != sizeof(g_loaded)) {
			LOG_WRN("topo/cfg size mismatch %u vs %u", (unsigned)len,
				(unsigned)sizeof(g_loaded));
			return -EINVAL;
		}
		n = read_cb(cb_arg, &g_loaded, sizeof(g_loaded));
		if (n < 0) {
			return (int)n;
		}
		if ((size_t)n != sizeof(g_loaded)) {
			return -EINVAL;
		}
		if (g_loaded.magic != TOPO_PERSIST_MAGIC || g_loaded.version != TOPO_PERSIST_VERSION) {
			LOG_WRN("topo/cfg bad magic/version");
			return -EINVAL;
		}
		g_have_loaded_blob = true;
		return 0;
	}

	return -ENOENT;
}

SETTINGS_STATIC_HANDLER_DEFINE(topo, "topo", NULL, persist_set_handler, NULL, NULL);

static void apply_blob_to_runtime(const struct topo_persist_cfg *cfg)
{
	struct topo_runtime *rt = topo_runtime_get();

	topo_runtime_lock();
	rt->role = (enum topo_role)cfg->role;
	rt->dest_id = cfg->dest_id;
	rt->max_hops = cfg->max_hops;
	rt->tx_power = cfg->tx_power;
	rt->mcs = cfg->mcs;
	rt->packet_size = cfg->packet_size;
	rt->tx_interval_ms = cfg->tx_interval_ms;
	rt->hello_interval_ms = cfg->hello_interval_ms;
	rt->tx_count = cfg->tx_count;
	rt->dedup = cfg->dedup != 0;
	topo_runtime_unlock();

	g_autostart = cfg->autostart != 0;
	g_present = true;
}

static void fill_blob_from_runtime(struct topo_persist_cfg *cfg)
{
	struct topo_runtime *rt = topo_runtime_get();

	memset(cfg, 0, sizeof(*cfg));
	cfg->magic = TOPO_PERSIST_MAGIC;
	cfg->version = TOPO_PERSIST_VERSION;
	cfg->autostart = g_autostart ? 1U : 0U;

	topo_runtime_lock();
	cfg->role = (uint8_t)rt->role;
	cfg->dest_id = rt->dest_id;
	cfg->max_hops = rt->max_hops;
	cfg->tx_power = rt->tx_power;
	cfg->mcs = rt->mcs;
	cfg->packet_size = rt->packet_size;
	cfg->tx_interval_ms = rt->tx_interval_ms;
	cfg->hello_interval_ms = rt->hello_interval_ms;
	cfg->tx_count = rt->tx_count;
	cfg->dedup = rt->dedup ? 1U : 0U;
	topo_runtime_unlock();
}

bool topo_persist_load(void)
{
	int rc;

	g_have_loaded_blob = false;
	g_present = false;

	rc = settings_subsys_init();
	if (rc && rc != -EALREADY) {
		LOG_ERR("settings_subsys_init failed %d", rc);
		return false;
	}

	rc = settings_load();
	if (rc) {
		LOG_WRN("settings_load failed %d", rc);
		return false;
	}

	if (!g_have_loaded_blob) {
		LOG_INF("no saved topology profile");
		return false;
	}

	if (g_loaded.role > TOPO_ROLE_SINK_V) {
		LOG_WRN("invalid saved role %u", g_loaded.role);
		return false;
	}
	if (g_loaded.packet_size < sizeof(struct topo_packet) || g_loaded.packet_size > 32) {
		LOG_WRN("invalid saved size %u", g_loaded.packet_size);
		return false;
	}
	if (g_loaded.max_hops < 1 || g_loaded.max_hops > 16) {
		LOG_WRN("invalid saved max_hops %u", g_loaded.max_hops);
		return false;
	}
	if (g_loaded.tx_power > 13 || g_loaded.mcs > 7) {
		LOG_WRN("invalid saved RF params");
		return false;
	}

	apply_blob_to_runtime(&g_loaded);
	LOG_INF("loaded profile role=%s dest=%u autostart=%u", topo_role_str(g_loaded.role),
		g_loaded.dest_id, g_loaded.autostart);
	printk("persist: loaded role=%s dest=%u power=%u autostart=%u dedup=%u\n",
	       topo_role_str((enum topo_role)g_loaded.role), g_loaded.dest_id, g_loaded.tx_power,
	       g_loaded.autostart, g_loaded.dedup);
	return true;
}

int topo_persist_save(void)
{
	struct topo_persist_cfg cfg;
	int rc;

	rc = settings_subsys_init();
	if (rc && rc != -EALREADY) {
		return rc;
	}

	fill_blob_from_runtime(&cfg);
	rc = settings_save_one(TOPO_PERSIST_KEY, &cfg, sizeof(cfg));
	if (rc) {
		LOG_ERR("settings_save_one failed %d", rc);
		return rc;
	}

	g_loaded = cfg;
	g_have_loaded_blob = true;
	g_present = true;
	LOG_INF("saved profile role=%s dest=%u autostart=%u", topo_role_str(cfg.role), cfg.dest_id,
		cfg.autostart);
	return 0;
}

int topo_persist_clear(void)
{
	int rc;

	rc = settings_subsys_init();
	if (rc && rc != -EALREADY) {
		return rc;
	}

	rc = settings_delete(TOPO_PERSIST_KEY);
	if (rc && rc != -ENOENT) {
		LOG_ERR("settings_delete failed %d", rc);
		return rc;
	}

	g_present = false;
	g_have_loaded_blob = false;
	g_autostart = false;
	memset(&g_loaded, 0, sizeof(g_loaded));
	LOG_INF("cleared saved topology profile");
	return 0;
}

bool topo_persist_present(void)
{
	return g_present;
}

bool topo_autostart_get(void)
{
	return g_autostart;
}

void topo_autostart_set(bool on)
{
	g_autostart = on;
}
