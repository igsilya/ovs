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

"""IPsec tests, migrated from system-ipsec.at."""

import re

import pytest

from tests.lib.cmd import parallel, wait_until
from tests.system.lib.ipsec import (IPsecNode, check_esp_traffic,
                                    libreswan_version)
from tests.system.lib.ping import ping

pytestmark = pytest.mark.requires("kernel_datapath", "libreswan", "tcpdump")


# Geneve may not work on older kernels due to CVE-2020-25645, see
# https://bugzilla.redhat.com/show_bug.cgi?id=1883988.  Like the Autotest
# IPsec tests, these don't check for Geneve support and firewalld.
def test_libreswan_ipv4_geneve_defaultroute_psk(ovs):
    ovs.ofctl("add-flow br0 actions=normal")
    left = IPsecNode(ovs, "left", "p0", "10.1.1.1", "10.1.1.2")
    right = IPsecNode(ovs, "right", "p1", "10.1.1.2", "10.1.1.1")

    left.add_tunnel("geneve", "options:remote_ip=10.1.1.2 "
                              "options:psk=swordfish")
    right.add_tunnel("geneve", "options:remote_ip=10.1.1.1 "
                               "options:psk=swordfish")
    check_esp_traffic(ovs, left, right)


def test_libreswan_nxn_geneve_tunnels_reconciliation(ovs):
    n_nodes = 20
    ids = range(1, n_nodes + 1)
    n_conns = 2 * (n_nodes - 1)

    def mac(i):
        return "f2:ff:00:00:00:%02d" % i

    ovs.ofctl("add-flow br0 actions=normal")

    # Nodes with self-signed certificates, set up in parallel.
    def add_node(i):
        node = IPsecNode(ovs, "node-%d" % i, "p-%d" % i, "10.1.1.%d" % i,
                         "10.1.1.254")
        node.self_signed_cert()
        node.node.vsctl("set bridge br-ipsec other-config:hwaddr=%s"
                        % mac(i))
        return node

    nodes = dict(zip(ids, parallel(add_node, ids)))

    # A full mesh of tunnels.
    def add_tunnels(i):
        nodes[i].node.vsctl(" ".join(
            "-- add-port br-ipsec tun-%d -- set Interface tun-%d type=geneve"
            " options:remote_ip=10.1.1.%d options:remote_cert=%s"
            % (j, j, j, nodes[j].cert) for j in ids if j != i))

    parallel(add_tunnels, ids)

    # It may take long: the default retransmit timeout of pluto is 60
    # seconds.
    def wait_for_connections(active=False):
        parallel(lambda node: node.wait_for_connections(
            n_conns, active=active, revive=True, timeout=300),
            nodes.values())

    # Not waiting for the connections to become active, because if pluto
    # is down on one of the nodes, some connections may not become active
    # until it is revived.  Some may also never become active due to bugs
    # in Libreswan 4.x.
    wait_for_connections()

    # Different versions of Libreswan 4.x have issues where connections are
    # not established correctly or never become active, in a way that can't
    # be mitigated by ovs-monitor-ipsec or the test.  Skipping here, so the
    # first half still runs with them.
    if libreswan_version()[:1] == (4,):
        pytest.skip("connections don't become active with Libreswan 4.x")

    node1 = nodes[1]
    wait_until(lambda: "all(%d) configured tunnels are Up" % (n_nodes - 1)
               in node1.monitor_log(),
               description="all the tunnels of node-1 up")

    # Remove connections of two tunnels, one fully and one partially, and
    # wait for the monitor to restore them.
    for conn in ("tun-5-out-1", "tun-2-in-1", "tun-2-out-1"):
        node1.delete_connection(conn)
    wait_until(lambda: re.search(r"tun-[25] .*need to reconcile",
                                 node1.monitor_log()),
               description="node-1 reconciles the deleted connections")
    wait_for_connections()

    # No IPv6, static ARP entries and exact OpenFlow rules, to avoid any
    # broadcast and multicast traffic, which would be multiplied by every
    # node into a traffic storm.
    def configure_traffic(i):
        node = nodes[i]
        others = [j for j in ids if j != i]
        node.ns.exec("sysctl -w net.ipv6.conf.all.disable_ipv6=1",
                     stdout=True)
        node.node.ofctl("del-flows br-ipsec")
        node.node.add_flows("br-ipsec", "\n".join(
            ["dl_dst=%s actions=LOCAL" % mac(i)]
            + ["dl_dst=%s actions=tun-%d" % (mac(j), j) for j in others]))
        node.ns.exec("sh -c '%s'" % "; ".join(
            "ip neigh add 192.0.0.%d lladdr %s dev br-ipsec" % (j, mac(j))
            for j in others))
        node.ns.exec("ip addr add 192.0.0.%d/24 dev br-ipsec" % i)
        node.ns.exec("ip link set dev br-ipsec up")

    parallel(configure_traffic, ids)
    wait_for_connections(active=True)

    # Full mesh ping, all the pairs at the same time.
    def ping_pair(pair):
        i, j = pair
        # The first packet may be lost while the connection recovers.
        ping("192.0.0.%d" % j, ns=nodes[i].ns, count=1)
        return ping("192.0.0.%d" % j, ns=nodes[i].ns, count=3, interval=0.1)

    pairs = [(i, j) for i in ids for j in ids if i != j]
    results = parallel(ping_pair, pairs, max_workers=len(pairs))
    failed = ["node-%d -> node-%d: %d of %d received" % (i, j, r.received,
                                                         r.transmitted)
              for (i, j), r in zip(pairs, results) if r.received != 3]
    assert not failed, "\n".join(failed)

    # Stopping the nodes one by one takes a while.  Their namespaces are
    # deleted after the underlay switch stops, as usual.
    parallel(lambda node: node.node.stop(), nodes.values())
