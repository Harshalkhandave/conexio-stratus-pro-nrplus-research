/*
 * Copyright (c) 2024 Nordic Semiconductor ASA
 * Copyright (c) 2026 Conexio Technologies, Inc
 *
 * SPDX-License-Identifier: LicenseRef-Nordic-5-Clause
 *
 * NR+ Experimental Firmware — three-node topology (app-layer relay on PHY).
 */
#include <inttypes.h>
#include <limits.h>
#include <string.h>
#include <zephyr/kernel.h>
#include <zephyr/logging/log.h>
#include <zephyr/sys/util.h>
#include <nrf_modem_dect_phy.h>
#include <modem/nrf_modem_lib.h>
#include <zephyr/drivers/hwinfo.h>

#include "topo_packet.h"
#include "topo_persist.h"
#include "topo_runtime.h"

LOG_MODULE_REGISTER(app);

BUILD_ASSERT(CONFIG_CARRIER, "Carrier must be configured according to local regulations");
BUILD_ASSERT(CONFIG_TOPO_PACKET_SIZE >= sizeof(struct topo_packet),
	     "CONFIG_TOPO_PACKET_SIZE too small for topo_packet");
BUILD_ASSERT(sizeof(struct topo_packet) == 18, "topo_packet size changed — update docs");

#define DATA_LEN_MAX 128
#define RADIO_STACK_SIZE 4096

static bool phy_fatal;
static uint64_t modem_time;
static uint16_t last_sender_id;
static int64_t last_hello_ms;

struct phy_ctrl_field_common {
	uint32_t packet_length : 4;
	uint32_t packet_length_type : 1;
	uint32_t header_format : 3;
	uint32_t short_network_id : 8;
	uint32_t transmitter_id_hi : 8;
	uint32_t transmitter_id_lo : 8;
	uint32_t df_mcs : 3;
	uint32_t reserved : 1;
	uint32_t transmit_power : 4;
	uint32_t pad : 24;
};

K_SEM_DEFINE(operation_sem, 0, 1);
K_SEM_DEFINE(deinit_sem, 0, 1);

static void on_init(const struct nrf_modem_dect_phy_init_event *evt)
{
	if (evt->err) {
		LOG_ERR("Init failed, err %d", evt->err);
		phy_fatal = true;
		return;
	}
	k_sem_give(&operation_sem);
}

static void on_deinit(const struct nrf_modem_dect_phy_deinit_event *evt)
{
	if (evt->err) {
		LOG_ERR("Deinit failed, err %d", evt->err);
		return;
	}
	k_sem_give(&deinit_sem);
}

static void on_activate(const struct nrf_modem_dect_phy_activate_event *evt)
{
	if (evt->err) {
		LOG_ERR("Activate failed, err %d", evt->err);
		phy_fatal = true;
		return;
	}
	k_sem_give(&operation_sem);
}

static void on_deactivate(const struct nrf_modem_dect_phy_deactivate_event *evt)
{
	if (evt->err) {
		LOG_ERR("Deactivate failed, err %d", evt->err);
		return;
	}
	k_sem_give(&deinit_sem);
}

static void on_configure(const struct nrf_modem_dect_phy_configure_event *evt)
{
	if (evt->err) {
		LOG_ERR("Configure failed, err %d", evt->err);
		return;
	}
	k_sem_give(&operation_sem);
}

static void on_link_config(const struct nrf_modem_dect_phy_link_config_event *evt)
{
	LOG_DBG("link_config cb time %" PRIu64 " status %d", modem_time, evt->err);
}

static void on_radio_config(const struct nrf_modem_dect_phy_radio_config_event *evt)
{
	if (evt->err) {
		LOG_ERR("Radio config failed, err %d", evt->err);
		return;
	}
	k_sem_give(&operation_sem);
}

static void on_capability_get(const struct nrf_modem_dect_phy_capability_get_event *evt)
{
	LOG_DBG("capability_get cb time %" PRIu64 " status %d", modem_time, evt->err);
}

static void on_bands_get(const struct nrf_modem_dect_phy_band_get_event *evt)
{
	LOG_DBG("bands_get cb status %d", evt->err);
}

static void on_latency_info_get(const struct nrf_modem_dect_phy_latency_info_event *evt)
{
	LOG_DBG("latency_info_get cb status %d", evt->err);
}

