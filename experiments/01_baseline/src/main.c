/*
 * Copyright (c) 2024 Nordic Semiconductor ASA
 * Copyright (c) 2026 Conexio Technologies, Inc
 *
 * SPDX-License-Identifier: LicenseRef-Nordic-5-Clause
 *
 * NR+ Experimental Firmware — DECT NR+ PHY baseline (+ optional exp shell).
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

#include "experiment_packet.h"
#include "exp_runtime.h"

LOG_MODULE_REGISTER(app);

BUILD_ASSERT(CONFIG_CARRIER, "Carrier must be configured according to local regulations");
BUILD_ASSERT(CONFIG_EXPERIMENT_PACKET_SIZE >= sizeof(struct experiment_packet),
	     "CONFIG_EXPERIMENT_PACKET_SIZE too small for experiment_packet");
BUILD_ASSERT(sizeof(struct experiment_packet) == 15,
	     "experiment_packet size changed — update docs");

#define DATA_LEN_MAX 32
#define RADIO_STACK_SIZE 4096

static bool phy_fatal;
static uint64_t modem_time;
static uint16_t last_sender_id;

#define SEQ_TRACK_MAX 4
struct seq_track {
	uint16_t id;
	uint32_t seq;
	bool used;
};
static struct seq_track seq_tracks[SEQ_TRACK_MAX];

static void note_rx_sequence(uint16_t from_id, uint32_t sequence)
{
	struct seq_track *slot = NULL;
	struct exp_runtime *rt = exp_runtime_get();

	for (int i = 0; i < SEQ_TRACK_MAX; i++) {
		if (seq_tracks[i].used && seq_tracks[i].id == from_id) {
			slot = &seq_tracks[i];
			break;
		}
		if (!seq_tracks[i].used && slot == NULL) {
			slot = &seq_tracks[i];
		}
	}

	if (slot == NULL) {
		return;
	}

	if (slot->used && sequence != slot->seq + 1U && sequence != 0U) {
		LOG_WRN("RX gap: from=%u prev_seq=%u seq=%u", from_id, slot->seq, sequence);
		exp_runtime_lock();
		rt->rx_gaps++;
		exp_runtime_unlock();
	}

	slot->used = true;
	slot->id = from_id;
	slot->seq = sequence;
}

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

static void on_pdc(const struct nrf_modem_dect_phy_pdc_event *evt)
{
	uint64_t rx_time_ms = k_uptime_get();
	int rssi_i = evt->rssi_2 / 2;
	int rssi_f = (evt->rssi_2 & 1) * 5;
	struct exp_runtime *rt = exp_runtime_get();

	if (evt->len < sizeof(struct experiment_packet)) {
		LOG_WRN("RX: node=%u seq= short size=%u from=%u rssi=%d.%d time=%llu cs=fail",
			exp_device_id(), evt->len, last_sender_id, rssi_i, rssi_f,
			(unsigned long long)rx_time_ms);
		exp_runtime_lock();
		rt->rx_fail++;
		exp_runtime_unlock();
		return;
	}

	const struct experiment_packet *pkt = (const struct experiment_packet *)evt->data;
	bool cs_ok = experiment_packet_verify(pkt);
	uint16_t from_id = last_sender_id;

	if (cs_ok && pkt->device_id != 0) {
		from_id = pkt->device_id;
	}

	LOG_INF("RX: node=%u seq=%u from=%u rssi=%d.%d time=%llu tx_time=%u size=%u type=%u cs=%s",
		exp_device_id(), pkt->sequence, from_id, rssi_i, rssi_f,
		(unsigned long long)rx_time_ms, pkt->tx_time_ms, evt->len, pkt->message_type,
		cs_ok ? "ok" : "fail");

	exp_runtime_lock();
	if (cs_ok) {
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
	} else {
		rt->rx_fail++;
	}
	exp_runtime_unlock();

	if (cs_ok) {
		note_rx_sequence(from_id, pkt->sequence);
	}
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
	struct phy_ctrl_field_common header = {
		.header_format = 0x0,
		.packet_length_type = 0x0,
		.packet_length = 0x03,
		.short_network_id = (CONFIG_NETWORK_ID & 0xff),
		.transmitter_id_hi = (exp_device_id() >> 8),
		.transmitter_id_lo = (exp_device_id() & 0xff),
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
		.filter.receiver_identity = CONFIG_EXPERIMENT_DEST_RECEIVER_ID,
	};

	return nrf_modem_dect_phy_rx(&rx_op_params);
}

static void resolve_device_id(void)
{
	uint16_t id;

#if IS_ENABLED(CONFIG_EXPERIMENT_DEVICE_ID_OVERRIDE)
	id = (uint16_t)CONFIG_EXPERIMENT_DEVICE_ID;
#else
	hwinfo_get_device_id((void *)&id, sizeof(id));
#endif
	exp_set_device_id(id);
}

static int send_one(uint32_t tx_handle, uint8_t *tx_buf)
{
	int err;
	struct exp_runtime *rt = exp_runtime_get();
	uint32_t sequence;
	uint16_t tx_len;
	uint8_t tx_power;
	uint8_t mcs;
	uint8_t msg_type;
	struct experiment_packet *pkt = (struct experiment_packet *)tx_buf;

	exp_runtime_lock();
	sequence = rt->sequence;
	tx_len = rt->packet_size;
	tx_power = rt->tx_power;
	mcs = rt->mcs;
	msg_type = rt->message_type;
	exp_runtime_unlock();

	if (tx_len < sizeof(*pkt) || tx_len > DATA_LEN_MAX) {
		LOG_ERR("invalid packet size %u", tx_len);
		return -EINVAL;
	}

	memset(tx_buf, 0, DATA_LEN_MAX);
	pkt->device_id = exp_device_id();
	pkt->message_type = msg_type;
	pkt->flags = 0;
	pkt->sequence = sequence;
	pkt->tx_time_ms = (uint32_t)k_uptime_get();
	pkt->payload_len = (uint16_t)(tx_len - sizeof(*pkt));
	experiment_packet_finalize(pkt);

	LOG_INF("TX: node=%u seq=%u size=%u time=%u type=%u", exp_device_id(), pkt->sequence,
		tx_len, pkt->tx_time_ms, pkt->message_type);

	err = transmit(tx_handle, tx_buf, tx_len, tx_power, mcs);
	if (err) {
		LOG_ERR("Transmission failed, err %d", err);
		return err;
	}
	return 0;
}

static void clear_seq_tracks(void)
{
	memset(seq_tracks, 0, sizeof(seq_tracks));
}

static void radio_thread_fn(void *p1, void *p2, void *p3)
{
	ARG_UNUSED(p1);
	ARG_UNUSED(p2);
	ARG_UNUSED(p3);

	uint32_t tx_handle = 0;
	uint32_t rx_handle = 1;
	uint8_t tx_buf[DATA_LEN_MAX];
	struct exp_runtime *rt = exp_runtime_get();

	while (1) {
		exp_wait_until_start();
		clear_seq_tracks();
		LOG_INF("run active");

		while (exp_is_running()) {
			int err;

			if (IS_ENABLED(CONFIG_EXPERIMENT_TEST_MODE_RX_ONLY)) {
				err = receive(rx_handle);
				if (err) {
					LOG_ERR("Reception failed, err %d", err);
					exp_request_stop();
					exp_print_summary("rx_error");
					break;
				}
				k_sem_take(&operation_sem, K_FOREVER);
				continue;
			}

			err = send_one(tx_handle, tx_buf);
			if (err) {
				exp_request_stop();
				exp_print_summary("tx_error");
				break;
			}

			k_sem_take(&operation_sem, K_FOREVER);

			exp_runtime_lock();
			rt->sequence++;
			rt->tx_sent++;
			uint32_t sent = rt->tx_sent;
			uint32_t count = rt->tx_count;
			uint32_t interval = rt->tx_interval_ms;
			exp_runtime_unlock();

			if (count && sent >= count) {
				exp_request_stop();
				exp_print_summary("count_reached");
				LOG_INF("Reached transmission count (%u)", count);
				break;
			}

			if (!exp_is_running()) {
				exp_print_summary("stop");
				break;
			}

			if (IS_ENABLED(CONFIG_EXPERIMENT_TEST_MODE_TX_RX)) {
				err = receive(rx_handle);
				if (err) {
					LOG_ERR("Reception failed, err %d", err);
					exp_request_stop();
					exp_print_summary("rx_error");
					break;
				}
				k_sem_take(&operation_sem, K_FOREVER);
			}

			if (!exp_is_running()) {
				exp_print_summary("stop");
				break;
			}

			if (interval > 0) {
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

	exp_runtime_init();

	LOG_INF("NR+ Experimental Firmware v1.1 (01_baseline)");
	LOG_INF("mode=%s carrier=%d net=0x%x shell=%d wait_for_start=%d", exp_mode_str(),
		CONFIG_CARRIER, CONFIG_NETWORK_ID, IS_ENABLED(CONFIG_EXPERIMENT_SHELL),
		IS_ENABLED(CONFIG_EXPERIMENT_WAIT_FOR_START));

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
	LOG_INF("device_id=%u (0x%04x)", exp_device_id(), exp_device_id());
	LOG_INF("Commands: exp status | exp sett | exp start [count] | exp stop");

	err = nrf_modem_dect_phy_capability_get();
	if (err) {
		LOG_ERR("nrf_modem_dect_phy_capability_get failed, err %d", err);
	}

	k_thread_create(&radio_thread_data, radio_stack, RADIO_STACK_SIZE, radio_thread_fn, NULL,
			NULL, NULL, 5, 0, K_NO_WAIT);
	k_thread_name_set(&radio_thread_data, "exp_radio");

	if (!IS_ENABLED(CONFIG_EXPERIMENT_WAIT_FOR_START)) {
		exp_request_start(UINT32_MAX);
		LOG_INF("auto-start enabled");
	} else {
		LOG_INF("waiting for: exp start");
	}

	/* Shell (if enabled) runs on UART; radio thread does the work. */
	return 0;
}
