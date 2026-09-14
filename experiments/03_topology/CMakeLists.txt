#
# Copyright (c) 2024 Nordic Semiconductor
# Copyright (c) 2026 Conexio Technologies, Inc
#
# SPDX-License-Identifier: LicenseRef-Nordic-5-Clause
#

cmake_minimum_required(VERSION 3.20.0)

find_package(Zephyr REQUIRED HINTS $ENV{ZEPHYR_BASE})
project(nrplus_exp_topology)

target_sources(app PRIVATE
  src/main.c
  src/topo_runtime.c
)

target_include_directories(app PRIVATE src)

if(CONFIG_TOPO_SHELL)
  target_sources(app PRIVATE src/topo_shell.c)
endif()
