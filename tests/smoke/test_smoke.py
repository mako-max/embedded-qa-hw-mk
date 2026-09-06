#!/usr/bin/env python3

import pytest

pytestmark = pytest.mark.smoke


# Перевіряє, що UART CLI відповідає та містить ключові системні команди.
def test_device_responds_to_help(connected_device):
    assert connected_device.is_cli_responsive(), (
        "Device CLI did not return the expected help response"
    )


# Перевіряє базовий стан системи без залежності від зовнішніх сенсорів.
def test_device_reports_healthy_system_status(device):
    assert device.is_system_status_healthy(), (
        "Device status is incomplete, unavailable, or reports no free heap"
    )


# Перевіряє, що після reboot застосунок стартує і CLI знову доступний.
def test_device_remains_responsive_after_reboot(device):
    assert device.reboot(), "Device did not report application startup after reboot"
    assert device.is_cli_responsive(), "Device CLI is unavailable after reboot"
