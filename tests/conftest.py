# Copyright (c) 2026 Red Hat, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at:
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Common pytest configuration for all OVS tests."""

from tests.lib import env, report
from tests.lib.report import (  # noqa: F401
    pytest_runtest_makereport,
    pytest_runtest_teardown,
    test_dir,
)
from tests.system.lib import options as system_options

pytest_plugins = ("pytester",)


def pytest_addoption(parser):
    report.pytest_addoption(parser)
    system_options.add_options(parser)


def pytest_configure(config):
    env.setup()
