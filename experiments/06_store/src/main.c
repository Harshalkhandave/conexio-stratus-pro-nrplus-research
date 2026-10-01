/*
 * Copyright (c) 2026 Conexio Technologies, Inc
 *
 * SPDX-License-Identifier: Apache-2.0
 *
 * Modem bring-up and the half-duplex radio thread.
 * Protocol decisions live in sf_node.c. This file only moves frames.
 */

#include "sf_port.h"

#include <string.h>

#include <zephyr/drivers/hwinfo.h>
#include <zephyr/kernel.h>
#include <zephyr/logging/log.h>
#include <modem/nrf_modem_lib.h>
#include <nrf_modem_dect_phy.h>

LOG_MODULE_DECLARE(app, CONFIG_SF_LOG_LEVEL);

#define TX_HANDLE 0u
#define RX_HANDLE 1u

static bool phy_fatal;
static uint64_t modem_time;
/* Written by the modem callback immediately before it gives op_sem. */
static volatile int op_result;

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

K_SEM_DEFINE(op_sem, 0, 4);

static void sem_give(void)
{
	(void)k_sem_give(&op_sem);
}

static void on_init(const struct nrf_modem_dect_phy_init_event *evt)
{
	if (evt->err) {
		LOG_ERR("phy init %d", evt->err);
		phy_fatal = true;
	}
	sem_give();
}

static void on_deinit(const struct nrf_modem_dect_phy_deinit_event *evt)
{
	ARG_UNUSED(evt);
	sem_give();
}

static void on_activate(const struct nrf_modem_dect_phy_activate_event *evt)
{
	if (evt->err) {
		LOG_ERR("phy activate %d", evt->err);
		phy_fatal = true;
	}
	sem_give();
}

static void on_deactivate(const struct nrf_modem_dect_phy_deactivate_event *evt)
{
	ARG_UNUSED(evt);
	sem_give();
}

static void on_configure(const struct nrf_modem_dect_phy_configure_event *evt)
{
	if (evt->err) {
		LOG_ERR("phy configure %d", evt->err);
		phy_fatal = true;
	}
	sem_give();
}

static bool op_succeeded(int err)
{
	return err == NRF_MODEM_DECT_PHY_SUCCESS || err == NRF_MODEM_DECT_PHY_OK_WITH_HARQ_RESET;
}

static void on_op_complete(const struct nrf_modem_dect_phy_op_complete_event *evt)
{
	op_result = (int)evt->err;
	if (!op_succeeded(op_result)) {
		LOG_WRN("phy op handle %u err %d", evt->handle, op_result);
	}
	sem_give();
}

static void on_cancel(const struct nrf_modem_dect_phy_cancel_event *evt)
{
	ARG_UNUSED(evt);
	sem_give();
}

static void on_pdc(const struct nrf_modem_dect_phy_pdc_event *evt)
{
	sf_port_on_pdc(evt->data, evt->len, (int16_t)evt->rssi_2);
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
	case NRF_MODEM_DECT_PHY_EVT_COMPLETED:
		on_op_complete(&evt->op_complete);
		break;
	case NRF_MODEM_DECT_PHY_EVT_CANCELED:
		on_cancel(&evt->cancel);
		break;
	case NRF_MODEM_DECT_PHY_EVT_PDC:
		on_pdc(&evt->pdc);
		break;
	case NRF_MODEM_DECT_PHY_EVT_PDC_ERROR:
	case NRF_MODEM_DECT_PHY_EVT_PCC_ERROR:
		LOG_DBG("phy crc error t=%" PRIu64, modem_time);
		break;
	case NRF_MODEM_DECT_PHY_EVT_PCC:
	case NRF_MODEM_DECT_PHY_EVT_RSSI:
	case NRF_MODEM_DECT_PHY_EVT_RADIO_CONFIG:
	case NRF_MODEM_DECT_PHY_EVT_TIME:
	case NRF_MODEM_DECT_PHY_EVT_CAPABILITY:
	case NRF_MODEM_DECT_PHY_EVT_BANDS:
	case NRF_MODEM_DECT_PHY_EVT_LATENCY:
	case NRF_MODEM_DECT_PHY_EVT_LINK_CONFIG:
	case NRF_MODEM_DECT_PHY_EVT_STF_CONFIG:
	case NRF_MODEM_DECT_PHY_EVT_TEST_RF_TX_CW_CONTROL_CONFIG:
	default:
		break;
	}
}

