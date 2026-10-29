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

"""pytest configuration for OVS system tests.

System tests need root privileges and run with a real datapath selected
with --datapath (and --offload, --tso, --afxdp, --dpdk).  Every test runs
in network and mount namespaces of its own, so tests can run in parallel.

The Autotest system testsuite for the selected configuration runs as well
(tests/system/test_autotest.py), with every test isolated the same way.
"""

import os
import sys

import pytest

from tests.lib import env, report
from tests.lib.modules import KernelModules
from tests.system.lib.dpdk import TestPMD
from tests.system.lib.features import check_requirements, \
    datapath_config, dpdk_offload_check, isolated
from tests.system.lib.hugepages import SLOT_BYTES, hugepage_bytes, \
    hugepage_slots
from tests.system.lib.netns import IsolatedNetNS
from tests.system.lib.ovs import OVSNodeDPDK, OVSNodeSystem, \
    OVSNodeUserspace
from tests.system.lib.pmd import busy_polling, cpu_slots, pmd_environment
from tests.system.lib import retis

# Kernel modules loaded for the whole session: (name, required).
_SYSTEM_MODULES = [
    ("openvswitch", True),
    # Conntrack.  nf_conntrack_ipv[46] are the old names, before 4.18.
    ("nf_conntrack", False),
    ("nf_conntrack_ipv4", False),
    ("nf_conntrack_ipv6", False),
    ("nf_conntrack_netlink", False),
    # Conntrack ALGs and timeout policies.
    ("nf_nat_ftp", False),
    ("nf_nat_tftp", False),
    ("nfnetlink_cttimeout", False),
]

_modules = None


_CAP_NET_ADMIN = 12
_CAP_SYS_ADMIN = 21


def system_tests_possible():
    """Whether the process can create namespaces and configure networking.

    Being root is not enough, e.g., in a container.
    """
    if not sys.platform.startswith("linux"):
        return False
    try:
        with open("/proc/self/status") as f:
            caps = next(int(line.split()[1], 16) for line in f
                        if line.startswith("CapEff:"))
    except (OSError, StopIteration, ValueError):
        return False
    needed = (1 << _CAP_NET_ADMIN) | (1 << _CAP_SYS_ADMIN)
    return caps & needed == needed


def pytest_configure(config):
    dp = datapath_config(config)
    if dp.datapath == "system" and (dp.tso or dp.afxdp or dp.dpdk):
        raise pytest.UsageError("--tso, --afxdp and --dpdk require "
                                "--datapath=userspace")
    if dp.tso and dp.afxdp:
        raise pytest.UsageError("--tso and --afxdp are mutually exclusive")
    error = retis.configure(config)
    if error:
        raise pytest.UsageError(error)

    # DPDK Autotest tests with hardware are in one xdist group and must run
    # on one worker, which requires the 'loadgroup' distribution mode.
    # Workers have no 'numprocesses', so this is only checked in the
    # controller.
    if dp.dpdk and config.getoption("numprocesses", None) \
            and config.getoption("dist", "no") != "loadgroup":
        raise pytest.UsageError(
            "DPDK system tests run in parallel require --dist=loadgroup "
            "(pytest-xdist 2.5 or newer).")


def pytest_sessionstart(session):
    # With pytest-xdist, this runs in the controller before the workers
    # start, and the workers use the loaded modules.
    if hasattr(session.config, "workerinput") or not system_tests_possible():
        return
    if datapath_config(session.config).datapath != "system":
        return
    global _modules
    _modules = KernelModules()
    for name, required in _SYSTEM_MODULES:
        _modules.load(name, required=required)


def pytest_sessionfinish(session, exitstatus):
    global _modules
    if _modules is not None:
        _modules.unload_all()
        _modules = None


