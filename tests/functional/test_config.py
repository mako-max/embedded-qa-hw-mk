#!/usr/bin/env python3

import pytest

from tests.constants import (
    PERSISTED_ALARM_THRESHOLD,
    PERSISTED_SENSOR_INTERVAL,
    TEST_LOGIN,
    TEST_PASSWORD,
)

pytestmark = pytest.mark.functional

PERSISTED_CONFIG = {
    "alarm_threshold": PERSISTED_ALARM_THRESHOLD,
    "sensor_interval": PERSISTED_SENSOR_INTERVAL,
}


@pytest.mark.xfail(
    reason=(
        "SENTRY-ISSUE-0004: config save reports success but configuration "
        "reverts to defaults after reboot"
    ),
    raises=AssertionError,
)
def test_saved_configuration_survives_reboot(device):
    # Початковий snapshot потрібен для cleanup, особливо після виправлення FW,
    # коли цей тест почне реально змінювати персистентну конфігурацію стенда.
    if not device.load_config():
        pytest.fail("Device did not complete initial config load")

    original_config = device.get_config_values(PERSISTED_CONFIG)
    session_available = True

    try:
        if not device.set_alarm_threshold(PERSISTED_ALARM_THRESHOLD):
            pytest.fail("Cannot set alarm_threshold for persistence test")
        if not device.set_sensor_interval(PERSISTED_SENSOR_INTERVAL):
            pytest.fail("Cannot set sensor_interval for persistence test")

        runtime_config = device.get_config_values(PERSISTED_CONFIG)
        if runtime_config != PERSISTED_CONFIG:
            pytest.fail(
                "Working configuration does not match values set before save: "
                f"{runtime_config!r}"
            )

        if not device.save_config():
            pytest.fail("Device did not report successful config save")

        # reboot() сам викликає wait_for_pattern("App started") без time.sleep().
        session_available = False
        if not device.reboot():
            pytest.fail("Device did not report application startup after reboot")

        # Профіль і сесія волатильні, тому після reboot створюємо профіль заново
        # та відновлюємо AUTH_USER через публічний API драйвера.
        if not device.login(TEST_LOGIN, TEST_PASSWORD):
            pytest.fail("Cannot restore authenticated session after reboot")
        session_available = True

        restored_config = device.get_config_values(PERSISTED_CONFIG)

        assert restored_config == PERSISTED_CONFIG, (
            "Saved configuration was not restored after reboot: "
            f"expected {PERSISTED_CONFIG!r}, got {restored_config!r}"
        )
    finally:
        # Cleanup є best effort для поточного дефектного FW. На виправленій версії
        # повертаємо початкові значення в NVS, щоб тест не забруднював наступні кейси.
        if not session_available:
            session_available = device.login(TEST_LOGIN, TEST_PASSWORD)

        if session_available:
            device.set_alarm_threshold(original_config["alarm_threshold"])
            device.set_sensor_interval(original_config["sensor_interval"])
            device.save_config()
