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

"""Tests for the parts of tests.system.lib that don't need root."""

import os
import types

import pytest

from tests.system.lib import features, retis
from tests.system.lib.conntrack import ConntrackEntry, format_ct
from tests.system.lib.features import DatapathConfig, check_requirements
from tests.system.lib.ping import PingResult, parse_ping

KERNEL = DatapathConfig("system", False, False, False, False)
OFFLOAD = DatapathConfig("system", True, False, False, False)
USERSPACE = DatapathConfig("userspace", False, False, False, False)


class TestPing:
    def test_parse(self):
        assert parse_ping(
            "PING 10.1.1.2 (10.1.1.2) 56(84) bytes of data.\n\n"
            "--- 10.1.1.2 ping statistics ---\n"
            "3 packets transmitted, 3 received, 0% packet loss, time 405ms\n"
            "rtt min/avg/max/mdev = 0.04/0.05/0.08/0.01 ms\n") \
            == PingResult(3, 3)
        assert parse_ping("7 packets transmitted, 0 received, "
                          "100% packet loss, time 2050ms\n") \
            == PingResult(7, 0)
        # BusyBox and FreeBSD style.
        assert parse_ping("3 packets transmitted, 2 packets received, "
                          "33.3% packet loss\n") == PingResult(3, 2)

    def test_parse_error(self):
        with pytest.raises(ValueError):
            parse_ping("ping: connect: Network is unreachable\n")


DUMP = """\
icmp,orig=(src=10.1.1.1,dst=10.1.1.2,id=4321,type=8,code=0),\
reply=(src=10.1.1.2,dst=10.1.1.1,id=4321,type=0,code=0),zone=1
tcp,orig=(src=10.1.1.1,dst=10.1.1.2,sport=45678,dport=80),\
reply=(src=10.1.1.2,dst=10.1.1.1,sport=80,dport=45678),zone=1,mark=0x10,\
labels=0x200000001,protoinfo=(state=TIME_WAIT)
udp,orig=(src=10.1.1.2,dst=10.1.1.20,sport=1,dport=2),\
reply=(src=10.1.1.20,dst=10.1.1.2,sport=2,dport=1)
"""


class TestConntrack:
    def test_entry(self):
        icmp, tcp, udp = [ConntrackEntry(line)
                          for line in DUMP.splitlines()]
        assert icmp.proto == "icmp"
        assert icmp.orig == {"src": "10.1.1.1", "dst": "10.1.1.2",
                             "id": "4321", "type": "8", "code": "0"}
        assert icmp.reply["src"] == "10.1.1.2"
        assert icmp.zone == 1 and icmp.mark == 0 and icmp.state is None
        assert tcp.orig["dport"] == "80"
        assert tcp.mark == 0x10
        assert tcp.labels == 0x200000001
        assert tcp.state == "TIME_WAIT"
        assert udp.zone == 0

    def test_format_ct(self):
        # Same as FORMAT_CT(10.1.1.2): 'dst=10.1.1.2' is a substring match.
        assert format_ct(DUMP, "10.1.1.2") == [
            "icmp,orig=(src=10.1.1.1,dst=10.1.1.2,id=<cleared>,type=8,"
            "code=0),reply=(src=10.1.1.2,dst=10.1.1.1,id=<cleared>,type=0,"
            "code=0),zone=1",
            "tcp,orig=(src=10.1.1.1,dst=10.1.1.2,sport=<cleared>,"
            "dport=<cleared>),reply=(src=10.1.1.2,dst=10.1.1.1,"
            "sport=<cleared>,dport=<cleared>),zone=1,mark=0x10,"
            "labels=0x200000001,protoinfo=(state=<cleared>)",
            "udp,orig=(src=10.1.1.2,dst=10.1.1.20,sport=<cleared>,"
            "dport=<cleared>),reply=(src=10.1.1.20,dst=10.1.1.2,"
            "sport=<cleared>,dport=<cleared>)",
        ]
        assert format_ct(DUMP, "192.168.0.1") == []


class FakeItem:
    def __init__(self, **markers):
        self.markers = markers

    def iter_markers(self, name):
        if name in self.markers:
            yield types.SimpleNamespace(args=self.markers[name])


class TestFeatures:
    def test_datapath_specific(self):
        item = FakeItem(requires=("conntrack_local_stack",))
        assert check_requirements(item, KERNEL) is None
        assert "userspace" in check_requirements(item, USERSPACE)

        item = FakeItem(requires=("conntrack", "conntrack_alg"))
        assert check_requirements(item, KERNEL) is None
        assert check_requirements(item, USERSPACE) is None
        assert "ALG" in check_requirements(item, OFFLOAD)

        item = FakeItem(requires=("ct_dpif_maxconns",))
        assert check_requirements(item, KERNEL)
        assert check_requirements(item, USERSPACE) is None

    def test_unknown(self):
        with pytest.raises(ValueError):
            check_requirements(FakeItem(requires=("no-such-thing",)), KERNEL)

    def test_min_kernel(self, monkeypatch):
        monkeypatch.setattr(features, "kernel_version", lambda: (5, 14))
        assert check_requirements(FakeItem(min_kernel=(5, 14)),
                                  KERNEL) is None
        assert check_requirements(FakeItem(min_kernel=(4, 20)),
                                  KERNEL) is None
        assert "5.19" in check_requirements(FakeItem(min_kernel=(5, 19)),
                                            KERNEL)
        assert check_requirements(FakeItem(min_kernel=(3, 10)), USERSPACE)

    def test_no_markers(self):
        assert check_requirements(FakeItem(), KERNEL) is None