static void on_time_get(const struct nrf_modem_dect_phy_time_get_event *evt)
{
	LOG_DBG("time_get cb time %" PRIu64 " status %d", modem_time, evt->err);
}

static void on_cancel(const struct nrf_modem_dect_phy_cancel_event *evt)
{
	LOG_DBG("on_cancel cb status %d", evt->err);
	k_sem_give(&operation_sem);
}

static void on_op_complete(const struct nrf_modem_dect_phy_op_complete_event *evt)
{
	LOG_DBG("op_complete cb time %" PRIu64 " status %d", modem_time, evt->err);
	k_sem_give(&operation_sem);
}

static void on_pcc(const struct nrf_modem_dect_phy_pcc_event *evt)
{
	last_sender_id = (evt->hdr.hdr_type_1.transmitter_id_hi << 8) |
			 evt->hdr.hdr_type_1.transmitter_id_lo;
	LOG_DBG("PCC from device ID %u", last_sender_id);
}

static void on_pcc_crc_err(const struct nrf_modem_dect_phy_pcc_crc_failure_event *evt)
{
	ARG_UNUSED(evt);
	LOG_DBG("pcc_crc_err cb time %" PRIu64, modem_time);
}

static void handle_data_rx(const struct topo_packet *pkt, int rssi_i, int rssi_f, uint64_t rx_time_ms)
{
	struct topo_runtime *rt = topo_runtime_get();
	enum topo_role role;
	uint8_t max_hops;
	uint16_t me = topo_device_id();

	topo_runtime_lock();
	role = rt->role;
	max_hops = rt->max_hops;
	topo_runtime_unlock();

	uint64_t rx_time_us = (uint64_t)k_ticks_to_us_near64(k_uptime_ticks());

	LOG_INF("RX: node=%u type=DATA seq=%u src=%u dst=%u prev=%u hop=%u rssi=%d.%d time=%llu time_us=%llu",
		me, pkt->sequence, pkt->src, pkt->dst, pkt->prev_hop, pkt->hop_count, rssi_i,
		rssi_f, (unsigned long long)rx_time_ms, (unsigned long long)rx_time_us);

	if (pkt->dst == me) {
		LOG_INF("DELIVER: node=%u seq=%u src=%u prev=%u hops=%u rssi=%d.%d time=%llu time_us=%llu", me,
			pkt->sequence, pkt->src, pkt->prev_hop, pkt->hop_count, rssi_i, rssi_f,
			(unsigned long long)rx_time_ms, (unsigned long long)rx_time_us);
		topo_runtime_lock();
		rt->deliver_ok++;
		topo_runtime_unlock();
		return;
	}

	/* Relays forward; source/sink do not rebroadcast DATA (avoids loops / floods). */
	if (role != TOPO_ROLE_RELAY_V) {
		return;
	}

	if (pkt->src == me) {
		return;
	}

	if (topo_seen_is_dup(pkt->src, pkt->sequence)) {
		LOG_DBG("drop dup src=%u seq=%u", pkt->src, pkt->sequence);
		return;
	}

	if (pkt->hop_count >= max_hops) {
		topo_runtime_lock();
		rt->fwd_drop_ttl++;
		topo_runtime_unlock();
		LOG_INF("FORWARD_DROP: node=%u seq=%u src=%u reason=ttl hop=%u max=%u", me,
			pkt->sequence, pkt->src, pkt->hop_count, max_hops);
		return;
	}

	{
		struct topo_packet fwd = *pkt;

		fwd.prev_hop = me;
		fwd.hop_count = (uint8_t)(pkt->hop_count + 1U);
		fwd.tx_time_ms = (uint32_t)k_uptime_get();
		topo_packet_finalize(&fwd);

		if (topo_fwd_enqueue(&fwd)) {
			LOG_INF("FORWARD_Q: node=%u seq=%u src=%u dst=%u prev=%u hop=%u", me,
				fwd.sequence, fwd.src, fwd.dst, fwd.prev_hop, fwd.hop_count);
		} else {
			LOG_WRN("FORWARD_DROP: node=%u seq=%u reason=queue_full", me, pkt->sequence);
		}
	}
}

