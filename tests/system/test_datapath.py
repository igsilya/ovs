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

"""Basic datapath tests, migrated from system-traffic.at."""

import os

import pytest

from tests.lib.cmd import run, wait_until
from tests.system.lib.l7 import listening, nc_eof_opt
from tests.system.lib.ping import check_ping


def test_ping_between_two_ports(ovs):
    ovs.ofctl("add-flow br0 actions=normal")

    ns0 = ovs.netns("at_ns0")
    ns1 = ovs.netns("at_ns1")
    ovs.add_veth("p0", ns0, "br0", "10.1.1.1/24")
    ovs.add_veth("p1", ns1, "br0", "10.1.1.2/24")

    for size in (None, 1600, 3200):
        check_ping("10.1.1.2", ns=ns0, size=size)


def test_ping_between_two_ports_on_vlan(ovs):
    ovs.ofctl("add-flow br0 actions=normal")

    ns0 = ovs.netns("at_ns0")
    ns1 = ovs.netns("at_ns1")
    ovs.add_veth("p0", ns0, "br0", "10.1.1.1/24")
    ovs.add_veth("p1", ns1, "br0", "10.1.1.2/24")
    ns0.add_vlan("p0", 100, "10.2.2.1/24")
    ns1.add_vlan("p1", 100, "10.2.2.2/24")

    for size in (None, 1600, 3200):
        check_ping("10.2.2.2", ns=ns0, size=size)


@pytest.mark.requires("vxlan", "nc")
def test_ping_over_vxlan_tunnel(ovs):
    ovs.add_bridge("br-underlay")
    ovs.ofctl("add-flow br0 actions=normal")
    ovs.ofctl("add-flow br-underlay actions=normal")

    ns0 = ovs.netns("at_ns0")

    # Underlay link from the test namespace into ns0.
    ovs.add_veth("p0", ns0, "br-underlay", "172.31.1.1/24")
    run("ip addr add dev br-underlay 172.31.1.100/24")
    run("ip link set dev br-underlay up")

    # Tunnel endpoints: OVS in the test namespace and a native device in
    # ns0.
    ovs.add_ovs_tunnel("vxlan", "br0", "at_vxlan0", "172.31.1.1",
                       "10.1.1.100/24")
    ns0.add_native_tunnel("vxlan", "at_vxlan1", "172.31.1.100",
                          "10.1.1.1/24", type_args="id 0 dstport 4789")

    # Underlay first, then overlay with different packet sizes.
    check_ping("172.31.1.100", ns=ns0)
    for size in (None, 1600, 3200):
        check_ping("10.1.1.100", ns=ns0, size=size)

    ovs.start_background("nc -l 10.1.1.100 1234", stdout="tcp_data")
    ovs.start_background("nc -l -u 10.1.1.1 4321", stdout="udp_data",
                         ns=ns0)
    wait_until(lambda: listening(1234))
    wait_until(lambda: listening(4321, ns=ns0, udp=True))

    # Large TCP transfer.
    payload = os.urandom(60000)
    with open("payload.bin", "wb") as f:
        f.write(payload)
    ns0.exec("nc %s 10.1.1.100 1234 < payload.bin" % nc_eof_opt())
    wait_until(lambda: open("tcp_data", "rb").read() == payload)

    # UDP.
    payload = os.urandom(600)
    with open("payload.bin", "wb") as f:
        f.write(payload)
    run("nc %s -u 10.1.1.1 4321 < payload.bin" % nc_eof_opt())
    wait_until(lambda: open("udp_data", "rb").read() == payload)
