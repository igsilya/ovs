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

"""Tests for the system test infrastructure itself."""

import os

from tests.lib.cmd import run, wait_until
from tests.lib.process import process_alive
from tests.system.lib.netns import IsolatedNetNS, netns_id

# Fallback devices of tunnel modules, created in every network namespace
# when the modules are loaded, and the bonding control file.
NETNS_DEFAULT_DEVICES = {
    "bonding_masters", "erspan0", "gre0", "gretap0", "ip6_vti0", "ip6gre0",
    "ip6tnl0", "ip_vti0", "sit0", "tunl0",
}


def test_isolation(test_dir):
    host_netns = netns_id("/proc/self/ns/net")
    host_devices = set(os.listdir("/sys/class/net"))
    host_netns_names = run("ip netns list", stdout=True).stdout

    with IsolatedNetNS() as ns:
        assert netns_id("/proc/self/ns/net") == ns.id != host_netns
        # Only the loopback and devices that the kernel creates in every
        # namespace, and /sys shows the new namespace.
        devices = set(os.listdir("/sys/class/net"))
        assert "lo" in devices
        assert devices <= {"lo"} | NETNS_DEFAULT_DEVICES
        run("ip -o link show lo", stdout=True)
        # Named namespaces of the host are not visible and new ones don't
        # show up on the host.
        run("ip netns list", stdout=[])
        run("ip netns add at_ns0")
        run("ip link add p0 type veth peer name ovs-p0")
        assert {"p0", "ovs-p0"} <= set(os.listdir("/sys/class/net"))
        # The working directory is preserved.
        assert os.getcwd() == test_dir

    assert netns_id("/proc/self/ns/net") == host_netns
    assert set(os.listdir("/sys/class/net")) == host_devices
    assert run("ip netns list", stdout=True).stdout == host_netns_names
    assert os.getcwd() == test_dir


def test_leftover_processes_killed():
    with IsolatedNetNS():
        proc = run("sleep 1000 > /dev/null 2>&1 & echo $!", stdout=True)
        pid = int(proc.stdout)
        wait_until(lambda: process_alive(pid, "sleep"))
    wait_until(lambda: not process_alive(pid))


def test_netns(ovs):
    ns0 = ovs.netns("at_ns0")
    ovs.add_veth("p0", ns0, "br0", "10.1.1.1/24", mac="f0:00:00:01:01:01",
                 gateway="10.1.1.254")
    ns0.exec("ip -o addr show p0 | grep -q 10.1.1.1/24")
    ns0.exec("ip link show p0 | grep -q f0:00:00:01:01:01")
    route = ns0.exec("ip route show default", stdout=True).stdout
    assert route.split()[:5] == ["default", "via", "10.1.1.254", "dev", "p0"]
    run("ip netns list", stdout=True)
    ovs.vsctl("get interface ovs-p0 external-ids:iface-id", stdout=['p0'])
    sleeper = ovs.start_background("sleep 1000", ns=ns0)
    # Make sure it is in the namespace ('ip netns exec' replaced itself).
    wait_until(lambda: process_alive(sleeper.pid, "sleep"))
    # Deleting the namespace destroys the veth pair.
    ovs.vsctl("del-port ovs-p0")
    ns0.close()
    assert ns0.name is None
    wait_until(lambda: not sleeper.alive())
    run("ip netns list", stdout=[])


def test_child_node(ovs):
    hv1 = ovs.create_node("hv1")
    hv1.start()
    hv1.add_bridge("br-hv1")
    hv1.vsctl("list-br", stdout=["br-hv1"])
    ovs.vsctl("list-br", stdout=["br0"])
    # The child runs in its own namespace.
    hv1.run("ip -o link show br-hv1", stdout=True)
    run("ip link show br-hv1", rc=1, stderr=True)