static void on_pdc(const struct nrf_modem_dect_phy_pdc_event *evt)
{
	uint64_t rx_time_ms = k_uptime_get();
	int rssi_i = evt->rssi_2 / 2;
	int rssi_f = (evt->rssi_2 & 1) * 5;
	struct topo_runtime *rt = topo_runtime_get();

	if (evt->len < sizeof(struct topo_packet)) {
		LOG_WRN("RX: node=%u short size=%u from=%u rssi=%d.%d time=%llu cs=fail",
			topo_device_id(), evt->len, last_sender_id, rssi_i, rssi_f,
			(unsigned long long)rx_time_ms);
		topo_runtime_lock();
		rt->rx_fail++;
		topo_runtime_unlock();
		return;
	}

	const struct topo_packet *pkt = (const struct topo_packet *)evt->data;
	bool cs_ok = topo_packet_verify(pkt);
	uint16_t from_id = last_sender_id;

	if (cs_ok && pkt->prev_hop != 0) {
		from_id = pkt->prev_hop;
	} else if (cs_ok && pkt->src != 0) {
		from_id = pkt->src;
	}

	if (!cs_ok) {
		LOG_INF("RX: node=%u seq=%u from=%u rssi=%d.%d time=%llu size=%u cs=fail",
			topo_device_id(), pkt->sequence, from_id, rssi_i, rssi_f,
			(unsigned long long)rx_time_ms, evt->len);
		topo_runtime_lock();
		rt->rx_fail++;
		topo_runtime_unlock();
		return;
	}

	topo_runtime_lock();
	rt->rx_ok++;
	rt->last_from = from_id;
	if (evt->rssi_2 < rt->rssi_min_x2) {
		rt->rssi_min_x2 = evt->rssi_2;
	}
	if (evt->rssi_2 > rt->rssi_max_x2) {
		rt->rssi_max_x2 = evt->rssi_2;
	}
	rt->rssi_sum_x2 += evt->rssi_2;
	rt->rssi_n++;
	topo_runtime_unlock();

	topo_neigh_note(from_id, evt->rssi_2, pkt->message_type);

	if (pkt->message_type == TOPO_MSG_HELLO) {
		LOG_INF("RX: node=%u type=HELLO src=%u rssi=%d.%d time=%llu", topo_device_id(),
			pkt->src, rssi_i, rssi_f, (unsigned long long)rx_time_ms);
		return;
	}

	if (pkt->message_type == TOPO_MSG_DATA) {
		handle_data_rx(pkt, rssi_i, rssi_f, rx_time_ms);
		return;
	}

	LOG_INF("RX: node=%u type=%u seq=%u src=%u dst=%u rssi=%d.%d time=%llu", topo_device_id(),
		pkt->message_type, pkt->sequence, pkt->src, pkt->dst, rssi_i, rssi_f,
		(unsigned long long)rx_time_ms);
}

static void on_pdc_crc_err(const struct nrf_modem_dect_phy_pdc_crc_failure_event *evt)
{
	ARG_UNUSED(evt);
	LOG_DBG("pdc_crc_err cb time %" PRIu64, modem_time);
}

static void on_rssi(const struct nrf_modem_dect_phy_rssi_event *evt)
{
	LOG_DBG("rssi cb time %" PRIu64 " carrier %d", modem_time, evt->carrier);
}

static void on_stf_cover_seq_control(const struct nrf_modem_dect_phy_stf_control_event *evt)
{
	ARG_UNUSED(evt);
	LOG_WRN("Unexpectedly in %s", __func__);
}

static void on_test_rf_tx_cw_ctrl(const struct nrf_modem_dect_phy_test_rf_tx_cw_control_event *evt)
{
	ARG_UNUSED(evt);
	LOG_WRN("Unexpectedly in %s", __func__);
}

