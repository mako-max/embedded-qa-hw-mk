#!/usr/bin/env python3

import time

import pytest

from device_driver import DeviceDriver, find_device_port, get_available_ports

# Спільні тестові дані та очікування для обох апаратних тестів.
TEST_LOGIN = "user"
TEST_PASSWORD = "111222"
WRONG_PASSWORD = "wrongpass"
SENSOR_COLLECTION_TIME = 32
EXPECTED_HISTORY_COUNT = 10
FAILED_LOGIN_ATTEMPTS = 3


# Приводить пристрій до стану з новим профілем і без активної сесії.
def prepare_test_profile(driver):
    # Успішний reboot очищає RAM-профіль, тому його створюємо заново.
    if driver.reboot():
        assert driver.register(TEST_LOGIN, TEST_PASSWORD), "Registration failed"
        return

    # Якщо reboot заборонено й профілю немає, register одразу завершує підготовку.
    if driver.register(TEST_LOGIN, TEST_PASSWORD):
        return

    # Існуючий профіль потрібно авторизувати, перезавантажити та створити заново.
    assert driver.login(
        TEST_LOGIN,
        TEST_PASSWORD,
    ), "Cannot access the existing test profile"

    assert driver.reboot(), "Failed to reset the existing test profile"
    assert driver.register(TEST_LOGIN, TEST_PASSWORD), "Registration failed"


# Відкриває окреме з'єднання для кожного тесту та завжди закриває його після тесту.
@pytest.fixture
def connected_device():
    ports = get_available_ports()
    port = find_device_port(ports)
    driver = DeviceDriver(port)

    try:
        driver.open()
        # Значення yield передається залежній фікстурі або тесту.
        yield driver
    finally:
        driver.close()


# Готує авторизований пристрій для перевірки історії сенсора.
@pytest.fixture
def device(connected_device):
    prepare_test_profile(connected_device)

    assert connected_device.login(
        TEST_LOGIN,
        TEST_PASSWORD,
    ), "Login failed after device setup"

    return connected_device


# Готує профіль без login, щоб тест міг накопичити невдалі спроби авторизації.
@pytest.fixture
def rate_limit_device(connected_device):
    prepare_test_profile(connected_device)
    return connected_device


# Перевіряє, що sensor history зберігає очікувані десять показань.
def test_sensor_history_count(device):
    device.send_command("sensor start")

    try:
        time.sleep(SENSOR_COLLECTION_TIME)
    finally:
        # Зупиняємо сенсор навіть після переривання тесту або помилки sleep.
        device.send_command("sensor stop")

    response = device.send_command("sensor history")
    # Відкидаємо службові Sensor-логи та залишаємо лише рядки history з temp.
    sensor_lines = [
        line
        for line in response
        if "[Sensor]" in line and "] temp:" in line
    ]

    actual_count = len(sensor_lines)

    assert actual_count == EXPECTED_HISTORY_COUNT, (
        f"Sensor history should contain {EXPECTED_HISTORY_COUNT} entries, "
        f"but contains {actual_count}"
    )


# Перевіряє блокування профілю після трьох неправильних паролів.
def test_login_rate_limit(rate_limit_device):
    # Кожна невдала спроба повинна завершитися без створення сесії.
    for attempt in range(1, FAILED_LOGIN_ATTEMPTS + 1):
        assert not rate_limit_device.login(
            TEST_LOGIN,
            WRONG_PASSWORD,
        ), f"Login unexpectedly succeeded on failed attempt {attempt}"

    # Перевіряємо необроблену відповідь, бо важливі маркери locked і Session Started.
    response = rate_limit_device.send_command(
        f"login {TEST_LOGIN} {TEST_PASSWORD}"
    )

    assert any("locked" in line.lower() for line in response), (
        "Account was not locked after three failed login attempts"
    )
    assert not any("Session Started" in line for line in response), (
        "Session started while the account was locked"
    )
