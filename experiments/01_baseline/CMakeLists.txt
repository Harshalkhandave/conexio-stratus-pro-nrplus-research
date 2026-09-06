#
# Copyright (c) 2024 Nordic Semiconductor
# Copyright (c) 2026 Conexio Technologies, Inc
#
# SPDX-License-Identifier: LicenseRef-Nordic-5-Clause
#

cmake_minimum_required(VERSION 3.20.0)

find_package(Zephyr REQUIRED HINTS $ENV{ZEPHYR_BASE})
project(nrplus_exp_baseline)

target_sources(app PRIVATE src/main.c)
target_include_directories(app PRIVATE src)
