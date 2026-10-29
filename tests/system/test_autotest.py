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

AF_XDP and DPDK tests get CPUs for their PMD threads (and for testpmd),
so busy polling threads of parallel tests don't share CPUs, see
tests.system.lib.pmd.  DPDK tests also need their share of the hugepages
of the system, see tests.system.lib.hugepages, and wait for it if needed.

Tests that use physical devices can't run in parallel: DPDK tests with a
PCI device and all the DPDK offload tests.  They are all in one
pytest-xdist group, so with '--dist=loadgroup' they run on one worker, one
after another.  DPDK offload tests also need the representor ports of the
system, so they are not isolated.
"""

import os

import pytest

from tests.lib import env
from tests.lib.autotest import AutotestSuite, matching_tests
from tests.system.lib.features import datapath_config, isolated
from tests.system.lib.hugepages import hugepage_slots
from tests.system.lib.pmd import busy_polling, cpu_slots, pmd_environment
from tests.system.lib import retis

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
_testpmd_tests = {}


# Marker of tests that use a physical device: a test body that looks for
# a PCI device for DPDK (OVS_DPDK_PRE_PHY_SKIP).
_PCI_TEST_MARKER = "system-dpdk-find-device.py"

_SERIAL = [pytest.mark.xdist_group("serial")]

# Marker of tests that need hugepages for testpmd in addition to OVS.
_TESTPMD_TEST_MARKER = "dpdk-testpmd"


def suite(config):
    dp = datapath_config(config)
    if dp not in _suites:
        testsuite = os.path.join(env.srcdir(), "tests",
                                 autotest_suite_name(dp))
        if not isolated(datapath_config(config)):
            marks = _SERIAL
        elif dp.dpdk and os.path.isfile(testsuite):
            pci_tests = matching_tests(testsuite, _PCI_TEST_MARKER)
            _testpmd_tests[dp] = matching_tests(testsuite,
                                                _TESTPMD_TEST_MARKER)

            def marks(number):
                return _SERIAL if number in pci_tests else []
        else:
            marks = []
        _suites[dp] = AutotestSuite(
            testsuite, os.path.join(env.builddir(), "tests"),
            marks=marks, setup=_KEEP_MODULES,
            process_per_test=isolated(datapath_config(config)))
    return _suites[dp]


def pytest_generate_tests(metafunc):
    if "number" in metafunc.fixturenames:
        metafunc.parametrize("number", suite(metafunc.config).params())


@pytest.fixture(scope="session")
def autotest_runner(request):
    yield from suite(request.config).runner(request)


def test_autotest(request, autotest_runner, number):
    dp = datapath_config(request.config)
    if not isolated(datapath_config(request.config)):
        suite(request.config).run(autotest_runner, number)
        return

    request.getfixturevalue("isolated_ns")
    environment = retis.autotest_environment(request.config)
    if not busy_polling(dp):
        suite(request.config).run(autotest_runner, number,
                                  env=environment or None)
        return

    # One CPU (and hugepage slot) for OVS, one more for testpmd.
    n = 2 if number in _testpmd_tests.get(dp, ()) else 1
    slots_dir = os.path.join(env.builddir(), "tests", ".slots")
    held = []
    try:
        # Always in this order, hugepages first, to avoid deadlocks.
        if dp.dpdk:
            held.append(hugepage_slots(
                os.path.join(slots_dir, "hugepages")).acquire(n))
        cpus = cpu_slots(os.path.join(slots_dir, "cpus")).acquire(n)
        held.append(cpus)
        environment.update(pmd_environment(cpus))
        suite(request.config).run(autotest_runner, number, env=environment)
    finally:
        for slots in reversed(held):
            slots.release()
