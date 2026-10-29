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

"""ofproto-dpif tests, migrated from ofproto-dpif.at."""


def trace(ovs, bridge, flow):
    """Return the datapath actions of 'ovs-appctl ofproto/trace'."""
    out = ovs.appctl("ofproto/trace %s '%s'" % (bridge, flow),
                     stdout=True).stdout
    return out.rstrip("\n").splitlines()[-1]


def test_resubmit(ovs):
    ovs.add_of_ports("br0", 1, *range(10, 22))
    ovs.add_flows("br0", """
        table=0 in_port=1 priority=1000 icmp actions=output(10),resubmit(2),output(19),resubmit(3),output(21)
        table=0 in_port=2 priority=1500 icmp actions=output(11),resubmit(,1),output(16),resubmit(2,1),output(18)
        table=0 in_port=3 priority=2000 icmp actions=output(20)
        table=1 in_port=1 priority=1000 icmp actions=output(12),resubmit(4,1),output(13),resubmit(3),output(15)
        table=1 in_port=2 priority=1500 icmp actions=output(17),resubmit(,2)
        table=1 in_port=3 priority=1500 icmp actions=output(14),resubmit(,2)
    """)  # noqa: E501

    flow = ("in_port=p1,"
            "dl_src=50:54:00:00:00:05,dl_dst=50:54:00:00:00:07,dl_type=0x0800,"
            "nw_src=192.168.0.1,nw_dst=192.168.0.2,nw_proto=1,nw_tos=0,"
            "nw_ttl=128,nw_frag=no,"
            "icmp_type=8,icmp_code=0")
    assert trace(ovs, "br0", flow) == \
        "Datapath actions: 10,11,12,13,14,15,16,17,18,19,20,21"
