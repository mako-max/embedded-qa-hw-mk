#!/usr/bin/env python3

from statistics import mean

import pytest

from tests.constants import (
    DISTANCE_READING_COUNT,
    DISTANCE_SERIES_COUNT,
    MAX_DISTANCE_CM,
    MAX_DISTANCE_MEAN_SPREAD_CM,
    MAX_DISTANCE_SPREAD_CM,
    MIN_DISTANCE_CM,
)

pytestmark = [pytest.mark.functional, pytest.mark.slow]


def test_distance_readings_are_stable(device):
    series_means = []

    # Серії порівнюємо в одному тесті: окремі parametrized-кейси не виявили б
    # зміщення між запусками, якщо кожна серія сама по собі стабільна.
    for series_number in range(1, DISTANCE_SERIES_COUNT + 1):
        readings = device.collect_distance_readings()

        assert len(readings) == DISTANCE_READING_COUNT, (
            f"Series {series_number}: expected {DISTANCE_READING_COUNT} readings, "
            f"got {len(readings)} (missing readings or sensor timeout): {readings!r}"
        )
        assert all(
            MIN_DISTANCE_CM <= reading <= MAX_DISTANCE_CM for reading in readings
        ), f"Series {series_number}: out-of-range distance readings: {readings!r}"

        spread = max(readings) - min(readings)
        series_mean = mean(readings)
        series_means.append(series_mean)
        print(
            f"Distance series {series_number}: readings={readings!r}; "
            f"mean={series_mean:.2f} cm; spread={spread:.2f} cm"
        )

        assert spread <= MAX_DISTANCE_SPREAD_CM, (
            f"Series {series_number}: spread {spread:.2f} cm exceeds "
            f"{MAX_DISTANCE_SPREAD_CM:.2f} cm; readings={readings!r}"
        )

    # Max-min середніх порівнює всі запуски, зокрема другий із третім,
    # а не лише кожний наступний із початковим baseline.
    mean_spread = max(series_means) - min(series_means)

    assert mean_spread <= MAX_DISTANCE_MEAN_SPREAD_CM, (
        f"Distance is not repeatable across {DISTANCE_SERIES_COUNT} series: "
        f"mean spread {mean_spread:.2f} cm exceeds "
        f"{MAX_DISTANCE_MEAN_SPREAD_CM:.2f} cm; series means={series_means!r}"
    )