static void dect_phy_event_handler(const struct nrf_modem_dect_phy_event *evt)
{
	modem_time = evt->time;

	switch (evt->id) {
	case NRF_MODEM_DECT_PHY_EVT_INIT:
		on_init(&evt->init);
		break;
	case NRF_MODEM_DECT_PHY_EVT_DEINIT:
		on_deinit(&evt->deinit);
		break;
	case NRF_MODEM_DECT_PHY_EVT_ACTIVATE:
		on_activate(&evt->activate);
		break;
	case NRF_MODEM_DECT_PHY_EVT_DEACTIVATE:
		on_deactivate(&evt->deactivate);
		break;
	case NRF_MODEM_DECT_PHY_EVT_CONFIGURE:
		on_configure(&evt->configure);
		break;
	case NRF_MODEM_DECT_PHY_EVT_RADIO_CONFIG:
		on_radio_config(&evt->radio_config);
		break;
	case NRF_MODEM_DECT_PHY_EVT_COMPLETED:
		on_op_complete(&evt->op_complete);
		break;
	case NRF_MODEM_DECT_PHY_EVT_CANCELED:
		on_cancel(&evt->cancel);
		break;
	case NRF_MODEM_DECT_PHY_EVT_RSSI:
		on_rssi(&evt->rssi);
		break;
	case NRF_MODEM_DECT_PHY_EVT_PCC:
		on_pcc(&evt->pcc);
		break;
	case NRF_MODEM_DECT_PHY_EVT_PCC_ERROR:
		on_pcc_crc_err(&evt->pcc_crc_err);
		break;
	case NRF_MODEM_DECT_PHY_EVT_PDC:
		on_pdc(&evt->pdc);
		break;
	case NRF_MODEM_DECT_PHY_EVT_PDC_ERROR:
		on_pdc_crc_err(&evt->pdc_crc_err);
		break;
	case NRF_MODEM_DECT_PHY_EVT_TIME:
		on_time_get(&evt->time_get);
		break;
	case NRF_MODEM_DECT_PHY_EVT_CAPABILITY:
		on_capability_get(&evt->capability_get);
		break;
	case NRF_MODEM_DECT_PHY_EVT_BANDS:
		on_bands_get(&evt->band_get);
		break;
	case NRF_MODEM_DECT_PHY_EVT_LATENCY:
		on_latency_info_get(&evt->latency_get);
		break;
	case NRF_MODEM_DECT_PHY_EVT_LINK_CONFIG:
		on_link_config(&evt->link_config);
		break;
	case NRF_MODEM_DECT_PHY_EVT_STF_CONFIG:
		on_stf_cover_seq_control(&evt->stf_cover_seq_control);
		break;
	case NRF_MODEM_DECT_PHY_EVT_TEST_RF_TX_CW_CONTROL_CONFIG:
		on_test_rf_tx_cw_ctrl(&evt->test_rf_tx_cw_control);
		break;
	}
}

static struct nrf_modem_dect_phy_config_params dect_phy_config_params = {
	.band_group_index = ((CONFIG_CARRIER >= 525 && CONFIG_CARRIER <= 551)) ? 1 : 0,
	.harq_rx_process_count = 4,
	.harq_rx_expiry_time_us = 5000000,
};

static int transmit(uint32_t handle, void *data, size_t data_len, uint8_t tx_power, uint8_t mcs)
{
	uint32_t pkt_len = (data_len <= 32) ? 0x03 : ((data_len <= 64) ? 0x07 : 0x0F);
	struct phy_ctrl_field_common header = {
		.header_format = 0x0,
		.packet_length_type = 0x0,
		.packet_length = pkt_len,
		.short_network_id = (CONFIG_NETWORK_ID & 0xff),
		.transmitter_id_hi = (topo_device_id() >> 8),
		.transmitter_id_lo = (topo_device_id() & 0xff),
		.transmit_power = tx_power,
		.reserved = 0,
		.df_mcs = mcs,
	};

	struct nrf_modem_dect_phy_tx_params tx_op_params = {
		.start_time = 0,
		.handle = handle,
		.network_id = CONFIG_NETWORK_ID,
		.phy_type = 0,
		.lbt_rssi_threshold_max = 0,
		.carrier = CONFIG_CARRIER,
		.lbt_period = NRF_MODEM_DECT_LBT_PERIOD_MAX,
		.phy_header = (union nrf_modem_dect_phy_hdr *)&header,
		.data = data,
		.data_size = data_len,
	};

	return nrf_modem_dect_phy_tx(&tx_op_params);
}

static int receive(uint32_t handle)
{
	struct nrf_modem_dect_phy_rx_params rx_op_params = {
		.start_time = 0,
		.handle = handle,
		.network_id = CONFIG_NETWORK_ID,
		.mode = NRF_MODEM_DECT_PHY_RX_MODE_CONTINUOUS,
		.rssi_interval = NRF_MODEM_DECT_PHY_RSSI_INTERVAL_OFF,
		.link_id = NRF_MODEM_DECT_PHY_LINK_UNSPECIFIED,
		.rssi_level = -60,
		.carrier = CONFIG_CARRIER,
		.duration = CONFIG_RX_PERIOD_S * MSEC_PER_SEC *
			    NRF_MODEM_DECT_MODEM_TIME_TICK_RATE_KHZ,
		.filter.short_network_id = CONFIG_NETWORK_ID & 0xff,
		.filter.is_short_network_id_used = 1,
		.filter.receiver_identity = CONFIG_TOPO_DEST_RECEIVER_ID,
	};

	return nrf_modem_dect_phy_rx(&rx_op_params);
}

