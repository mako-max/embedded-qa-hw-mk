# Embedded QA Hardware Tests

## Install

python -m venv .venv
source .venv/bin/activate
python -m pip install pytest pyserial

## Run all tests

pytest -vv -s

## Run sensor history test

pytest -vv -s tests/functional/test_bugs.py::test_sensor_history_bug_is_reproduced

## Run rate-limit test

pytest -vv -s tests/functional/test_bugs.py::test_login_rate_limit