def pytest_collection_modifyitems(config, items):
    system_dir = os.path.dirname(__file__)
    if not system_tests_possible():
        skip = pytest.mark.skip(reason="system tests require root "
                                "privileges (CAP_SYS_ADMIN and "
                                "CAP_NET_ADMIN) on Linux")
        for item in items:
            if str(item.fspath).startswith(system_dir):
                item.add_marker(skip)
    elif not isolated(datapath_config(config)):
        # Tests that are not isolated run one at a time.
        for item in items:
            if str(item.fspath).startswith(system_dir):
                item.add_marker(pytest.mark.xdist_group("serial"))


@pytest.fixture
def isolated_ns(request):
    """Run the test in its own network and mount namespaces, if the
    datapath configuration allows it, see ``features.isolated()``.
    """
    if not isolated(datapath_config(request.config)):
        yield None
        return
    with IsolatedNetNS() as ns:
        yield ns


@pytest.fixture
def ovs(request, test_dir, isolated_ns):
    """OVS with the datapath under test and bridge br0.

    Like OVS_TRAFFIC_VSWITCHD_START.  Skips the test if a requirement
    declared with the 'requires' or 'min_kernel' marker is not met.  The
    daemon logs are checked after a successful test, messages allowed in
    them can be listed with the 'log_allow' marker.
    """
    dp = datapath_config(request.config)
    reason = check_requirements(request.node, dp)
    if reason:
        pytest.skip(reason)

    held = []
    if dp.datapath == "system":
        node = OVSNodeSystem(test_dir, offload=dp.offload)
        # Same as CHECK_CONNTRACK, may fail if conntrack is not loaded.
        node.run("sysctl -w net.netfilter.nf_conntrack_helper=0", rc=None,
                 stdout=True, stderr=True)
    else:
        if dp.dpdk and hugepage_bytes() < SLOT_BYTES:
            pytest.skip("not enough hugepages for DPDK")
        if dp.dpdk and dp.offload:
            # All the tests use VFs instead of veths.
            reason = dpdk_offload_check()
            if reason:
                pytest.skip(reason)
        mask = None
        environment = {}
        if busy_polling(dp):
            # CPUs of its own for the PMD threads, and testpmd if the test
            # uses it, see tests.system.lib.pmd.  With DPDK, hugepages too,
            # always taken before CPUs to avoid deadlocks.
            n = 2 if "testpmd" in request.fixturenames else 1
            slots_dir = os.path.join(env.builddir(), "tests", ".slots")
            if dp.dpdk:
                held.append(hugepage_slots(
                    os.path.join(slots_dir, "hugepages")).acquire(n))
            cpus = cpu_slots(os.path.join(slots_dir, "cpus")).acquire(n)
            held.append(cpus)
            environment = pmd_environment(cpus)
            mask = environment["OVS_PMD_CPU_MASK"]
        if dp.dpdk:
            node = OVSNodeDPDK(test_dir, offload=dp.offload,
                               pmd_cpu_mask=mask)
            node.testpmd_eal_options = environment.get(
                "DPDK_EAL_OPTIONS", os.environ.get("DPDK_EAL_OPTIONS", ""))
        else:
            node = OVSNodeUserspace(test_dir, tso=dp.tso, afxdp=dp.afxdp,
                                    pmd_cpu_mask=mask)

    capture = None
    try:
        with node:
            node.add_bridge("br0")
            if dp.datapath == "system" and retis.enabled(request.config):
                capture = retis.Capture(
                    node, test_dir, retis.netns_filter()
                    if retis.parallel(request.config) else None)
            yield node
            marker = request.node.get_closest_marker("log_allow")
            node.stop(check=report.passed(request.node),
                      log_allow=marker.args if marker else ())
    finally:
        if capture is not None:
            capture.stop()
        for slots in reversed(held):
            slots.release()


@pytest.fixture
def testpmd(request, ovs):
    """dpdk-testpmd for DPDK tests, see ``tests.system.lib.dpdk.TestPMD``.

    It is not started, the test starts it with the ports it needs.  The
    'ovs' fixture reserves a CPU and hugepages for it.
    """
    if not isinstance(ovs, OVSNodeDPDK):
        pytest.skip("testpmd requires --dpdk")
    pmd = TestPMD(ovs, ovs.testpmd_eal_options)
    yield pmd
    pmd.stop()