/*
 * Type-1 PHY header packet_length codes used by 03_topology and the 05_performance
 * 249-byte captures. This is a modem header field, not an application setting.
 */
static uint8_t phy_len_code(uint16_t len)
{
	if (len <= 32) {
		return 0x03;
	}
	if (len <= 64) {
		return 0x07;
	}
	return 0x0F;
}

static int transmit(struct phy_ctrl_field_common *header, const uint8_t *data, uint16_t len,
		   uint8_t power, uint8_t mcs)
{
	struct nrf_modem_dect_phy_tx_params tx;

	memset(header, 0, sizeof(*header));
	header->header_format = 0x0;
	header->packet_length_type = 0x0;
	header->packet_length = phy_len_code(len);
	header->short_network_id = (CONFIG_NETWORK_ID & 0xff);
	header->transmitter_id_hi = (uint8_t)(sf_port_node_id() >> 8);
	header->transmitter_id_lo = (uint8_t)(sf_port_node_id() & 0xff);
	header->transmit_power = power;
	header->df_mcs = mcs;

	memset(&tx, 0, sizeof(tx));
	tx.start_time = 0;
	tx.handle = TX_HANDLE;
	tx.network_id = CONFIG_NETWORK_ID;
	tx.phy_type = 0;
	tx.lbt_rssi_threshold_max = 0;
	tx.carrier = CONFIG_CARRIER;
	tx.lbt_period = NRF_MODEM_DECT_LBT_PERIOD_MAX;
	tx.phy_header = (union nrf_modem_dect_phy_hdr *)header;
	tx.data = (uint8_t *)data;
	tx.data_size = len;
	return nrf_modem_dect_phy_tx(&tx);
}

static int receive(uint32_t duration_ms)
{
	struct nrf_modem_dect_phy_rx_params rx = {
		.start_time = 0,
		.handle = RX_HANDLE,
		.network_id = CONFIG_NETWORK_ID,
		.mode = NRF_MODEM_DECT_PHY_RX_MODE_CONTINUOUS,
		.rssi_interval = NRF_MODEM_DECT_PHY_RSSI_INTERVAL_OFF,
		.link_id = NRF_MODEM_DECT_PHY_LINK_UNSPECIFIED,
		.rssi_level = -60,
		.carrier = CONFIG_CARRIER,
		.duration = duration_ms * NRF_MODEM_DECT_MODEM_TIME_TICK_RATE_KHZ,
		.filter.short_network_id = CONFIG_NETWORK_ID & 0xff,
		.filter.is_short_network_id_used = 1,
		.filter.receiver_identity = CONFIG_SF_RX_FILTER_ID,
	};

	return nrf_modem_dect_phy_rx(&rx);
}

static int wait_boot(void)
{
	k_sem_take(&op_sem, K_FOREVER);
	return phy_fatal ? -EIO : 0;
}

static int wait_op(uint32_t handle)
{
	int rc = k_sem_take(&op_sem, K_MSEC(CONFIG_SF_OP_TIMEOUT_MS));
	int result;

	if (rc != 0) {
		LOG_ERR("modem operation %u timed out", handle);
		(void)nrf_modem_dect_phy_cancel(handle);
		(void)k_sem_take(&op_sem, K_MSEC(500));
		while (k_sem_take(&op_sem, K_NO_WAIT) == 0) {
		}
		return -ETIMEDOUT;
	}
	result = op_result;
	while (k_sem_take(&op_sem, K_NO_WAIT) == 0) {
	}
	if (op_succeeded(result)) {
		return 0;
	}
	LOG_WRN("modem operation %u finished err %d", handle, result);
	return -EIO;
}

static void drain_sem(void)
{
	while (k_sem_take(&op_sem, K_NO_WAIT) == 0) {
	}
}

