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

"""Conntrack tests, migrated from system-traffic.at."""

import pytest

from tests.system.lib.conntrack import dump_conntrack, flush_conntrack
from tests.system.lib.l7 import http_get, start_l7
from tests.system.lib.ping import check_ping

pytestmark = pytest.mark.requires("conntrack")


def test_ipv4_ping(ovs):
    ns0 = ovs.netns("at_ns0")
    ns1 = ovs.netns("at_ns1")
    ovs.add_veth("p0", ns0, "br0", "10.1.1.1/24")
    ovs.add_veth("p1", ns1, "br0", "10.1.1.2/24")

    # Allow any traffic from ns0->ns1, only allow ARP and return traffic
    # from ns1->ns0.
    ovs.add_flows("br0", """
        priority=1,action=drop
        priority=10,arp,action=normal
        priority=100,in_port=1,icmp,action=ct(commit),2
        priority=100,in_port=2,icmp,ct_state=-trk,action=ct(table=0)
        priority=100,in_port=2,icmp,ct_state=+trk+est,action=1
    """, args="--bundle")

    # Pings from ns0->ns1 work and create a single ICMP connection.
    check_ping("10.1.1.2", ns=ns0)
    entries = dump_conntrack(ip="10.1.1.2")
    assert len(entries) == 1
    ct = entries[0]
    assert ct.proto == "icmp"
    assert (ct.orig["src"], ct.orig["type"]) == ("10.1.1.1", "8")
    assert (ct.reply["src"], ct.reply["dst"], ct.reply["type"]) \
        == ("10.1.1.2", "10.1.1.1", "0")

    flush_conntrack(args="'ct_nw_src=10.1.1.1,ct_nw_dst=10.1.1.2'")
    assert dump_conntrack(ip="10.1.1.2") == []

    # Pings from ns1->ns0 fail.
    check_ping("10.1.1.1", ns=ns1, expect_loss=True)


def test_multiple_bridges(ovs):
    ovs.add_bridge("br1",
                   "add-port br0 patch+ -- set int patch+ type=patch "
                   "options:peer=patch-",
                   "add-port br1 patch- -- set int patch- type=patch "
                   "options:peer=patch+")

    ns0 = ovs.netns("at_ns0")
    ns1 = ovs.netns("at_ns1")
    ovs.add_veth("p0", ns0, "br0", "10.1.1.1/24")
    ovs.add_veth("p1", ns1, "br1", "10.1.1.2/24")

    # Allow any traffic from ns0->br1, allow established in reverse.
    ovs.add_flows("br0", """
        priority=1,action=drop
        priority=10,arp,action=normal
        priority=10,icmp,action=normal
        priority=100,in_port=2,tcp,ct_state=-trk,action=ct(commit,zone=1),1
        priority=100,in_port=1,tcp,ct_state=-trk,action=ct(table=0,zone=1)
        priority=100,in_port=1,tcp,ct_state=+trk+est,ct_zone=1,action=2
    """, args="--bundle")
    # Allow any traffic from br0->ns1, allow established in reverse.
    ovs.add_flows("br1", """
        priority=1,action=drop
        priority=10,arp,action=normal
        priority=10,icmp,action=normal
        priority=100,in_port=1,tcp,ct_state=-trk,action=ct(table=0,zone=2)
        priority=100,in_port=1,tcp,ct_state=+trk+new,ct_zone=2,action=ct(commit,zone=2),2
        priority=100,in_port=1,tcp,ct_state=+trk+est,ct_zone=2,action=2
        priority=100,in_port=2,tcp,ct_state=-trk,action=ct(table=0,zone=2)
        priority=100,in_port=2,tcp,ct_state=+trk+est,ct_zone=2,action=ct(commit,zone=2),1
    """, args="--bundle")  # noqa: E501

    # HTTP requests from p0->p1 work.
    start_l7(ovs, ns1, "http")
    http_get("10.1.1.2", ns=ns0)
