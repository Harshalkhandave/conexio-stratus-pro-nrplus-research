/*
 * Copyright (c) 2026 Conexio Technologies, Inc
 *
 * SPDX-License-Identifier: Apache-2.0
 *
 * Field-by-field codec. Callers never cast a received buffer to a struct.
 */

#ifndef SF_CODEC_H_
#define SF_CODEC_H_

#include "sf_types.h"

#include <stddef.h>

enum sf_codec_err {
	SF_CODEC_OK = 0,
	SF_CODEC_SHORT = 1,
	SF_CODEC_VERSION = 2,
	SF_CODEC_TYPE = 3,
	SF_CODEC_SEC = 4,
	SF_CODEC_MTU = 5,
	SF_CODEC_RANGE = 6,
};

int sf_codec_encode(const struct sf_frame *f, uint8_t *out, size_t cap, uint16_t phy_mtu);
int sf_codec_decode(const uint8_t *in, size_t len, uint16_t phy_mtu, struct sf_frame *f);

#endif /* SF_CODEC_H_ */
