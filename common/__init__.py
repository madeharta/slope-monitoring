"""Shared wire contract between producers (loadgen, firmware) and consumers.

Kept deliberately dependency-light so both sides agree on exactly one
definition of the payload envelope, the MQTT topic scheme, and the latency
math. Not in context.md's original layout; added because the producer and
consumer must not drift on the wire format.
"""
