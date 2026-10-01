/*
 * Copyright (c) 2026 Conexio Technologies, Inc
 *
 * SPDX-License-Identifier: Apache-2.0
 */

#include "sf_codec.h"

#include <string.h>

static void put_u16(uint8_t *p, uint16_t v)
{
	p[0] = (uint8_t)(v & 0xffu);
	p[1] = (uint8_t)((v >> 8) & 0xffu);
}

static uint16_t get_u16(const uint8_t *p)
{
	return (uint16_t)p[0] | ((uint16_t)p[1] << 8);
}

const char *sf_role_name(uint8_t role)
{
	switch (role) {
	case SF_ROLE_SOURCE:
		return "source";
	case SF_ROLE_RELAY:
		return "relay";
	case SF_ROLE_SINK:
		return "sink";
	default:
		return "invalid";
	}
}

const char *sf_class_name(uint8_t class_)
{
	switch (class_) {
	case SF_CLASS_TEL:
		return "tel";
	case SF_CLASS_ALARM:
		return "alarm";
	default:
		return "rsv";
	}
}

const char *sf_ack_name(uint8_t status)
{
	switch (status) {
	case SF_ACK_ACCEPTED:
		return "ACCEPTED";
	case SF_ACK_DUPLICATE:
		return "DUPLICATE";
	case SF_ACK_QUEUE_FULL:
		return "QUEUE_FULL";
	case SF_ACK_TTL_EXPIRED:
		return "TTL_EXPIRED";
	case SF_ACK_NO_ROUTE:
		return "NO_ROUTE";
	case SF_ACK_PROBE_REPLY:
		return "PROBE_REPLY";
	default:
		return "UNKNOWN";
	}
}

const char *sf_link_name(uint8_t state)
{
	switch (state) {
	case SF_LINK_DOWN:
		return "DOWN";
	case SF_LINK_PROBING:
		return "PROBING";
	case SF_LINK_UP:
		return "UP";
	default:
		return "INVALID";
	}
}

const char *sf_type_name(uint8_t type)
{
	switch (type) {
	case SF_TYPE_DATA:
		return "DATA";
	case SF_TYPE_HELLO:
		return "HELLO";
	case SF_TYPE_ACK:
		return "ACK";
	case SF_TYPE_PROBE:
		return "PROBE";
	default:
		return "UNKNOWN";
	}
}

static uint16_t min_len(uint8_t type)
{
	switch (type) {
	case SF_TYPE_DATA:
	case SF_TYPE_PROBE:
		return SF_HDR_LEN;
	case SF_TYPE_HELLO:
		return SF_HELLO_LEN;
	case SF_TYPE_ACK:
		return SF_ACK_LEN;
	default:
		return 0;
	}
}

int sf_codec_encode(const struct sf_frame *f, uint8_t *out, size_t cap, uint16_t phy_mtu)
{
	uint16_t need;
	uint8_t flags;

	if (f == NULL || out == NULL || f->ver != SF_PROTO_VERSION) {
		return -SF_CODEC_RANGE;
	}
	need = min_len(f->type);
	if (need == 0) {
		return -SF_CODEC_TYPE;
	}
	if (f->type == SF_TYPE_DATA) {
		need = (uint16_t)(SF_HDR_LEN + f->payload_len);
	}
	if (need > phy_mtu || need > cap || f->payload_len > SF_PAYLOAD_MAX) {
		return -SF_CODEC_MTU;
	}

	flags = (uint8_t)(f->flags & (uint8_t)~(0x0cu | SF_FLAG_RETX | SF_FLAG_SEC));
	flags = (uint8_t)(flags | ((f->class_ & 0x3u) << 2));
	if (f->retx) {
		flags |= SF_FLAG_RETX;
	}
	if (f->type == SF_TYPE_DATA) {
		flags |= SF_FLAG_CUSTODY;
	}

	memset(out, 0, need);
	out[0] = (uint8_t)((SF_PROTO_VERSION << 4) | (f->type & 0x0fu));
	out[1] = flags;
	put_u16(&out[2], f->src);
	put_u16(&out[4], f->dst);
	put_u16(&out[6], f->prev);
	put_u16(&out[8], f->next);
	put_u16(&out[10], f->seq);
	put_u16(&out[12], f->epoch);
	out[14] = f->hops;
	out[15] = f->ttl;

	if (f->type == SF_TYPE_DATA && f->payload_len > 0) {
		memcpy(&out[SF_HDR_LEN], f->payload, f->payload_len);
	} else if (f->type == SF_TYPE_HELLO) {
		out[16] = f->role;
		out[17] = f->free_pct;
	} else if (f->type == SF_TYPE_ACK) {
		out[16] = f->status;
		put_u16(&out[17], f->queue_free);
		put_u16(&out[19], f->node_epoch);
	}
	return (int)need;
}

int sf_codec_decode(const uint8_t *in, size_t len, uint16_t phy_mtu, struct sf_frame *f)
{
	uint8_t type;
	uint16_t need;

	if (in == NULL || f == NULL) {
		return -SF_CODEC_RANGE;
	}
	memset(f, 0, sizeof(*f));
	if (len < SF_HDR_LEN) {
		return -SF_CODEC_SHORT;
	}
	if (len > phy_mtu || len > SF_PAYLOAD_MAX) {
		return -SF_CODEC_MTU;
	}
	f->ver = (uint8_t)(in[0] >> 4);
	type = (uint8_t)(in[0] & 0x0fu);
	if (f->ver != SF_PROTO_VERSION) {
		return -SF_CODEC_VERSION;
	}
	if ((in[1] & SF_FLAG_SEC) != 0) {
		return -SF_CODEC_SEC;
	}
	need = min_len(type);
	if (need == 0) {
		return -SF_CODEC_TYPE;
	}
	if (len < need) {
		return -SF_CODEC_SHORT;
	}

	f->type = type;
	f->flags = in[1];
	f->class_ = (uint8_t)((in[1] >> 2) & 0x3u);
	f->retx = (in[1] & SF_FLAG_RETX) != 0;
	f->src = get_u16(&in[2]);
	f->dst = get_u16(&in[4]);
	f->prev = get_u16(&in[6]);
	f->next = get_u16(&in[8]);
	f->seq = get_u16(&in[10]);
	f->epoch = get_u16(&in[12]);
	f->hops = in[14];
	f->ttl = in[15];

	if (type == SF_TYPE_DATA) {
		f->payload_len = (uint16_t)(len - SF_HDR_LEN);
		if (f->payload_len > 0) {
			memcpy(f->payload, &in[SF_HDR_LEN], f->payload_len);
		}
		if ((in[1] & SF_FLAG_CUSTODY) == 0) {
			return -SF_CODEC_RANGE;
		}
	} else if (type == SF_TYPE_HELLO) {
		f->role = in[16];
		f->free_pct = in[17];
	} else if (type == SF_TYPE_ACK) {
		f->status = in[16];
		f->queue_free = get_u16(&in[17]);
		f->node_epoch = get_u16(&in[19]);
	}
	return SF_CODEC_OK;
}
