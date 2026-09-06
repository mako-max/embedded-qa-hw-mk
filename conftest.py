import pytest

from drivers.device_driver import DeviceDriver
from drivers.transports.uart import UARTTransport, find_device_port, get_available_ports
from tests.constants import TEST_LOGIN, TEST_PASSWORD


# Приводить пристрій до стану з новим профілем і без активної сесії.
def prepare_test_profile(driver):
    # Успішний reboot очищає RAM-профіль, тому його створюємо заново.
    if driver.reboot():
        assert driver.register(TEST_LOGIN, TEST_PASSWORD), "Registration failed"
        return

    # Якщо reboot заборонено й профілю немає, register одразу завершує підготовку.
    if driver.register(TEST_LOGIN, TEST_PASSWORD):
        return

    # Існуючий тестовий профіль потрібно авторизувати й створити заново після reboot.
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
    transport = UARTTransport(port)
    driver = DeviceDriver(transport)

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
