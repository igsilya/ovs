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

"""DPDK offload tests, migrated from system-dpdk-offloads.at.

They need a NIC with at least 6 VFs that have representors, its PCI address
is given in OVS_PF_PCI.
"""

import re

import pytest

from tests.lib.cmd import grep_lines, sort_lines, wait_until_equal
from tests.system.lib.ping import check_ping

pytestmark = pytest.mark.requires("dpdk_offload")


def clean_ip_flows(text):
    """Like DUMP_DP_IP_CLEAN_SORTED."""
    text = grep_lines("eth_type(0x0800)")(text)
    text = re.sub(r"eth\(src=[a-z0-9:]*,dst=[a-z0-9:]*\)", "eth(macs)", text)
    text = text.replace("recirc_id(0),", "")
    text = re.sub(r"used:[0-9]+\.[0-9]*", "used:0.0", text)
    text = re.sub(r"packet_type\(ns=[0-9]*,id=[0-9]*\),", "", text)
    return sort_lines(text)


def test_ping_between_two_hardware_offloaded_ports(ovs):
    ovs.ofctl("add-flow br0 actions=normal")

    ns0 = ovs.netns("at_ns0")
    ns1 = ovs.netns("at_ns1")
    ovs.add_vf("p0", ns0, "br0", "10.1.1.1/24")
    ovs.add_vf("p1", ns1, "br0", "10.1.1.2/24")

    check_ping("10.1.1.2", ns=ns0)

    wait_until_equal(
        "ovs-appctl dpctl/dump-flows --names type=dpdk,offloaded", [
            "in_port(ovs-p0),eth(macs),eth_type(0x0800),ipv4(frag=no), packets:2, bytes:196, used:0.0s, actions:ovs-p1",  # noqa: E501
            "in_port(ovs-p1),eth(macs),eth_type(0x0800),ipv4(frag=no), packets:2, bytes:196, used:0.0s, actions:ovs-p0",  # noqa: E501
        ], filters=clean_ip_flows)
