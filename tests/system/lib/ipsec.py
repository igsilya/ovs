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

"""IPsec endpoints with Libreswan for system tests, like system-ipsec.at.

An ``IPsecNode`` is a host in a network namespace of its own, connected to
the underlay bridge 'br0' of the test, with its own ovsdb-server,
ovs-vswitchd, pluto and ovs-monitor-ipsec, and a bridge 'br-ipsec' for the
tunnels.
"""

import os
import re
import shutil
import signal
import tempfile

from tests.lib.cmd import log_line, run, wait_until, wait_while
from tests.lib.process import process_alive
from tests.system.lib.ping import check_ping


class _Pluto:
    """The Libreswan IKE daemon of a node, stopped with ``close()``."""

    def __init__(self, ns, base, rundir):
        self.pidfile = os.path.join(rundir, "pluto.pid")
        os.makedirs(os.path.join(base, "ipsec.d"), exist_ok=True)
        for name in ("ipsec.conf", "secrets"):
            open(os.path.join(base, name), "a").close()
        run("ipsec initnss --nssdir %s/ipsec.d" % base, stdout=True,
            stderr=True)
        ns.exec("ipsec pluto --config %s/ipsec.conf --ipsecdir %s "
                "--nssdir %s/ipsec.d --logfile %s/pluto.log "
                "--secretsfile %s/secrets --rundir %s"
                % (base, base, base, base, base, rundir), stderr=True)

    def close(self):
        try:
            with open(self.pidfile) as f:
                pid = int(f.read())
        except (OSError, ValueError):
            return
        log_line("$ kill %d  # pluto" % pid)
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            return
        wait_while(lambda: process_alive(pid), description="pluto to exit")


class _TempDir:
    def __init__(self, prefix):
        self.path = tempfile.mkdtemp(prefix=prefix)

    def close(self):
        shutil.rmtree(self.path, ignore_errors=True)


class IPsecNode:
    """An IPsec endpoint, like IPSEC_ADD_NODE.

    Args:
        ovs: The ``SystemNode`` of the test, with the underlay bridge
            'br0'.
        name: Name of the node and of its network namespace.
        dev: Name of the veth of the node, connected to 'br0'.
        address: IPv4 address of the node.
        peer: The address of the peer, the default gateway of the node.
    """

    def __init__(self, ovs, name, dev, address, peer):
        self.name = name
        self.ns = ovs.netns(name)
        # No duplicates on this underlay network.
        for conf in ("all", "default"):
            self.ns.exec("sysctl -w net.ipv6.conf.%s.accept_dad=0" % conf,
                         stdout=True)
        ovs.add_veth(dev, self.ns, "br0", address + "/24")
        self.ns.exec("ip route add default via %s dev %s" % (peer, dev))

        self.node = ovs.create_node(name, ns=self.ns)
        self.node.start()
        base = self.base = self.node.test_dir

        # The control socket of pluto is in its run directory, which must
        # have a short path, see https://github.com/libreswan/libreswan/
        # issues/428.
        self.rundir = self.node.track(_TempDir("ovs-ipsec-")).path
        self.node.track(_Pluto(self.ns, base, self.rundir))
        self.node.start_daemon(
            "ovs-monitor-ipsec", "unix:%s/db.sock" % base,
            "--pidfile=%s/ovs-monitor-ipsec.pid" % base,
            "--ike-daemon=libreswan",
            "--ipsec-conf=%s/ipsec.conf" % base,
            "--ipsec-d=%s/ipsec.d" % base,
            "--ipsec-secrets=%s/secrets" % base,
            "--log-file=%s/ovs-monitor-ipsec.log" % base,
            "--ipsec-ctl=%s/pluto.ctl" % self.rundir,
            "--no-restart-ike-daemon", "--detach",
            pidfile="%s/ovs-monitor-ipsec.pid" % base, detach=False,
            stderr_allow=[])
        self.node.vsctl("add-br br-ipsec -- set-controller br-ipsec "
                        "punix:%s/br-ipsec.mgmt" % base)

    def connections(self):
        """Return the numbers of (loaded, active) IPsec connections."""
        status = run("ipsec --rundir %s status" % self.rundir,
                     stdout=True).stdout
        m = re.search(r"Total IPsec connections:.*loaded (\d+).*active "
                      r"(\d+)", status)
        return (int(m.group(1)), int(m.group(2))) if m else (0, 0)

    def add_tunnel(self, tunnel_type, options):
        """Add tunnel port 'tun' to 'br-ipsec', like IPSEC_ADD_TUNNEL.

        Waits for the IPsec connections of the tunnel to be loaded into
        Libreswan: one for GRE, two for the other types.
        """
        self.node.vsctl("add-port br-ipsec tun -- set Interface tun type=%s "
                        "%s" % (tunnel_type, options))
        n = 1 if tunnel_type == "gre" else 2
        wait_until(lambda: self.connections()[0] == n,
                   description="%d IPsec connections loaded on %s"
                   % (n, self.name))


def check_esp_traffic(ovs, left, right):
    """Check connectivity over the tunnels and that it is ESP in the
    underlay, like CHECK_ESP_TRAFFIC.
    """
    nodes = ((left, "192.0.0.1/24", "ovs-p0"),
             (right, "192.0.0.2/24", "ovs-p1"))
    for node, ip, _ in nodes:
        node.ns.exec("ip addr add %s dev br-ipsec" % ip)
        node.ns.exec("ip link set dev br-ipsec up")

    # Capture the ESP packets in the underlay.
    logs = []
    for node, _, port in nodes:
        log = os.path.join(node.base, "tcpdump.log")
        ovs.start_background("tcpdump -l -nn -i %s esp" % port, stdout=log)
        logs.append(log)

    for node in (left, right):
        wait_until(lambda: node.connections()[0] == node.connections()[1],
                   description="IPsec connections active on %s" % node.name)

    check_ping("192.0.0.2", ns=left.ns)
    check_ping("192.0.0.1", ns=right.ns)

    for log in logs:
        wait_until(lambda: "ESP" in open(log).read(),
                   description="ESP packets in %s" % log)
