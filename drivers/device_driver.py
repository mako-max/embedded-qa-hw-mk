#!/usr/bin/env python3

import argparse
import re
import sys
import time

import serial
from serial.tools import list_ports

# Стандартні параметри протоколу пристрою: 115200 baud, 8N1.
DEFAULT_BAUDRATE = 115200
DEFAULT_TIMEOUT = 2
DEFAULT_REBOOT_TIMEOUT = 5
SERIAL_BYTESIZE = serial.EIGHTBITS
SERIAL_PARITY = serial.PARITY_NONE
SERIAL_STOPBITS = serial.STOPBITS_ONE


# Створює serial-з'єднання з єдиною конфігурацією для драйвера та CLI.
def create_serial_connection(
    port,
    *,
    baudrate=DEFAULT_BAUDRATE,
    timeout=DEFAULT_TIMEOUT,
):
    return serial.Serial(
        port=port,
        baudrate=baudrate,
        bytesize=SERIAL_BYTESIZE,
        parity=SERIAL_PARITY,
        stopbits=SERIAL_STOPBITS,
        timeout=timeout,
    )


# Інкапсулює надсилання команд і читання відповідей пристрою через serial-порт.
class DeviceDriver:
    # Зберігає параметри з'єднання; фізично порт відкривається методом open().
    def __init__(
        self,
        port,
        timeout=DEFAULT_TIMEOUT,
        *,
        baudrate=DEFAULT_BAUDRATE,
    ):
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self.serial_connection = None

    # Відкриває порт один раз і очищає дані, що залишилися від попередньої сесії.
    def open(self):
        if self.serial_connection is not None and self.serial_connection.is_open:
            return

        self.serial_connection = create_serial_connection(
            self.port,
            baudrate=self.baudrate,
            timeout=self.timeout,
        )
        self.serial_connection.reset_input_buffer()

    # Закриває порт і скидає посилання, щоб драйвер можна було відкрити повторно.
    def close(self):
        if self.serial_connection is not None:
            self.serial_connection.close()
            self.serial_connection = None

    # Надсилає текстову команду та повертає рядки, отримані протягом timeout.
    def send_command(self, command):
        if self.serial_connection is None or not self.serial_connection.is_open:
            raise RuntimeError("Serial port is not open")

        # Пристрій очікує завершення кожної команди символами CRLF.
        command = command.rstrip("\r\n") + "\r\n"
        self.serial_connection.write(command.encode("utf-8"))
        self.serial_connection.flush()
        time.sleep(0.1)

        return self.read_lines(self.timeout)

    # Збирає непорожні текстові рядки до завершення заданого часу очікування.
    def read_lines(self, timeout):
        if self.serial_connection is None or not self.serial_connection.is_open:
            raise RuntimeError("Serial port is not open")

        lines = []
        end_time = time.time() + timeout
        original_timeout = self.serial_connection.timeout

        try:
            while time.time() < end_time:
                remaining_time = end_time - time.time()
                # Короткий timeout дозволяє регулярно перевіряти загальний дедлайн.
                self.serial_connection.timeout = min(0.1, max(remaining_time, 0))
                raw_line = self.serial_connection.readline()

                if not raw_line:
                    continue

                line = raw_line.decode("utf-8", errors="replace")
                # Видаляємо ANSI-коди кольору, щоб тести працювали з чистим текстом.
                line = re.sub(r"\x1b\[[0-9;]*[mK]", "", line)
                line = line.strip("\r\n")

                if line.strip():
                    lines.append(line)
        finally:
            # Відновлюємо timeout навіть після помилки читання serial-порту.
            self.serial_connection.timeout = original_timeout

        return lines

    # Читає нові рядки, доки не знайде pattern або не завершиться timeout.
    def wait_for(self, pattern, timeout):
        if self.serial_connection is None or not self.serial_connection.is_open:
            raise RuntimeError("Serial port is not open")

        end_time = time.time() + timeout
        original_timeout = self.serial_connection.timeout

        try:
            while time.time() < end_time:
                remaining_time = end_time - time.time()
                # Читаємо короткими інтервалами, але не довше загального timeout.
                self.serial_connection.timeout = min(0.1, max(remaining_time, 0))
                raw_line = self.serial_connection.readline()

                if not raw_line:
                    continue

                line = raw_line.decode("utf-8", errors="replace")
                # Керівні ANSI-послідовності не повинні впливати на пошук pattern.
                line = re.sub(r"\x1b\[[0-9;]*[mK]", "", line)
                line = line.strip("\r\n")

                if pattern in line:
                    return True

            return False
        finally:
            # Повертаємо timeout з'єднання до значення, заданого користувачем.
            self.serial_connection.timeout = original_timeout

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


# Повертає доступні порти у стабільному порядку для відтворюваного вибору.
def get_available_ports():
    return sorted(list_ports.comports(), key=lambda port: port.device)


# Друкує діагностичну інформацію про знайдені serial-порти.
def print_available_ports(ports):
    print(f"Available serial ports: {len(ports)}")

    for port in ports:
        print(port.device)
        print(f"  description: {port.description or 'n/a'}")
        print(f"  hwid: {port.hwid or 'n/a'}")


# Обирає перший USB serial-порт, для якого система визначила VID і PID.
def find_device_port(ports):
    for port in ports:
        if port.vid is not None and port.pid is not None:
            return port.device

    raise RuntimeError("USB serial port was not found")


# Збирає необроблені байти для діагностики без декодування тексту.
def read_raw_response(connection, timeout):
    response = bytearray()
    end_time = time.time() + timeout

    while time.time() < end_time:
        bytes_available = connection.in_waiting

        if bytes_available > 0:
            response.extend(connection.read(bytes_available))
        else:
            time.sleep(0.01)

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
        default=DEFAULT_TIMEOUT,
        help=f"response timeout in seconds (default: {DEFAULT_TIMEOUT})",
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

    # Контекстний менеджер гарантовано закриє порт при успіху або помилці.
    with create_serial_connection(
        port,
        baudrate=args.baudrate,
        timeout=args.timeout,
    ) as connection:
        connection.reset_input_buffer()
        command = b"help\r\n"
        print(f"Sent bytes: {command!r}")

        connection.write(command)
        connection.flush()

        raw_response = read_raw_response(connection, args.timeout)
        print(f"Raw response ({len(raw_response)} bytes):")
        print(repr(raw_response))

    return 0


# Перетворює помилки serial і конфігурації на зрозумілий код завершення CLI.
def main():
    parser = build_parser()
    args = parser.parse_args()

    try:
        return run(args)
    except (serial.SerialException, RuntimeError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
