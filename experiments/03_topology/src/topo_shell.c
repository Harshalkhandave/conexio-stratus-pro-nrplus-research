/*
 * Copyright (c) 2026 Conexio Technologies, Inc
 *
 * SPDX-License-Identifier: Apache-2.0
 */

#include "topo_runtime.h"

#include <stdlib.h>
#include <string.h>
#include <zephyr/kernel.h>
#include <zephyr/shell/shell.h>

#if IS_ENABLED(CONFIG_TOPO_PERSIST)
#include "topo_persist.h"
#endif

static int cmd_status(const struct shell *sh, size_t argc, char **argv)
{
	ARG_UNUSED(sh);
	ARG_UNUSED(argc);
	ARG_UNUSED(argv);
	topo_print_status();
	return 0;
}

static int cmd_neigh(const struct shell *sh, size_t argc, char **argv)
{
	ARG_UNUSED(sh);
	ARG_UNUSED(argc);
	ARG_UNUSED(argv);
	topo_print_neighbors();
	return 0;
}

static int cmd_start(const struct shell *sh, size_t argc, char **argv)
{
	uint32_t count = UINT32_MAX;
	uint32_t configured;
	enum topo_role role;
	uint16_t dest;

	if (argc >= 2) {
		count = (uint32_t)strtoul(argv[1], NULL, 0);
	}

	if (topo_is_running()) {
		shell_print(sh, "already running; stop first");
		return -EALREADY;
	}

	topo_runtime_lock();
	role = topo_runtime_get()->role;
	dest = topo_runtime_get()->dest_id;
	topo_runtime_unlock();

	if (role == TOPO_ROLE_SOURCE_V && dest == 0) {
		shell_print(sh, "source needs dest_id; set: exp sett dest <id>");
		return -EINVAL;
	}

	topo_request_start(count);
	topo_runtime_lock();
	configured = topo_runtime_get()->tx_count;
	topo_runtime_unlock();
	shell_print(sh, "started role=%s dest=%u count=%u (0=forever)", topo_role_str(role), dest,
		    configured);
	return 0;
}

static int cmd_stop(const struct shell *sh, size_t argc, char **argv)
{
	ARG_UNUSED(argc);
	ARG_UNUSED(argv);

	if (!topo_is_running()) {
		shell_print(sh, "not running");
		return 0;
	}

	topo_request_stop();
	shell_print(sh, "stop requested");
	return 0;
}

static int cmd_role(const struct shell *sh, size_t argc, char **argv)
{
	enum topo_role role;
	struct topo_runtime *rt;

	if (argc < 2) {
		shell_print(sh, "usage: exp role <source|relay|sink>");
		return -EINVAL;
	}

	if (topo_is_running()) {
		shell_print(sh, "stop the run before changing role");
		return -EBUSY;
	}

	if (!topo_role_from_str(argv[1], &role)) {
		shell_print(sh, "unknown role '%s' (source|relay|sink)", argv[1]);
		return -EINVAL;
	}

	rt = topo_runtime_get();
	topo_runtime_lock();
	rt->role = role;
	topo_runtime_unlock();
	shell_print(sh, "role=%s (RAM only — exp save to persist)", topo_role_str(role));
	return 0;
}

