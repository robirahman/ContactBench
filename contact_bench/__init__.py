"""ContactBench: a reproducible benchmark for the word game Contact.

Protocol version 0.4 (see CONTACT_BENCHMARK_SPEC.md).
"""

PROTOCOL_VERSION = "contact-v0.4"
SCHEMA_VERSION = "1.0.0"
ENGINE_VERSION = "engine-1"
PACKING_VERSION = "combined-two-longest-maximal-prefix-v1"
RNG_VERSION = "python-mt19937-sha256-seed-v1"

__all__ = [
    "PROTOCOL_VERSION",
    "SCHEMA_VERSION",
    "ENGINE_VERSION",
    "PACKING_VERSION",
    "RNG_VERSION",
]
