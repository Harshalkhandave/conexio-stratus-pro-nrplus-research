/*
 * Copyright (c) 2026 Conexio Technologies, Inc
 *
 * SPDX-License-Identifier: Apache-2.0
 *
 * Week 3 topology — on-air application PDU (PHY broadcast).
 */

#ifndef TOPO_PACKET_H_
#define TOPO_PACKET_H_

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

/** End-to-end application probe (source → destination). */
#define TOPO_MSG_DATA 1
/** Neighbor advertisement (dst ignored / broadcast). */
#define TOPO_MSG_HELLO 2

/**
 * Packed application PDU in the DECT PHY PDC.
 *
 * Routing note: next_hop is local state only; on air we carry prev_hop
 * (who transmitted this hop) plus hop_count for path reconstruction.
 *
 * Clocks: tx_time_ms is sender k_uptime_get() — not synchronized.
 * Checksum: XOR of all bytes before the checksum field.
 */
struct topo_packet {
	uint16_t src;
	uint16_t dst;
	uint16_t prev_hop;
	uint8_t message_type;
	uint8_t hop_count;
	uint8_t flags;
	uint32_t sequence;
	uint32_t tx_time_ms;
	uint8_t checksum;
} __attribute__((packed));

/* Expected sizeof(struct topo_packet) == 18 */

static inline uint8_t topo_checksum(const void *data, size_t len)
{
	const uint8_t *b = data;
	uint8_t cs = 0;

	for (size_t i = 0; i < len; i++) {
		cs ^= b[i];
	}
	return cs;
}

static inline void topo_packet_finalize(struct topo_packet *pkt)
{
	pkt->checksum = 0;
	pkt->checksum = topo_checksum(pkt, sizeof(*pkt) - 1);
}

static inline bool topo_packet_verify(const struct topo_packet *pkt)
{
	uint8_t expect = topo_checksum(pkt, sizeof(*pkt) - 1);

	return pkt->checksum == expect;
}

#endif /* TOPO_PACKET_H_ */
