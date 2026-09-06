#!/usr/bin/env python3

import pytest

from tests.constants import (
    DISTANCE_READING_COUNT,
    MAX_DISTANCE_CM,
    MAX_DISTANCE_SPREAD_CM,
    MIN_DISTANCE_CM,
)

pytestmark = [pytest.mark.functional, pytest.mark.slow]


def test_distance_readings_are_stable(device):
    readings = device.collect_distance_readings()

    assert len(readings) == DISTANCE_READING_COUNT, (
        f"Expected {DISTANCE_READING_COUNT} distance readings, got {len(readings)}: "
        f"{readings!r}"
    )
    assert all(MIN_DISTANCE_CM <= reading <= MAX_DISTANCE_CM for reading in readings), (
        f"Distance readings contain timeout or out-of-range values: {readings!r}"
    )

    spread = max(readings) - min(readings)

    assert spread <= MAX_DISTANCE_SPREAD_CM, (
        f"Distance readings are unstable: spread {spread:.1f} cm exceeds "
        f"{MAX_DISTANCE_SPREAD_CM:.1f} cm; readings={readings!r}"
    )
