/*
 * Copyright (c) 2026 Conexio Technologies, Inc
 *
 * SPDX-License-Identifier: Apache-2.0
 */

#include "exp_runtime.h"

#include <stdlib.h>
#include <string.h>
#include <zephyr/kernel.h>
#include <zephyr/shell/shell.h>

static int cmd_status(const struct shell *sh, size_t argc, char **argv)
{
	ARG_UNUSED(sh);
	ARG_UNUSED(argc);
	ARG_UNUSED(argv);
	exp_print_status();
	return 0;
}

static int cmd_start(const struct shell *sh, size_t argc, char **argv)
{
	uint32_t count = UINT32_MAX;
	uint32_t configured;

	if (argc >= 2) {
		count = (uint32_t)strtoul(argv[1], NULL, 0);
	}

	if (exp_is_running()) {
		shell_print(sh, "already running; stop first");
		return -EALREADY;
	}

	exp_request_start(count);
	exp_runtime_lock();
	configured = exp_runtime_get()->tx_count;
	exp_runtime_unlock();
	shell_print(sh, "started (count=%u, 0=forever)", configured);
	return 0;
}

static int cmd_stop(const struct shell *sh, size_t argc, char **argv)
{
	ARG_UNUSED(argc);
	ARG_UNUSED(argv);

	if (!exp_is_running()) {
		shell_print(sh, "not running");
		return 0;
	}

	exp_request_stop();
	shell_print(sh, "stop requested");
	return 0;
}

static int cmd_sett(const struct shell *sh, size_t argc, char **argv)
{
	struct exp_runtime *rt;
	unsigned long v;

	if (argc < 3) {
		shell_print(sh, "usage: exp sett <interval|count|power|mcs|size|type> <value>");
		return -EINVAL;
	}

	if (exp_is_running()) {
		shell_print(sh, "stop the run before changing settings");
		return -EBUSY;
	}

	v = strtoul(argv[2], NULL, 0);
	rt = exp_runtime_get();
	exp_runtime_lock();

	if (strcmp(argv[1], "interval") == 0) {
		rt->tx_interval_ms = (uint32_t)v;
	} else if (strcmp(argv[1], "count") == 0) {
		rt->tx_count = (uint32_t)v;
	} else if (strcmp(argv[1], "power") == 0) {
		if (v > 13) {
			exp_runtime_unlock();
			shell_print(sh, "power must be 0..13");
			return -EINVAL;
		}
		rt->tx_power = (uint8_t)v;
	} else if (strcmp(argv[1], "mcs") == 0) {
		if (v > 7) {
			exp_runtime_unlock();
			shell_print(sh, "mcs must be 0..7");
			return -EINVAL;
		}
		rt->mcs = (uint8_t)v;
	} else if (strcmp(argv[1], "size") == 0) {
		if (v < 15 || v > 32) {
			exp_runtime_unlock();
			shell_print(sh, "size must be 15..32");
			return -EINVAL;
		}
		rt->packet_size = (uint16_t)v;
	} else if (strcmp(argv[1], "type") == 0) {
		if (v > 255) {
			exp_runtime_unlock();
			shell_print(sh, "type must be 0..255");
			return -EINVAL;
		}
		rt->message_type = (uint8_t)v;
	} else {
		exp_runtime_unlock();
		shell_print(sh, "unknown key '%s'", argv[1]);
		return -EINVAL;
	}

	exp_runtime_unlock();
	shell_print(sh, "ok");
	return 0;
}

SHELL_STATIC_SUBCMD_SET_CREATE(sub_exp,
			       SHELL_CMD(status, NULL, "Show experiment status", cmd_status),
			       SHELL_CMD_ARG(start, NULL, "Start run [count]", cmd_start, 1, 1),
			       SHELL_CMD(stop, NULL, "Stop run and print SUMMARY", cmd_stop),
			       SHELL_CMD_ARG(sett, NULL, "Set interval|count|power|mcs|size|type",
					     cmd_sett, 3, 0),
			       SHELL_SUBCMD_SET_END);

SHELL_CMD_REGISTER(exp, &sub_exp, "NR+ experiment control", NULL);
