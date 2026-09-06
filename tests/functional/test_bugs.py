#!/usr/bin/env python3

import pytest

from drivers.device_driver import AlarmState, JobState
from tests.constants import (
    ALARM_STATE_TIMEOUT,
    CANCELLED_JOB_OBSERVATION_TIME,
    DEFAULT_ALARM_THRESHOLD,
    DEFAULT_SENSOR_INTERVAL,
    EXPECTED_HISTORY_COUNT,
    FAILED_LOGIN_ATTEMPTS,
    SENSOR_COLLECTION_TIME,
    TEST_LOGIN,
    TEST_PASSWORD,
    WRONG_PASSWORD,
)

pytestmark = pytest.mark.functional

# У pytest.ini ввімкнено xfail_strict: після виправлення FW неочікуваний XPASS
# навмисно зламає suite, щоб застарілу xfail-мітку не залишили назавжди.


@pytest.mark.slow
@pytest.mark.xfail(
    reason="Дефект FW: sensor history зберігає менше 10 показань із PRD",
)
def test_sensor_history_keeps_last_ten_readings(device):
    # Це навмисно довгий hardware-тест: 10 записів формує реальна FreeRTOS-задача
    # з інтервалом 3000 мс, без підміни часу або прискорення прошивки.
    assert device.set_sensor_mode_temperature()
    assert device.set_sensor_interval(DEFAULT_SENSOR_INTERVAL)
    assert device.collect_sensor_readings(SENSOR_COLLECTION_TIME)

    assert device.get_sensor_history_count() == EXPECTED_HISTORY_COUNT


# Поля винесено в окремі параметризовані кейси: strict XPASS тоді точно покаже,
# який із двох незалежних дефектів alarm status уже виправлено у прошивці.
@pytest.mark.parametrize(
    ("status_attribute", "expected_value"),
    [
        pytest.param(
            "last_value",
            float(DEFAULT_ALARM_THRESHOLD),
            marks=pytest.mark.xfail(
                reason="Дефект FW: alarm status показує Last value 0 після trigger"
            ),
            id="trigger-value-is-stale",
        ),
        pytest.param(
            "led_on",
            True,
            marks=pytest.mark.xfail(
                reason="Дефект FW: alarm status показує LED OFF після примусового ON"
            ),
            id="trigger-led-state-is-stale",
        ),
    ],
)
def test_triggered_alarm_status_matches_runtime_state(
    alarm_device,
    status_attribute,
    expected_value,
):
    assert alarm_device.set_sensor_value(DEFAULT_ALARM_THRESHOLD)
    assert alarm_device.arm_alarm()

    status = alarm_device.wait_for_alarm_state(
        AlarmState.TRIGGERED,
        ALARM_STATE_TIMEOUT,
    )

    assert status is not None
    assert getattr(status, status_attribute) == expected_value


@pytest.mark.slow
@pytest.mark.xfail(
    reason="Дефект FW: скасована calibration продовжується і записує стан DONE",
)
def test_cancelled_calibration_job_remains_cancelled(alarm_device):
    job_id = alarm_device.add_calibration_job()
    assert job_id is not None
    cancel_confirmed = False

    try:
        assert alarm_device.cancel_calibration_job(job_id)
        cancel_confirmed = True
        # Спочатку підтверджуємо коректний миттєвий CANCELLED, а потім тримаємо
        # observation window: відомий дефект проявляється відкладеним записом DONE.
        assert (
            alarm_device.wait_for_calibration_job_state(
                job_id,
                JobState.CANCELLED,
                ALARM_STATE_TIMEOUT,
            )
            is not None
        )
        assert alarm_device.calibration_job_state_remains(
            job_id,
            JobState.CANCELLED,
            CANCELLED_JOB_OBSERVATION_TIME,
        )
    finally:
        if not cancel_confirmed:
            alarm_device.cancel_calibration_job(job_id)


def test_login_rate_limit(rate_limit_device):
    for attempt in range(1, FAILED_LOGIN_ATTEMPTS + 1):
        result = rate_limit_device.login_attempt(TEST_LOGIN, WRONG_PASSWORD)
        assert not result.has_active_session, (
            f"Session unexpectedly started on failed attempt {attempt}"
        )

    # Правильний пароль відрізняє справжній lockout від звичайної відмови через
    # неправильні credentials; cleanup-фікстура потім чекає реальні 30 секунд.
    result = rate_limit_device.login_attempt(TEST_LOGIN, TEST_PASSWORD)

    assert result.account_locked, (
        "Account was not locked after three failed login attempts"
    )
    assert not result.has_active_session, "Session started while the account was locked"
