#!/usr/bin/env python3

import pytest

from drivers.device_driver import AlarmOperation, AlarmState
from tests.constants import (
    ALARM_INHIBIT_OBSERVATION_TIME,
    ALARM_STATE_TIMEOUT,
    CALIBRATION_INHIBIT_OBSERVATION_TIME,
    DEFAULT_ALARM_THRESHOLD,
)

pytestmark = pytest.mark.functional


# Значення навколо порога окремо фіксують головну boundary-умову PRD: `>=`.
@pytest.mark.parametrize(
    ("sensor_value", "expected_state"),
    [
        pytest.param(79, AlarmState.ARMED, id="below-threshold"),
        pytest.param(80, AlarmState.TRIGGERED, id="at-threshold"),
        pytest.param(81, AlarmState.TRIGGERED, id="above-threshold"),
    ],
)
def test_alarm_triggers_at_or_above_threshold(
    alarm_device,
    sensor_value,
    expected_state,
):
    assert alarm_device.set_sensor_value(sensor_value), (
        f"Cannot set sensor value to {sensor_value}"
    )
    assert alarm_device.arm_alarm(), "Cannot arm alarm"

    status = alarm_device.wait_for_alarm_state(expected_state, ALARM_STATE_TIMEOUT)

    assert status is not None, f"Alarm did not reach {expected_state}"
    assert status.threshold == DEFAULT_ALARM_THRESHOLD
    assert status.sensor_running is True


@pytest.mark.parametrize(
    ("initial_state", "sensor_value", "expected_result", "expected_final_state"),
    [
        pytest.param(
            AlarmState.DISARMED,
            None,
            False,
            AlarmState.DISARMED,
            id="clear-disarmed-is-rejected",
        ),
        pytest.param(
            AlarmState.ARMED,
            79,
            False,
            AlarmState.ARMED,
            id="clear-armed-is-rejected",
        ),
        pytest.param(
            AlarmState.TRIGGERED,
            80,
            True,
            AlarmState.CLEARED,
            id="clear-triggered-is-accepted",
        ),
    ],
)
def test_alarm_clear_follows_state_machine(
    alarm_device,
    initial_state,
    sensor_value,
    expected_result,
    expected_final_state,
):
    # None залишає базовий DISARMED зі фікстури; число готує ARMED/TRIGGERED
    # через реальну state machine, а не штучне присвоєння внутрішнього стану.
    if sensor_value is not None:
        assert alarm_device.set_sensor_value(sensor_value)
        assert alarm_device.arm_alarm()
        assert (
            alarm_device.wait_for_alarm_state(initial_state, ALARM_STATE_TIMEOUT)
            is not None
        )

    assert alarm_device.clear_alarm() is expected_result

    status = alarm_device.get_alarm_status()
    assert status.state is expected_final_state


@pytest.mark.parametrize(
    ("sensor_value", "initial_state"),
    [
        pytest.param(79, AlarmState.ARMED, id="disarm-from-armed"),
        pytest.param(80, AlarmState.TRIGGERED, id="disarm-from-triggered"),
    ],
)
def test_alarm_disarm_transitions_to_disarmed(
    alarm_device,
    sensor_value,
    initial_state,
):
    assert alarm_device.set_sensor_value(sensor_value)
    assert alarm_device.arm_alarm()
    assert (
        alarm_device.wait_for_alarm_state(initial_state, ALARM_STATE_TIMEOUT)
        is not None
    )

    assert alarm_device.disarm_alarm()

    status = alarm_device.wait_for_alarm_state(
        AlarmState.DISARMED,
        ALARM_STATE_TIMEOUT,
    )
    assert status is not None


def test_cleared_alarm_can_be_rearmed(alarm_device):
    assert alarm_device.set_sensor_value(DEFAULT_ALARM_THRESHOLD)
    assert alarm_device.arm_alarm()
    assert (
        alarm_device.wait_for_alarm_state(
            AlarmState.TRIGGERED,
            ALARM_STATE_TIMEOUT,
        )
        is not None
    )
    assert alarm_device.clear_alarm()

    # Перед повторним arm знижуємо value, інакше CLEARED майже одразу знову
    # стане TRIGGERED та перехід CLEARED -> ARMED неможливо буде спостерігати.
    assert alarm_device.set_sensor_value(DEFAULT_ALARM_THRESHOLD - 1)
    assert alarm_device.arm_alarm()

    status = alarm_device.wait_for_alarm_state(
        AlarmState.ARMED,
        ALARM_STATE_TIMEOUT,
    )
    assert status is not None