def test_testsuite_names():
    from tests.system.test_autotest import autotest_suite_name

    def dp(datapath, **kwargs):
        args = dict(offload=False, tso=False, afxdp=False, dpdk=False)
        args.update(kwargs)
        return DatapathConfig(datapath, **args)

    assert autotest_suite_name(dp("system")) == "system-kmod-testsuite"
    assert autotest_suite_name(dp("system", offload=True)) \
        == "system-offloads-testsuite"
    assert autotest_suite_name(dp("userspace")) == "system-userspace-testsuite"
    assert autotest_suite_name(dp("userspace", tso=True)) \
        == "system-tso-testsuite"
    assert autotest_suite_name(dp("userspace", afxdp=True)) \
        == "system-afxdp-testsuite"
    assert autotest_suite_name(dp("userspace", dpdk=True)) \
        == "system-dpdk-testsuite"
    assert autotest_suite_name(dp("userspace", dpdk=True, offload=True)) \
        == "system-dpdk-offloads-testsuite"


class TestHugepages:
    def test_slot_count(self, tmp_path, monkeypatch):
        from tests.system.lib import hugepages

        monkeypatch.setattr(hugepages, "hugepage_bytes", lambda: 0)
        assert hugepages.hugepage_slots(str(tmp_path)).count == 1
        monkeypatch.setattr(hugepages, "hugepage_bytes",
                            lambda: 5 * hugepages.SLOT_BYTES + 1)
        assert hugepages.hugepage_slots(str(tmp_path)).count == 5


class TestPMD:
    def slots(self, *numbers):
        return types.SimpleNamespace(numbers=list(numbers))

    def test_pmd_only(self, monkeypatch):
        from tests.system.lib import pmd

        monkeypatch.setattr(pmd, "available_cpus", lambda: [0, 2, 4, 6])
        # The first CPU is not used for polling.
        assert pmd.polling_cpus() == [2, 4, 6]
        assert pmd.pmd_environment(self.slots(0), base={}) \
            == {"OVS_PMD_CPU_MASK": "0x4"}
        monkeypatch.setattr(pmd, "available_cpus", lambda: [3])
        assert pmd.pmd_environment(self.slots(0), base={}) \
            == {"OVS_PMD_CPU_MASK": "0x8"}

    def test_testpmd(self, monkeypatch):
        from tests.system.lib import pmd

        monkeypatch.setattr(pmd, "available_cpus", lambda: [0, 2, 4, 6])
        base = {"DPDK_EAL_OPTIONS": "--lcores 0@1,1@1,2@1 --no-telemetry"}
        assert pmd.pmd_environment(self.slots(0, 2), base=base) == {
            "OVS_PMD_CPU_MASK": "0x4",
            "DPDK_EAL_OPTIONS": "--no-telemetry --lcores 0@6,1@6,2@6",
        }
        assert pmd.pmd_environment(self.slots(1, 0), base={}) == {
            "OVS_PMD_CPU_MASK": "0x10",
            "DPDK_EAL_OPTIONS": "--lcores 0@2,1@2,2@2",
        }

    def test_busy_polling(self):
        from tests.system.lib.pmd import busy_polling

        assert not busy_polling(KERNEL)
        assert not busy_polling(USERSPACE)
        assert not busy_polling(DatapathConfig("userspace", False, True,
                                               False, False))
        assert busy_polling(DatapathConfig("userspace", False, False,
                                           True, False))
        assert busy_polling(DatapathConfig("userspace", False, False,
                                           False, True))

    def test_cpu_slots(self, tmp_path):
        from tests.system.lib.pmd import cpu_slots, polling_cpus

        assert cpu_slots(str(tmp_path)).count == len(polling_cpus())


class FakeRetisConfig:
    def __init__(self, retis=False):
        self.options = {"retis": retis}

    def getoption(self, name, default=None):
        return self.options.get(name, default)


def test_retis_environment(monkeypatch):
    monkeypatch.delenv("OVS_TEST_WITH_RETIS", raising=False)
    monkeypatch.delenv("PYTEST_XDIST_WORKER_COUNT", raising=False)
    assert not retis.enabled(FakeRetisConfig())
    assert retis.autotest_environment(FakeRetisConfig(retis=True)) == {}

    ino = os.stat("/proc/self/ns/net").st_ino
    expected = "sk_buff.dev.nd_net.net.ns.inum == %d" % ino
    assert retis.netns_filter() == expected
    config = FakeRetisConfig(retis=True)
    monkeypatch.setenv("PYTEST_XDIST_WORKER_COUNT", "1")
    assert retis.autotest_environment(config) == {}
    monkeypatch.setenv("PYTEST_XDIST_WORKER_COUNT", "4")
    assert retis.autotest_environment(config) \
        == {"OVS_TEST_RETIS_FILTER": expected}

    # Same as 'make check-kernel OVS_TEST_WITH_RETIS=yes'.
    monkeypatch.setenv("OVS_TEST_WITH_RETIS", "yes")
    assert retis.enabled(FakeRetisConfig())
