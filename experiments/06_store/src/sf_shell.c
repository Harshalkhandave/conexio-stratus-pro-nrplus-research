/*
 * Copyright (c) 2026 Conexio Technologies, Inc
 *
 * SPDX-License-Identifier: Apache-2.0
 *
 * One command, exp. `exp sett` with no arguments lists every key.
 */

#include "sf_port.h"

#include <errno.h>
#include <stdlib.h>
#include <string.h>

#include <zephyr/shell/shell.h>

static void out(void *ctx, const char *line)
{
	shell_print((const struct shell *)ctx, "%s", line);
}

static int parse_u16(const char *s, uint16_t *out_v)
{
	char *end = NULL;
	unsigned long v;

	if (s == NULL || *s == '\0') {
		return -EINVAL;
	}
	v = strtoul(s, &end, 0);
	if (end == s || *end != '\0' || v > 65535ul) {
		return -EINVAL;
	}
	*out_v = (uint16_t)v;
	return 0;
}

static int cmd_status(const struct shell *sh, size_t argc, char **argv)
{
	ARG_UNUSED(argc);
	ARG_UNUSED(argv);
	sf_port_print_status(out, (void *)sh);
	return 0;
}

static int cmd_sf(const struct shell *sh, size_t argc, char **argv)
{
	ARG_UNUSED(argc);
	ARG_UNUSED(argv);
	sf_port_print_sf(out, (void *)sh);
	return 0;
}

static int cmd_link(const struct shell *sh, size_t argc, char **argv)
{
	ARG_UNUSED(argc);
	ARG_UNUSED(argv);
	sf_port_print_link(out, (void *)sh);
	return 0;
}

static int cmd_neigh(const struct shell *sh, size_t argc, char **argv)
{
	ARG_UNUSED(argc);
	ARG_UNUSED(argv);
	sf_port_print_neigh(out, (void *)sh);
	return 0;
}

static int cmd_role(const struct shell *sh, size_t argc, char **argv)
{
	char err[80];
	int rc;

	if (argc < 2) {
		shell_print(sh, "usage: exp role source|relay|sink");
		return -EINVAL;
	}
	err[0] = '\0';
	rc = sf_port_set("role", argv[1], err, sizeof(err));
	if (rc != 0) {
		shell_error(sh, "%s", err[0] ? err : "role rejected");
		return rc;
	}
	shell_print(sh, "role=%s", argv[1]);
	return 0;
}

static int cmd_start(const struct shell *sh, size_t argc, char **argv)
{
	uint32_t count = 0;
	int rc;

	if (argc >= 2) {
		char *end = NULL;
		unsigned long v = strtoul(argv[1], &end, 0);

		if (end == argv[1] || *end != '\0') {
			shell_error(sh, "count is not an integer");
			return -EINVAL;
		}
		count = (uint32_t)v;
	}
	rc = sf_port_start(count);
	if (rc == -EALREADY) {
		shell_error(sh, "already running");
	} else if (rc == -EINVAL) {
		shell_error(sh, "source needs dest: exp sett dest <id>");
	} else if (rc != 0) {
		shell_error(sh, "start failed (%d)", rc);
	} else {
		shell_print(sh, "started");
	}
	return rc;
}

static int cmd_stop(const struct shell *sh, size_t argc, char **argv)
{
	ARG_UNUSED(argc);
	ARG_UNUSED(argv);
	if (!sf_port_running()) {
		shell_print(sh, "not running");
		return 0;
	}
	sf_port_stop("user");
	shell_print(sh, "stopped");
	return 0;
}

static int cmd_sett(const struct shell *sh, size_t argc, char **argv)
{
	char err[96];
	int rc;

	if (argc == 1) {
		sf_port_print_cfg(out, (void *)sh);
		shell_print(sh, "set with: exp sett <key> <value>");
		return 0;
	}
	if (argc != 3) {
		shell_error(sh, "usage: exp sett <key> <value>");
		return -EINVAL;
	}
	err[0] = '\0';
	rc = sf_port_set(argv[1], argv[2], err, sizeof(err));
	if (rc != 0) {
		shell_error(sh, "%s", err[0] ? err : "rejected");
		return rc;
	}
	shell_print(sh, "%s=%s", argv[1], argv[2]);
	return 0;
}

static int cmd_route(const struct shell *sh, size_t argc, char **argv)
{
	char err[80];
	uint16_t dst;
	uint16_t next;
	int rc;

	if (argc == 1) {
		sf_port_print_route(out, (void *)sh);
		shell_print(sh, "usage: exp route set <dst> <next> | exp route del <dst>");
		return 0;
	}
	if (argc == 3 && strcmp(argv[1], "del") == 0) {
		if (parse_u16(argv[2], &dst) != 0) {
			shell_error(sh, "dst is not an id");
			return -EINVAL;
		}
		rc = sf_port_route_del(dst);
		if (rc != 0) {
			shell_error(sh, rc == -EBUSY ? "stop the run first" : "no such route");
			return rc;
		}
		shell_print(sh, "route del %u", dst);
		return 0;
	}
	if (argc == 4 && strcmp(argv[1], "set") == 0) {
		if (parse_u16(argv[2], &dst) != 0 || parse_u16(argv[3], &next) != 0) {
			shell_error(sh, "dst and next are ids");
			return -EINVAL;
		}
		err[0] = '\0';
		rc = sf_port_route_set(dst, next, err, sizeof(err));
		if (rc != 0) {
			shell_error(sh, "%s", err[0] ? err : "rejected");
			return rc;
		}
		shell_print(sh, "route dst=%u next=%u", dst, next);
		return 0;
	}
	shell_error(sh, "usage: exp route | exp route set <dst> <next> | exp route del <dst>");
	return -EINVAL;
}