static int cmd_sett(const struct shell *sh, size_t argc, char **argv)
{
	struct topo_runtime *rt;
	unsigned long v;
	enum topo_role role;

	if (argc < 3) {
		shell_print(sh,
			    "usage: exp sett <interval|hello|count|power|mcs|size|dest|max_hops|"
			    "role|autostart|dedup> <value>");
		return -EINVAL;
	}

	if (topo_is_running()) {
		shell_print(sh, "stop the run before changing settings");
		return -EBUSY;
	}

	rt = topo_runtime_get();

	if (strcmp(argv[1], "role") == 0) {
		if (!topo_role_from_str(argv[2], &role)) {
			shell_print(sh, "role must be source|relay|sink");
			return -EINVAL;
		}
		topo_runtime_lock();
		rt->role = role;
		topo_runtime_unlock();
		shell_print(sh, "ok (RAM — exp save to persist)");
		return 0;
	}

	if (strcmp(argv[1], "autostart") == 0) {
#if IS_ENABLED(CONFIG_TOPO_PERSIST)
		if (strcmp(argv[2], "on") == 0 || strcmp(argv[2], "1") == 0 ||
		    strcmp(argv[2], "true") == 0) {
			topo_autostart_set(true);
		} else if (strcmp(argv[2], "off") == 0 || strcmp(argv[2], "0") == 0 ||
			   strcmp(argv[2], "false") == 0) {
			topo_autostart_set(false);
		} else {
			shell_print(sh, "autostart must be on|off (or 1|0)");
			return -EINVAL;
		}
		shell_print(sh, "autostart=%d (RAM — exp save to persist)",
			    topo_autostart_get() ? 1 : 0);
		return 0;
#else
		shell_print(sh, "persist disabled (CONFIG_TOPO_PERSIST=n)");
		return -ENOTSUP;
#endif
	}

	if (strcmp(argv[1], "dedup") == 0) {
		if (strcmp(argv[2], "on") == 0 || strcmp(argv[2], "1") == 0 ||
		    strcmp(argv[2], "true") == 0) {
			topo_runtime_lock();
			rt->dedup = true;
			topo_runtime_unlock();
		} else if (strcmp(argv[2], "off") == 0 || strcmp(argv[2], "0") == 0 ||
			   strcmp(argv[2], "false") == 0) {
			topo_runtime_lock();
			rt->dedup = false;
			topo_runtime_unlock();
		} else {
			shell_print(sh, "dedup must be on|off (or 1|0)");
			return -EINVAL;
		}
		shell_print(sh, "dedup=%d (RAM — exp save to persist)", rt->dedup ? 1 : 0);
		return 0;
	}

	v = strtoul(argv[2], NULL, 0);
	topo_runtime_lock();

	if (strcmp(argv[1], "interval") == 0) {
		rt->tx_interval_ms = (uint32_t)v;
	} else if (strcmp(argv[1], "hello") == 0) {
		rt->hello_interval_ms = (uint32_t)v;
	} else if (strcmp(argv[1], "count") == 0) {
		rt->tx_count = (uint32_t)v;
	} else if (strcmp(argv[1], "power") == 0) {
		if (v > 13) {
			topo_runtime_unlock();
			shell_print(sh, "power must be 0..13");
			return -EINVAL;
		}
		rt->tx_power = (uint8_t)v;
	} else if (strcmp(argv[1], "mcs") == 0) {
		if (v > 7) {
			topo_runtime_unlock();
			shell_print(sh, "mcs must be 0..7");
			return -EINVAL;
		}
		rt->mcs = (uint8_t)v;
	} else if (strcmp(argv[1], "size") == 0) {
		if (v < sizeof(struct topo_packet) || v > 32) {
			topo_runtime_unlock();
			shell_print(sh, "size must be %u..32",
				    (unsigned)sizeof(struct topo_packet));
			return -EINVAL;
		}
		rt->packet_size = (uint16_t)v;
	} else if (strcmp(argv[1], "dest") == 0) {
		if (v > 65535) {
			topo_runtime_unlock();
			shell_print(sh, "dest must be 0..65535");
			return -EINVAL;
		}
		rt->dest_id = (uint16_t)v;
	} else if (strcmp(argv[1], "max_hops") == 0) {
		if (v < 1 || v > 16) {
			topo_runtime_unlock();
			shell_print(sh, "max_hops must be 1..16");
			return -EINVAL;
		}
		rt->max_hops = (uint8_t)v;
	} else {
		topo_runtime_unlock();
		shell_print(sh, "unknown key '%s'", argv[1]);
		return -EINVAL;
	}

	topo_runtime_unlock();
	shell_print(sh, "ok (RAM — exp save to persist)");
	return 0;
}

#if IS_ENABLED(CONFIG_TOPO_PERSIST)
static int cmd_save(const struct shell *sh, size_t argc, char **argv)
{
	int rc;
	enum topo_role role;
	uint16_t dest;

	ARG_UNUSED(argc);
	ARG_UNUSED(argv);

	rc = topo_persist_save();
	if (rc) {
		shell_print(sh, "save failed (%d)", rc);
		return rc;
	}
	topo_runtime_lock();
	role = topo_runtime_get()->role;
	dest = topo_runtime_get()->dest_id;
	topo_runtime_unlock();
	shell_print(sh, "saved role=%s dest=%u autostart=%d", topo_role_str(role), dest,
		    topo_autostart_get() ? 1 : 0);
	return 0;
}

