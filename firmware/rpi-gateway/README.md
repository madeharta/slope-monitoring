# firmware/rpi-gateway

Raspberry Pi **edge gateway** (Python, paho-mqtt) — collects serial/LoRa sensors and forwards to MQTT. This is a distinct role from the ESP32/MKR publishers, realistic for remote slopes, and demonstrates genuinely different device capabilities.

Must emit the shared envelope/measurements payload and publish to `slope/{site_id}/{device_id}/data`.

Not yet implemented.
