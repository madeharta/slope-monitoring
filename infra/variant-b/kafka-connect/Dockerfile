# Kafka Connect + the Stream Reactor MQTT source connector.
#
# Stream Reactor's MqttSourceConnector is Apache-2.0 (open source) — chosen over
# Confluent's MQTT connector, which is under the Confluent evaluation licence and
# would be a licensing risk for a thesis benchmark that re-runs repeatedly.
#
# The connector is downloaded at build time and dropped into the plugin path.
# SR_VERSION is the one thing to verify on first bring-up: the release asset URL
# must resolve. Check the tags at
# https://github.com/lensesio/stream-reactor/releases and bump SR_VERSION if the
# download 404s — the connector's config keys are stable across 8.x.
FROM confluentinc/cp-kafka-connect-base:7.6.1

ARG SR_VERSION=8.1.30
ARG SR_ASSET=kafka-connect-mqtt-${SR_VERSION}.zip
ARG SR_URL=https://github.com/lensesio/stream-reactor/releases/download/${SR_VERSION}/${SR_ASSET}

USER root
# The cp-kafka-connect-base image (UBI-minimal) ships curl but not unzip —
# install it via microdnf (UBI's package manager) before extracting.
RUN microdnf install -y unzip && \
    mkdir -p /usr/share/confluent-hub-components && \
    curl -fsSL -o /tmp/mqtt.zip "${SR_URL}" && \
    unzip -q /tmp/mqtt.zip -d /usr/share/confluent-hub-components && \
    rm /tmp/mqtt.zip && \
    microdnf clean all
USER appuser