static void resolve_device_id(void)
{
	uint16_t id;

#if IS_ENABLED(CONFIG_TOPO_DEVICE_ID_OVERRIDE)
	id = (uint16_t)CONFIG_TOPO_DEVICE_ID;
#else
	hwinfo_get_device_id((void *)&id, sizeof(id));
#endif
	topo_set_device_id(id);
}

static int send_buf(uint32_t tx_handle, uint8_t *tx_buf, uint16_t tx_len)
{
	struct topo_runtime *rt = topo_runtime_get();
	uint8_t tx_power;
	uint8_t mcs;
	int err;

	topo_runtime_lock();
	tx_power = rt->tx_power;
	mcs = rt->mcs;
	topo_runtime_unlock();

	err = transmit(tx_handle, tx_buf, tx_len, tx_power, mcs);
	if (err) {
		LOG_ERR("Transmission failed, err %d", err);
		return err;
	}
	return 0;
}

static int send_hello(uint32_t tx_handle, uint8_t *tx_buf)
{
	struct topo_runtime *rt = topo_runtime_get();
	struct topo_packet *pkt = (struct topo_packet *)tx_buf;
	uint16_t tx_len;
	int err;

	topo_runtime_lock();
	tx_len = rt->packet_size;
	topo_runtime_unlock();

	if (tx_len < sizeof(*pkt) || tx_len > DATA_LEN_MAX) {
		return -EINVAL;
	}

	memset(tx_buf, 0, DATA_LEN_MAX);
	pkt->src = topo_device_id();
	pkt->dst = 0;
	pkt->prev_hop = topo_device_id();
	pkt->message_type = TOPO_MSG_HELLO;
	pkt->hop_count = 0;
	pkt->flags = 0;
	pkt->sequence = 0;
	pkt->tx_time_ms = (uint32_t)k_uptime_get();
	topo_packet_finalize(pkt);

	LOG_INF("TX: node=%u type=HELLO size=%u time=%u", topo_device_id(), tx_len,
		pkt->tx_time_ms);

	err = send_buf(tx_handle, tx_buf, tx_len);
	if (err) {
		return err;
	}

	topo_runtime_lock();
	rt->hello_sent++;
	topo_runtime_unlock();
	return 0;
}

static int send_data(uint32_t tx_handle, uint8_t *tx_buf)
{
	struct topo_runtime *rt = topo_runtime_get();
	struct topo_packet *pkt = (struct topo_packet *)tx_buf;
	uint32_t sequence;
	uint16_t tx_len;
	uint16_t dest;
	int err;

	topo_runtime_lock();
	sequence = rt->sequence;
	tx_len = rt->packet_size;
	dest = rt->dest_id;
	topo_runtime_unlock();

	if (dest == 0) {
		LOG_ERR("dest_id unset");
		return -EINVAL;
	}
	if (tx_len < sizeof(*pkt) || tx_len > DATA_LEN_MAX) {
		LOG_ERR("invalid packet size %u", tx_len);
		return -EINVAL;
	}

	memset(tx_buf, 0, DATA_LEN_MAX);
	pkt->src = topo_device_id();
	pkt->dst = dest;
	pkt->prev_hop = topo_device_id();
	pkt->message_type = TOPO_MSG_DATA;
	pkt->hop_count = 0;
	pkt->flags = 0;
	pkt->sequence = sequence;
	pkt->tx_time_ms = (uint32_t)k_uptime_get();
	topo_packet_finalize(pkt);

	uint64_t tx_time_us = (uint64_t)k_ticks_to_us_near64(k_uptime_ticks());

	LOG_INF("TX: node=%u type=DATA seq=%u src=%u dst=%u hop=0 size=%u time=%u time_us=%llu",
		topo_device_id(), pkt->sequence, pkt->src, pkt->dst, tx_len, pkt->tx_time_ms,
		(unsigned long long)tx_time_us);

	err = send_buf(tx_handle, tx_buf, tx_len);
	if (err) {
		return err;
	}

	topo_runtime_lock();
	rt->sequence++;
	rt->data_sent++;
	topo_runtime_unlock();
	return 0;
}

