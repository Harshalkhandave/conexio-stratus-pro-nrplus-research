/*
 * Copyright (c) 2026 Conexio Technologies, Inc
 *
 * SPDX-License-Identifier: Apache-2.0
 *
 * NR+ Experimental Firmware v1.0 — on-air packet format.
 */

#ifndef EXPERIMENT_PACKET_H_
#define EXPERIMENT_PACKET_H_

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

/** Message type: baseline experiment probe. */
#define EXPERIMENT_MSG_TYPE_BASELINE 1

/**
 * Packed application PDU carried in the DECT PHY PDC.
 *
 * Clocks: tx_time_ms is sender k_uptime_get() — not synchronized across nodes.
 * Checksum: XOR of all bytes before the checksum field.
 */
struct experiment_packet {
	uint16_t device_id;
	uint8_t message_type;
	uint8_t flags;
	uint32_t sequence;
	uint32_t tx_time_ms;
	uint16_t payload_len; /* trailing pad bytes after this header (usually 0) */
	uint8_t checksum;
} __attribute__((packed));

/* Expected sizeof(struct experiment_packet) == 15 */

static inline uint8_t experiment_checksum(const void *data, size_t len)
{
	const uint8_t *b = data;
	uint8_t cs = 0;

	for (size_t i = 0; i < len; i++) {
		cs ^= b[i];
	}
	return cs;
}

static inline void experiment_packet_finalize(struct experiment_packet *pkt)
{
	pkt->checksum = 0;
	pkt->checksum = experiment_checksum(pkt, sizeof(*pkt) - 1);
}

static inline bool experiment_packet_verify(const struct experiment_packet *pkt)
{
	uint8_t expect = experiment_checksum(pkt, sizeof(*pkt) - 1);

	return pkt->checksum == expect;
}

#endif /* EXPERIMENT_PACKET_H_ */
