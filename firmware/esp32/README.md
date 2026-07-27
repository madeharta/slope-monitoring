# firmware/esp32

PlatformIO project for ESP32 devices. MQTT publisher via PubSubClient or ESP-MQTT.

Must emit the shared envelope/measurements payload (see `common/schema.py`) and publish to `slope/{site_id}/{device_id}/data`. Output must be identical across all firmware platforms.

Not yet implemented — hardware not deployed; synthetic load is used for benchmarking.