static int send_forward(uint32_t tx_handle, uint8_t *tx_buf, const struct topo_packet *fwd)
{
	struct topo_runtime *rt = topo_runtime_get();
	struct topo_packet *pkt = (struct topo_packet *)tx_buf;
	uint16_t tx_len;
	int err;

	topo_runtime_lock();
	tx_len = rt->packet_size;
	topo_runtime_unlock();

	if (tx_len < sizeof(*pkt) || tx_len > DATA_LEN_MAX) {
		return -EINVAL;
	}

	memset(tx_buf, 0, DATA_LEN_MAX);
	*pkt = *fwd;
	topo_packet_finalize(pkt);

	LOG_INF("FORWARD: node=%u seq=%u src=%u dst=%u prev=%u hop=%u size=%u", topo_device_id(),
		pkt->sequence, pkt->src, pkt->dst, pkt->prev_hop, pkt->hop_count, tx_len);

	err = send_buf(tx_handle, tx_buf, tx_len);
	if (err) {
		return err;
	}

	topo_runtime_lock();
	rt->fwd_sent++;
	topo_runtime_unlock();
	return 0;
}

static bool maybe_hello(uint32_t tx_handle, uint8_t *tx_buf)
{
	struct topo_runtime *rt = topo_runtime_get();
	uint32_t hello_ms;
	int64_t now = k_uptime_get();

	topo_runtime_lock();
	hello_ms = rt->hello_interval_ms;
	topo_runtime_unlock();

	if (hello_ms == 0) {
		return false;
	}
	if (last_hello_ms != 0 && (now - last_hello_ms) < (int64_t)hello_ms) {
		return false;
	}

	if (send_hello(tx_handle, tx_buf) == 0) {
		last_hello_ms = now;
		k_sem_take(&operation_sem, K_FOREVER);
		return true;
	}
	return false;
}

static int drain_forwards(uint32_t tx_handle, uint8_t *tx_buf)
{
	struct topo_fwd_item item;
	int n = 0;

	while (topo_fwd_dequeue(&item)) {
		if (send_forward(tx_handle, tx_buf, &item.pkt)) {
			return -EIO;
		}
		k_sem_take(&operation_sem, K_FOREVER);
		n++;
		if (!topo_is_running()) {
			break;
		}
	}
	return n >= 0 ? 0 : -EIO;
}

static void radio_thread_fn(void *p1, void *p2, void *p3)
{
	ARG_UNUSED(p1);
	ARG_UNUSED(p2);
	ARG_UNUSED(p3);

	uint32_t tx_handle = 0;
	uint32_t rx_handle = 1;
	uint8_t tx_buf[DATA_LEN_MAX];
	struct topo_runtime *rt = topo_runtime_get();

	while (1) {
		topo_wait_until_start();
		last_hello_ms = 0;
		LOG_INF("run active role=%s", topo_role_str(rt->role));

		while (topo_is_running()) {
			int err;
			enum topo_role role;
			uint32_t interval;
			uint32_t count;
			uint32_t sent;

			topo_runtime_lock();
			role = rt->role;
			interval = rt->tx_interval_ms;
			count = rt->tx_count;
			sent = rt->data_sent;
			topo_runtime_unlock();

			maybe_hello(tx_handle, tx_buf);
			if (!topo_is_running()) {
				topo_print_summary("stop");
				break;
			}

			err = drain_forwards(tx_handle, tx_buf);
			if (err) {
				topo_request_stop();
				topo_print_summary("tx_error");
				break;
			}
			if (!topo_is_running()) {
				topo_print_summary("stop");
				break;
			}

			if (role == TOPO_ROLE_SOURCE_V) {
				err = send_data(tx_handle, tx_buf);
				if (err) {
					topo_request_stop();
					topo_print_summary("tx_error");
					break;
				}
				k_sem_take(&operation_sem, K_FOREVER);

				topo_runtime_lock();
				sent = rt->data_sent;
				count = rt->tx_count;
				topo_runtime_unlock();

				if (count && sent >= count) {
					topo_request_stop();
					topo_print_summary("count_reached");
					LOG_INF("Reached DATA count (%u)", count);
					break;
				}
			}

			if (!topo_is_running()) {
				topo_print_summary("stop");
				break;
			}

			bool do_rx = true;
			if (role == TOPO_ROLE_SOURCE_V) {
				topo_runtime_lock();
				do_rx = rt->source_rx;
				topo_runtime_unlock();
			}

			if (do_rx) {
				/* All roles listen so neighbors / delivers / forwards can arrive. */
				err = receive(rx_handle);
				if (err) {
					LOG_ERR("Reception failed, err %d", err);
					topo_request_stop();
					topo_print_summary("rx_error");
					break;
				}
				k_sem_take(&operation_sem, K_FOREVER);
			}

			if (!topo_is_running()) {
				topo_print_summary("stop");
				break;
			}

			/* Flush any packets queued during RX before next cycle. */
			err = drain_forwards(tx_handle, tx_buf);
			if (err) {
				topo_request_stop();
				topo_print_summary("tx_error");
				break;
			}

			if (role == TOPO_ROLE_SOURCE_V && interval > 0) {
				k_sleep(K_MSEC(interval));
			}
		}
	}
}

