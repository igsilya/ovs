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

"""The Autotest system testsuite for the datapath under test.

The testsuite is selected by the datapath options, e.g., --datapath=system
runs tests/system-kmod-testsuite.

The Autotest tests are written to run in the network namespace of the
system, with fixed names for network namespaces and devices.  To be able
to run them in parallel, every test runs in network and mount namespaces
of its own, the same way pytest-based system tests do: the test enters
the namespaces and starts the testsuite to run this one test from there.

Autotest tests load and unload kernel modules, which would disturb other
tests running at the same time, so 'modprobe -r' is turned into a no-op
for them.  The modules are loaded once for the whole session instead.

DPDK tests use hugepages and physical devices, so they are not isolated.
They are all in one pytest-xdist group instead, so with '--dist=loadgroup'
they run on one worker, one after another.
"""

import os

import pytest

from tests.lib import env
from tests.lib.autotest import AutotestSuite
from tests.system.lib.features import datapath_config

# Ignore 'modprobe -r' in tests, the modules are managed by the session.
_KEEP_MODULES = r"""
  modprobe () {
    case " $* " in
      *" -r "*) echo "modprobe $*: ignored by pytest" ;;
      *) command modprobe "$@" ;;
    esac
  }
"""


def autotest_suite_name(dp):
    """Return the name of the Autotest testsuite for ``DatapathConfig``."""
    if dp.datapath == "system":
        return "system-offloads-testsuite" if dp.offload \
            else "system-kmod-testsuite"
    if dp.dpdk:
        return "system-dpdk-offloads-testsuite" if dp.offload \
            else "system-dpdk-testsuite"
    if dp.tso:
        return "system-tso-testsuite"
    if dp.afxdp:
        return "system-afxdp-testsuite"
    return "system-userspace-testsuite"


_suites = {}


def isolated(config):
    """Whether Autotest tests run in isolated namespaces."""
    return not datapath_config(config).dpdk


def suite(config):
    dp = datapath_config(config)
    if dp not in _suites:
        if isolated(config):
            marks, per_test = [], True
        else:
            marks, per_test = [pytest.mark.xdist_group("autotest")], False
        _suites[dp] = AutotestSuite(
            os.path.join(env.srcdir(), "tests", autotest_suite_name(dp)),
            os.path.join(env.builddir(), "tests"),
            marks=marks, setup=_KEEP_MODULES, process_per_test=per_test)
    return _suites[dp]


def pytest_generate_tests(metafunc):
    if "number" in metafunc.fixturenames:
        metafunc.parametrize("number", suite(metafunc.config).params())


@pytest.fixture(scope="session")
def autotest_runner(request):
    yield from suite(request.config).runner(request)


def test_autotest(request, autotest_runner, number):
    if isolated(request.config):
        request.getfixturevalue("isolated_ns")
    suite(request.config).run(autotest_runner, number)
