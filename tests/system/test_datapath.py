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
