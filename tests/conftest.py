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

import glob
import os

import pytest

from tests.lib import env, report, tools
from tests.lib.debug import pytest_exception_interact  # noqa: F401
from tests.lib.report import (  # noqa: F401
    pytest_runtest_makereport,
    pytest_runtest_teardown,
    test_dir,
)
from tests.system.lib import options as system_options

pytest_plugins = ("pytester",)


def pytest_addoption(parser):
    report.pytest_addoption(parser)
    tools.pytest_addoption(parser)
    system_options.add_options(parser)


def pytest_configure(config):
    error = tools.configure(config)
    if error:
        raise pytest.UsageError(error)
    env.setup()


def pytest_terminal_summary(terminalreporter, config):
    tool = tools.selected(config)
    if tool is None:
        return
    # Native tests write the outputs into their directories under the base
    # temporary directory, Autotest tests into the test directories of the
    # testsuites.
    dirs = glob.glob(os.path.join(env.builddir(), "tests", "*.dir"))
    if config.option.basetemp:
        dirs.append(os.path.abspath(config.option.basetemp))
    reports = tools.reports(sorted(set(dirs)), tool)
    terminalreporter.section(tool)
    if reports:
        terminalreporter.write_line("%d %s output(s) with errors:"
                                    % (len(reports), tool))
        for path in reports:
            terminalreporter.write_line("  " + path)
    else:
        terminalreporter.write_line("No errors reported by %s." % tool)