static int cmd_load(const struct shell *sh, size_t argc, char **argv)
{
	ARG_UNUSED(argc);
	ARG_UNUSED(argv);

	if (topo_is_running()) {
		shell_print(sh, "stop the run before load");
		return -EBUSY;
	}

	if (!topo_persist_load()) {
		shell_print(sh, "no saved profile (or load failed)");
		return -ENOENT;
	}
	shell_print(sh, "loaded role=%s dest=%u autostart=%d",
		    topo_role_str(topo_runtime_get()->role), topo_runtime_get()->dest_id,
		    topo_autostart_get() ? 1 : 0);
	return 0;
}

static int cmd_factory(const struct shell *sh, size_t argc, char **argv)
{
	int rc;

	ARG_UNUSED(argc);
	ARG_UNUSED(argv);

	if (topo_is_running()) {
		shell_print(sh, "stop the run before factory reset of profile");
		return -EBUSY;
	}

	rc = topo_persist_clear();
	if (rc) {
		shell_print(sh, "factory clear failed (%d)", rc);
		return rc;
	}
	topo_runtime_restore_defaults();
	shell_print(sh, "cleared flash profile; RAM restored to Kconfig defaults");
	shell_print(sh, "role=%s dest=%u autostart=0", topo_role_str(topo_runtime_get()->role),
		    topo_runtime_get()->dest_id);
	return 0;
}

static int cmd_autostart(const struct shell *sh, size_t argc, char **argv)
{
	if (argc < 2) {
		shell_print(sh, "autostart=%d persist=%d", topo_autostart_get() ? 1 : 0,
			    topo_persist_present() ? 1 : 0);
		shell_print(sh, "usage: exp autostart <on|off>   then: exp save");
		return 0;
	}

	if (strcmp(argv[1], "on") == 0 || strcmp(argv[1], "1") == 0) {
		topo_autostart_set(true);
	} else if (strcmp(argv[1], "off") == 0 || strcmp(argv[1], "0") == 0) {
		topo_autostart_set(false);
	} else {
		shell_print(sh, "usage: exp autostart <on|off>");
		return -EINVAL;
	}
	shell_print(sh, "autostart=%d (RAM — exp save to persist across reset)",
		    topo_autostart_get() ? 1 : 0);
	return 0;
}
#endif /* CONFIG_TOPO_PERSIST */

SHELL_STATIC_SUBCMD_SET_CREATE(
	sub_exp, SHELL_CMD(status, NULL, "Show topology status", cmd_status),
	SHELL_CMD(neigh, NULL, "Show neighbor table", cmd_neigh),
	SHELL_CMD_ARG(role, NULL, "Set role source|relay|sink", cmd_role, 2, 0),
	SHELL_CMD_ARG(start, NULL, "Start run [count]", cmd_start, 1, 1),
	SHELL_CMD(stop, NULL, "Stop run and print SUMMARY", cmd_stop),
	SHELL_CMD_ARG(sett, NULL,
		      "Set interval|hello|count|power|mcs|size|dest|max_hops|role|autostart|dedup",
		      cmd_sett, 3, 0),
#if IS_ENABLED(CONFIG_TOPO_PERSIST)
	SHELL_CMD(save, NULL, "Save role/RF/autostart to flash", cmd_save),
	SHELL_CMD(load, NULL, "Load saved profile from flash into RAM", cmd_load),
	SHELL_CMD(factory, NULL, "Erase saved profile; restore Kconfig defaults in RAM",
		  cmd_factory),
	SHELL_CMD_ARG(autostart, NULL, "Show or set autostart on|off (then exp save)",
		      cmd_autostart, 1, 1),
#endif
	SHELL_SUBCMD_SET_END);

SHELL_CMD_REGISTER(exp, &sub_exp, "NR+ topology control", NULL);
