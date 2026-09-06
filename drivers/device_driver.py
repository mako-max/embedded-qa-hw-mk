#!/usr/bin/env python3

import argparse
import re
import sys
import time

from drivers.transports.base import Transport
from drivers.transports.uart import (
    DEFAULT_BAUDRATE,
    SERIAL_BYTESIZE,
    SERIAL_PARITY,
    SERIAL_STOPBITS,
    UARTTransport,
    find_device_port,
    get_available_ports,
    print_available_ports,
)

DEFAULT_COMMAND_TIMEOUT = 2
DEFAULT_REBOOT_TIMEOUT = 5


# Виконує команди пристрою незалежно від способу доставки даних.
class DeviceDriver:
    # Отримує готовий transport замість параметрів конкретного з'єднання.
    def __init__(self, transport: Transport, timeout=DEFAULT_COMMAND_TIMEOUT):
        self.transport = transport
        self.timeout = timeout

    # Делегує відкриття з'єднання вибраному transport.
    def open(self):
        self.transport.open()

    # Делегує коректне закриття з'єднання вибраному transport.
    def close(self):
        self.transport.close()

    # Надсилає текстову команду та повертає рядки, отримані протягом timeout.
    def send_command(self, command):
        self.transport.send_line(command)
        time.sleep(0.1)

        return self.read_lines(self.timeout)

    # Збирає непорожні текстові рядки до завершення заданого часу очікування.
    def read_lines(self, timeout):
        lines = []
        end_time = time.time() + timeout

        while time.time() < end_time:
            remaining_time = end_time - time.time()
            # Transport сам застосовує timeout до конкретної операції читання.
            raw_line = self.transport.read_line(min(0.1, max(remaining_time, 0)))

            if not raw_line:
                continue

            line = raw_line.decode("utf-8", errors="replace")
            # Видаляємо ANSI-коди кольору, щоб тести працювали з чистим текстом.
            line = re.sub(r"\x1b\[[0-9;]*[mK]", "", line)
            line = line.strip("\r\n")

            if line.strip():
                lines.append(line)

        return lines

    # Читає нові рядки, доки не знайде pattern або не завершиться timeout.
    def wait_for(self, pattern, timeout):
        end_time = time.time() + timeout

        while time.time() < end_time:
            remaining_time = end_time - time.time()
            raw_line = self.transport.read_line(min(0.1, max(remaining_time, 0)))

            if not raw_line:
                continue

            line = raw_line.decode("utf-8", errors="replace")
            # Керівні ANSI-послідовності не повинні впливати на пошук pattern.
            line = re.sub(r"\x1b\[[0-9;]*[mK]", "", line)
            line = line.strip("\r\n")

            if pattern in line:
                return True

        return False

    # Перезавантажує авторизований пристрій і очікує повідомлення про готовність.
    def reboot(self, timeout=DEFAULT_REBOOT_TIMEOUT):
        response = self.send_command("reboot")

        # Без активної сесії reboot заборонено, тому підготовка може перейти до register.
        if any("Access denied" in line for line in response):
            return False

        # Швидке завантаження може завершитися ще під час send_command().
        if any("Device ready" in line for line in response):
            return True

        # Якщо завантаження ще триває, дочитуємо serial до повідомлення Device ready.
        return self.wait_for("Device ready", timeout)

    # Створює профіль і визначає успіх за маркером у відповіді прошивки.
    def register(self, login, password):
        response = self.send_command(f"register {login} {password}")
        return any("Profile Created" in line for line in response)

    # Спочатку реєструє профіль, а потім авторизується згідно з контрактом завдання.
    def login(self, login, password):
        self.register(login, password)
        response = self.send_command(f"login {login} {password}")
        return any("Session Started" in line for line in response)


# Збирає необроблені байти transport для діагностики без декодування тексту.
def read_raw_response(transport: Transport, timeout):
    response = bytearray()
    end_time = time.time() + timeout

    while time.time() < end_time:
        remaining_time = end_time - time.time()
        raw_line = transport.read_line(min(0.1, max(remaining_time, 0)))

        if raw_line:
            response.extend(raw_line)

    return bytes(response)


# Описує параметри CLI з можливістю змінити port, baudrate і timeout.
def build_parser():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", help="serial port; detected automatically if omitted")
    parser.add_argument(
        "--baudrate",
        type=int,
        default=DEFAULT_BAUDRATE,
        help=f"serial baud rate (default: {DEFAULT_BAUDRATE})",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_COMMAND_TIMEOUT,
        help=f"response timeout in seconds (default: {DEFAULT_COMMAND_TIMEOUT})",
    )
    return parser


# Виконує діагностичну команду help і показує її необроблену відповідь.
def run(args):
    ports = get_available_ports()
    print_available_ports(ports)

    port = args.port
    if port is None:
        port = find_device_port(ports)

    print(f"Selected port: {port}")
    print(
        f"Connection parameters: {args.baudrate} baud, "
        f"{SERIAL_BYTESIZE} data bits, parity {SERIAL_PARITY}, "
        f"{SERIAL_STOPBITS} stop bit"
    )
    print(f"Timeout: {args.timeout:g} seconds")

    transport = UARTTransport(
        port,
        baudrate=args.baudrate,
        timeout=args.timeout,
    )

    try:
        transport.open()
        command = "help"
        print(f"Sent bytes: {(command + chr(13) + chr(10)).encode()!r}")

        transport.send_line(command)
        raw_response = read_raw_response(transport, args.timeout)
        print(f"Raw response ({len(raw_response)} bytes):")
        print(repr(raw_response))
    finally:
        transport.close()

    return 0


# Перетворює помилки serial і конфігурації на зрозумілий код завершення CLI.
def main():
    parser = build_parser()
    args = parser.parse_args()

    try:
        return run(args)
    except (OSError, RuntimeError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
