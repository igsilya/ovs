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

"""Userspace TSO tests, migrated from system-tap.at."""

import pytest

from tests.lib.cmd import run
from tests.system.lib.l7 import http_get, start_l7
from tests.system.lib.ping import check_ping

pytestmark = pytest.mark.requires("tso")


@pytest.mark.log_allow(r".*ethtool command ETHTOOL_G.*")
def test_traffic_between_namespaces_using_tap(ovs):
    ovs.ofctl("add-flow br0 actions=normal")

    ns0 = ovs.netns("at_ns0")
    ns1 = ovs.netns("at_ns1")
    for tap, ns, ip in (("tap0", ns0, "10.1.1.1/24"),
                        ("tap1", ns1, "10.1.1.2/24")):
        run("ip tuntap add %s mode tap" % tap)
        ovs.vsctl("add-port br0 %s -- set int %s type=tap" % (tap, tap))
        run("ip link set %s netns %s" % (tap, ns))
        run("ip link set dev %s up" % tap, ns=ns)
        run("ip addr add %s dev %s" % (ip, tap), ns=ns)

    check_ping("10.1.1.2", ns=ns0)

    start_l7(ovs, ns1, "http")
    http_get("10.1.1.2", ns=ns0)