def test_sensor_stop_suspends_alarm_monitoring(alarm_device):
    assert alarm_device.set_sensor_value(DEFAULT_ALARM_THRESHOLD + 1)
    assert alarm_device.stop_sensor()
    assert alarm_device.arm_alarm()

    # Негативну асинхронну умову перевіряємо протягом кількох циклів alarm task:
    # одноразовий ARMED ще не доводить, що відкладене спрацювання не відбудеться.
    assert alarm_device.alarm_state_remains(
        AlarmState.ARMED,
        ALARM_INHIBIT_OBSERVATION_TIME,
    ), "Alarm triggered while sensor was stopped"

    stopped_status = alarm_device.get_alarm_status()
    assert stopped_status.sensor_running is False

    assert alarm_device.start_sensor()
    # За PRD sensor start скидає manual override, тому небезпечне value задаємо знову.
    assert alarm_device.set_sensor_value(DEFAULT_ALARM_THRESHOLD + 1)

    resumed_status = alarm_device.wait_for_alarm_state(
        AlarmState.TRIGGERED,
        ALARM_STATE_TIMEOUT,
    )
    assert resumed_status is not None, "Alarm did not resume after sensor start"


def test_calibration_job_suspends_alarm_until_cancelled(alarm_device):
    assert alarm_device.set_sensor_value(DEFAULT_ALARM_THRESHOLD - 1)
    assert alarm_device.arm_alarm()
    assert (
        alarm_device.wait_for_alarm_state(
            AlarmState.ARMED,
            ALARM_STATE_TIMEOUT,
        )
        is not None
    )

    job_id = alarm_device.add_calibration_job()
    assert job_id is not None, "Calibration job did not activate alarm inhibit"

    try:
        # Значення піднімаємо лише після marker `Alarm inhibit: ACTIVE`, який
        # add_calibration_job() очікує всередині драйвера для усунення race condition.
        assert alarm_device.set_sensor_value(DEFAULT_ALARM_THRESHOLD + 1)
        assert alarm_device.alarm_state_remains(
            AlarmState.ARMED,
            CALIBRATION_INHIBIT_OBSERVATION_TIME,
        ), "Alarm triggered while calibration inhibit was active"

        assert alarm_device.cancel_calibration_job(job_id), (
            "Calibration job was not cancelled or inhibit was not released"
        )
        job_id = None

        resumed_status = alarm_device.wait_for_alarm_state(
            AlarmState.TRIGGERED,
            ALARM_STATE_TIMEOUT,
        )
        assert resumed_status is not None, (
            "Alarm did not resume after calibration job cancellation"
        )
    finally:
        # Раннє падіння не повинно залишити inhibit/job для наступного hardware-кейсу.
        # Після успішного cancel змінна стає None, тому повторна команда не надсилається.
        if job_id is not None:
            alarm_device.cancel_calibration_job(job_id)


@pytest.mark.parametrize(
    "operation",
    [
        pytest.param(AlarmOperation.ARM, id="arm-requires-auth"),
        pytest.param(AlarmOperation.DISARM, id="disarm-requires-auth"),
        pytest.param(AlarmOperation.CLEAR, id="clear-requires-auth"),
        pytest.param(AlarmOperation.STATUS, id="status-requires-auth"),
    ],
)
def test_alarm_commands_require_authorization(
    unauthenticated_device,
    operation,
):
    # Фікстура отримує AUTH_NONE через logout, а не через невдалий login,
    # тому ця матриця не змінює лічильник rate limit.
    assert unauthenticated_device.is_alarm_operation_access_denied(operation), (
        f"{operation.value!r} was not rejected for AUTH_NONE"
    )