static K_THREAD_STACK_DEFINE(radio_stack, RADIO_STACK_SIZE);
static struct k_thread radio_thread_data;

int main(void)
{
	int err;

	topo_runtime_init();

	LOG_INF("NR+ Topology Firmware (03_topology)");
	LOG_INF("default_role=%s carrier=%d net=0x%x wait_for_start=%d",
		topo_role_str(topo_runtime_get()->role), CONFIG_CARRIER, CONFIG_NETWORK_ID,
		IS_ENABLED(CONFIG_TOPO_WAIT_FOR_START));

	err = nrf_modem_lib_init();
	if (err) {
		LOG_ERR("modem init failed, err %d", err);
		return err;
	}

	err = nrf_modem_dect_phy_event_handler_set(dect_phy_event_handler);
	if (err) {
		LOG_ERR("nrf_modem_dect_phy_event_handler_set failed, err %d", err);
		return err;
	}

	err = nrf_modem_dect_phy_init();
	if (err) {
		LOG_ERR("nrf_modem_dect_phy_init failed, err %d", err);
		return err;
	}

	k_sem_take(&operation_sem, K_FOREVER);
	if (phy_fatal) {
		return -EIO;
	}

	err = nrf_modem_dect_phy_configure(&dect_phy_config_params);
	if (err) {
		LOG_ERR("nrf_modem_dect_phy_configure failed, err %d", err);
		return err;
	}

	k_sem_take(&operation_sem, K_FOREVER);
	if (phy_fatal) {
		return -EIO;
	}

	err = nrf_modem_dect_phy_activate(NRF_MODEM_DECT_PHY_RADIO_MODE_LOW_LATENCY);
	if (err) {
		LOG_ERR("nrf_modem_dect_phy_activate failed, err %d", err);
		return err;
	}

	k_sem_take(&operation_sem, K_FOREVER);
	if (phy_fatal) {
		return -EIO;
	}

	resolve_device_id();
	LOG_INF("device_id=%u (0x%04x)", topo_device_id(), topo_device_id());

	if (IS_ENABLED(CONFIG_TOPO_PERSIST)) {
		(void)topo_persist_load();
	}

	LOG_INF("Commands: exp status|role|sett|start|stop|neigh|save|load|factory|autostart");

	err = nrf_modem_dect_phy_capability_get();
	if (err) {
		LOG_ERR("nrf_modem_dect_phy_capability_get failed, err %d", err);
	}

	k_thread_create(&radio_thread_data, radio_stack, RADIO_STACK_SIZE, radio_thread_fn, NULL,
			NULL, NULL, 5, 0, K_NO_WAIT);
	k_thread_name_set(&radio_thread_data, "topo_radio");

	if (topo_should_autostart()) {
		enum topo_role role;
		uint16_t dest;

		topo_runtime_lock();
		role = topo_runtime_get()->role;
		dest = topo_runtime_get()->dest_id;
		topo_runtime_unlock();

		if (role == TOPO_ROLE_SOURCE_V && dest == 0) {
			LOG_WRN("autostart skipped: source needs dest_id (exp sett dest + exp save)");
			LOG_INF("waiting for: exp start");
		} else {
			topo_request_start(UINT32_MAX);
			LOG_INF("auto-start enabled (role=%s dest=%u)", topo_role_str(role), dest);
			printk("persist: auto-start role=%s dest=%u\n", topo_role_str(role), dest);
		}
	} else {
		LOG_INF("waiting for: exp start");
	}

	return 0;
}