static void radio_thread(void *p1, void *p2, void *p3)
{
	ARG_UNUSED(p1);
	ARG_UNUSED(p2);
	ARG_UNUSED(p3);

	while (1) {
		sf_port_wait_until_started();
		while (sf_port_running()) {
			struct sf_action act;
			struct phy_ctrl_field_common header;
			uint8_t buf[CONFIG_SF_PHY_MTU];
			uint8_t power;
			uint8_t mcs;
			int err;

			sf_port_note_stable_if_due();
			sf_port_poll(&act);
			if (!sf_port_running()) {
				break;
			}
			if (act.kind == SF_ACT_TX) {
				if (act.tx_len == 0 || act.tx_len > sizeof(buf)) {
					sf_port_on_tx_done(false, act.inflight);
					continue;
				}
				memcpy(buf, act.tx, act.tx_len);
				sf_port_radio(&power, &mcs);
				drain_sem();
				err = transmit(&header, buf, act.tx_len, power, mcs);
				if (err != 0) {
					LOG_ERR("tx submit %d", err);
					sf_port_on_tx_done(false, act.inflight);
					continue;
				}
				err = wait_op(TX_HANDLE);
				if (err == -ETIMEDOUT) {
					sf_port_stop("modem_timeout");
					break;
				}
				/* LBT busy, bad header, or a rejected op: the frame did not
				 * leave the radio. Count the attempt and keep listening.
				 */
				sf_port_on_tx_done(err == 0, act.inflight);
			} else {
				uint32_t slice = act.rx_ms == 0 ? 1u : act.rx_ms;

				drain_sem();
				err = receive(slice);
				if (err != 0) {
					LOG_ERR("rx submit %d", err);
					sf_port_stop("rx_error");
					break;
				}
				err = wait_op(RX_HANDLE);
				if (err == -ETIMEDOUT) {
					sf_port_stop("modem_timeout");
					break;
				}
				if (err != 0) {
					LOG_ERR("rx operation failed");
					sf_port_stop("rx_error");
					break;
				}
				sf_port_drain_rx();
			}
		}
	}
}

static K_THREAD_STACK_DEFINE(radio_stack, CONFIG_SF_RADIO_STACK);
static struct k_thread radio_thread_data;

static uint16_t read_device_id(void)
{
	uint16_t id = 0;

#if IS_ENABLED(CONFIG_SF_DEVICE_ID_OVERRIDE)
	id = (uint16_t)CONFIG_SF_DEVICE_ID;
#else
	(void)hwinfo_get_device_id((uint8_t *)&id, sizeof(id));
#endif
	return id;
}

static int boot_phy(void)
{
	static const struct nrf_modem_dect_phy_config_params params = {
		.band_group_index = ((CONFIG_CARRIER >= 525 && CONFIG_CARRIER <= 551)) ? 1 : 0,
		.harq_rx_process_count = CONFIG_SF_HARQ_RX_PROCESSES,
		.harq_rx_expiry_time_us = CONFIG_SF_HARQ_RX_EXPIRY_US,
	};
	int err;

	err = nrf_modem_lib_init();
	if (err != 0) {
		LOG_ERR("modem lib %d", err);
		return err;
	}
	err = nrf_modem_dect_phy_event_handler_set(dect_phy_event_handler);
	if (err != 0) {
		LOG_ERR("phy handler %d", err);
		return err;
	}
	err = nrf_modem_dect_phy_init();
	if (err != 0 || wait_boot() != 0) {
		LOG_ERR("phy init failed");
		return err != 0 ? err : -EIO;
	}
	err = nrf_modem_dect_phy_configure(&params);
	if (err != 0 || wait_boot() != 0) {
		LOG_ERR("phy configure failed");
		return err != 0 ? err : -EIO;
	}
	err = nrf_modem_dect_phy_activate(NRF_MODEM_DECT_PHY_RADIO_MODE_LOW_LATENCY);
	if (err != 0 || wait_boot() != 0) {
		LOG_ERR("phy activate failed");
		return err != 0 ? err : -EIO;
	}
	return 0;
}

int main(void)
{
	int err;

	sf_port_boot(read_device_id());
	err = boot_phy();
	if (err != 0) {
		return err;
	}
	k_thread_create(&radio_thread_data, radio_stack, CONFIG_SF_RADIO_STACK, radio_thread, NULL,
			NULL, NULL, 5, 0, K_NO_WAIT);
	k_thread_name_set(&radio_thread_data, "sf_radio");
	LOG_INF("shell: exp status|sett|route|start|stop|sf|link|neigh|alarm|save|load");
	if (sf_port_autostart_ok()) {
		err = sf_port_start(0);
		if (err != 0) {
			LOG_WRN("autostart failed %d", err);
		}
	} else {
		LOG_INF("idle — exp start");
	}
	return 0;
}
