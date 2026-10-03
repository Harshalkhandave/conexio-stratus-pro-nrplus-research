#include <zephyr/kernel.h>
#include <zephyr/device.h>
#include <zephyr/drivers/sensor.h>
#include <stdio.h>

int main(void)
{
	const struct device *const dht = DEVICE_DT_GET_ANY(aosong_dht);
	struct sensor_value temp, humidity;

	printf("DHT11 Minimal Baremetal Test Application Started!\n");
	printf("DECT NR+ Radio Stack is DISABLED. CPU is 100%% dedicated to DHT11.\n");

	if (dht == NULL || !device_is_ready(dht)) {
		printf("ERROR: DHT11 device not ready or not found in devicetree!\n");
		return 0;
	}

	while (1) {
		int rc = sensor_sample_fetch(dht);
		if (rc == 0) {
			sensor_channel_get(dht, SENSOR_CHAN_AMBIENT_TEMP, &temp);
			sensor_channel_get(dht, SENSOR_CHAN_HUMIDITY, &humidity);
			
			printf("Success -> Temp: %d.%06d C, Hum: %d.%06d %%\n",
			       temp.val1, temp.val2, humidity.val1, humidity.val2);
		} else {
			printf("Failed to fetch data from DHT11 rc=%d\n", rc);
		}

		k_sleep(K_SECONDS(10));
	}
	return 0;
}
