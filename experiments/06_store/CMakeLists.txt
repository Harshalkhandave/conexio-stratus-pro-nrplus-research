#
# Copyright (c) 2026 Conexio Technologies, Inc
#
# SPDX-License-Identifier: Apache-2.0
#

cmake_minimum_required(VERSION 3.20.0)

find_package(Zephyr REQUIRED HINTS $ENV{ZEPHYR_BASE})
project(nrplus_exp_store)

target_sources(app PRIVATE
  src/main.c
  src/sf_codec.c
  src/sf_dedup.c
  src/sf_store.c
  src/sf_link.c
  src/sf_node.c
  src/sf_port.c
  src/sf_shell.c
  src/sf_persist.c
)

target_include_directories(app PRIVATE src)