static int cmd_flush(const struct shell *sh, size_t argc, char **argv)
{
	uint16_t n;

	ARG_UNUSED(argc);
	ARG_UNUSED(argv);
	n = sf_port_flush("shell");
	shell_print(sh, "flushed %u", n);
	return 0;
}

static int cmd_alarm(const struct shell *sh, size_t argc, char **argv)
{
	int rc;

	ARG_UNUSED(argc);
	ARG_UNUSED(argv);
	rc = sf_port_alarm();
	if (rc == -EAGAIN) {
		shell_error(sh, "alarm rate limit");
	} else if (rc == -EINVAL) {
		shell_error(sh, "alarm is only accepted on a running source");
	} else if (rc != 0) {
		shell_error(sh, "alarm not stored (%d)", rc);
	} else {
		shell_print(sh, "alarm queued");
	}
	return rc;
}

static int cmd_save(const struct shell *sh, size_t argc, char **argv)
{
	int rc;

	ARG_UNUSED(argc);
	ARG_UNUSED(argv);
	rc = sf_port_save();
	if (rc != 0) {
		shell_error(sh, "save failed (%d)", rc);
		return rc;
	}
	shell_print(sh, "saved profile autostart=%u", sf_port_autostart_get() ? 1u : 0u);
	return 0;
}

static int cmd_load(const struct shell *sh, size_t argc, char **argv)
{
	char err[80];
	int rc;

	ARG_UNUSED(argc);
	ARG_UNUSED(argv);
	err[0] = '\0';
	rc = sf_port_load(err, sizeof(err));
	if (rc != 0) {
		shell_error(sh, "%s", err[0] ? err : "load failed");
		return rc;
	}
	shell_print(sh, "loaded profile");
	sf_port_print_cfg(out, (void *)sh);
	return 0;
}

static int cmd_factory(const struct shell *sh, size_t argc, char **argv)
{
	char err[80];
	int rc;

	ARG_UNUSED(argc);
	ARG_UNUSED(argv);
	err[0] = '\0';
	rc = sf_port_factory(err, sizeof(err));
	if (rc != 0) {
		shell_error(sh, "%s", err[0] ? err : "factory failed");
		return rc;
	}
	shell_print(sh, "profile erased, RAM restored to Kconfig defaults, epoch kept");
	return 0;
}

static int cmd_autostart(const struct shell *sh, size_t argc, char **argv)
{
	if (argc < 2) {
		shell_print(sh, "autostart=%u profile=%u", sf_port_autostart_get() ? 1u : 0u,
			    sf_port_profile_present() ? 1u : 0u);
		shell_print(sh, "usage: exp autostart on|off    then exp save");
		return 0;
	}
	if (strcmp(argv[1], "on") == 0 || strcmp(argv[1], "1") == 0) {
		sf_port_autostart_set(true);
	} else if (strcmp(argv[1], "off") == 0 || strcmp(argv[1], "0") == 0) {
		sf_port_autostart_set(false);
	} else {
		shell_error(sh, "usage: exp autostart on|off");
		return -EINVAL;
	}
	shell_print(sh, "autostart=%u (RAM only until exp save)", sf_port_autostart_get() ? 1u : 0u);
	return 0;
}

SHELL_STATIC_SUBCMD_SET_CREATE(
	sub_exp, SHELL_CMD(status, NULL, "Role, counters, in-flight frame", cmd_status),
	SHELL_CMD(sf, NULL, "Store occupancy", cmd_sf),
	SHELL_CMD(link, NULL, "Next-hop link state", cmd_link),
	SHELL_CMD(neigh, NULL, "Neighbours heard", cmd_neigh),
	SHELL_CMD_ARG(route, NULL, "List, set <dst> <next>, or del <dst>", cmd_route, 1, 3),
	SHELL_CMD_ARG(role, NULL, "source|relay|sink", cmd_role, 1, 1),
	SHELL_CMD_ARG(start, NULL, "Start [count for this run]", cmd_start, 1, 1),
	SHELL_CMD(stop, NULL, "Stop and log SUMMARY", cmd_stop),
	SHELL_CMD_ARG(sett, NULL, "List keys, or set <key> <value>", cmd_sett, 1, 2),
	SHELL_CMD(flush, NULL, "Drop every stored packet", cmd_flush),
	SHELL_CMD(alarm, NULL, "Queue one alarm (running source)", cmd_alarm),
	SHELL_CMD(save, NULL, "Write the profile to flash", cmd_save),
	SHELL_CMD(load, NULL, "Load the profile into RAM", cmd_load),
	SHELL_CMD(factory, NULL, "Erase the profile, keep the epoch", cmd_factory),
	SHELL_CMD_ARG(autostart, NULL, "Show or set on|off (needs exp save)", cmd_autostart, 1, 1),
	SHELL_SUBCMD_SET_END);

SHELL_CMD_REGISTER(exp, &sub_exp, "NR+ store-and-forward", NULL);
