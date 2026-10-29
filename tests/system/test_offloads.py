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

"""TC offload tests, migrated from system-offloads-traffic.at."""

import pytest

from tests.system.lib.flows import dump_dp_flows
from tests.system.lib.ping import check_ping

pytestmark = pytest.mark.requires("tc_offload")


def ipv4_flows(ovs, args=""):
    """Return (in_port, packets, bytes) of the IPv4 datapath flows."""
    return sorted((f.match["in_port"], f.info["packets"], f.info["bytes"])
                  for f in dump_dp_flows(ovs, args)
                  if f.match.get("eth_type") == 0x0800)


def test_ping_between_two_ports_offloads_enabled(ovs):
    ovs.ofctl("add-flow br0 actions=normal")

    ns0 = ovs.netns("at_ns0")
    ns1 = ovs.netns("at_ns1")
    ovs.add_veth("p0", ns0, "br0", "10.1.1.1/24")
    ovs.add_veth("p1", ns1, "br0", "10.1.1.2/24")

    check_ping("10.1.1.2", ns=ns0, count=10, interval=0.1)

    # The first packet in each direction goes to userspace, the rest are
    # handled by the flows offloaded to TC.
    expected = [(2, 9, 756), (3, 9, 756)]
    assert ipv4_flows(ovs) == expected
    assert ipv4_flows(ovs, "type=ovs") == []
    assert ipv4_flows(ovs, "type=tc,offloaded") == expected

    upcalls = ovs.appctl("upcall/show", stdout=True).stdout
    assert any(line.strip().startswith("offloaded flows :")
               and int(line.split(":")[1].split()[0]) > 0
               for line in upcalls.splitlines()), upcalls
