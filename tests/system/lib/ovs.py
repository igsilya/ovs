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

"""OVS nodes with real datapaths for system tests.

 - ``OVSNodeSystem`` -- the kernel datapath, like system-kmod-macros.at
   (and system-offloads-testsuite-macros.at with ``offload=True``).
 - ``OVSNodeUserspace`` -- the userspace datapath, like
   system-userspace-macros.at (and system-tso-macros.at with
   ``tso=True``, system-afxdp-macros.at with ``afxdp=True``).

Both provide helpers for building topologies: ``netns()`` (named network
namespaces), ``add_veth()``, ``add_internal()``, ``add_veth_bond()`` and
``add_ovs_tunnel()``.
"""

import re

import pytest

from tests.lib.cmd import run
from tests.lib.ovs import OVSError, OVSNode, check_logs
from tests.system.lib.netns import NetNS


class SystemNode(OVSNode):
    """Common part of the system test nodes."""

    # Additional WARN/ERR messages allowed in daemon logs.
    LOG_ALLOW = []

    def check_logs(self, allow=()):
        __tracebackhide__ = True
        check_logs(self.test_dir, self.LOG_ALLOW + list(allow))

    def netns(self, name):
        """Create named network namespace ``name``, like ADD_NAMESPACES.

        The namespace is deleted when this node stops.
        """
        return self.track(NetNS(name))

    def create_node(self, name, node_cls=None, ns=None, **kwargs):
        """Create a child node running in a new network namespace ``name``.

        See ``OVSNode.create_node()``.
        """
        if ns is None:
            ns = self.netns(name)
        return super().create_node(name, node_cls=node_cls, ns=ns, **kwargs)

    def configure_veth_offloads(self, port, ns=None):
        """Configure offloads of a veth, like CONFIGURE_VETH_OFFLOADS."""

    def port_type(self):
        """Return the OVS interface type for veth ports, or None."""
        return None

    def add_veth(self, port, ns, bridge, ip, mac=None, gateway=None,
                 ip_flags=""):
        """Connect namespace ``ns`` to ``bridge`` with a veth pair.

        Like ADD_VETH: 'port' is moved to ``ns`` and configured with
        address ``ip`` (CIDR), and 'ovs-<port>' is added to ``bridge``.

        Args:
            port: Name of the veth in ``ns``.
            ns: The ``NetNS`` to connect.
            bridge: The OVS bridge.
            ip: IP address in CIDR notation.
            mac: Optional MAC address for ``port``.
            gateway: Optional default gateway in ``ns``.
            ip_flags: Additional arguments for 'ip addr add'.
        """
        ovs_port = "ovs-" + port
        self.run("ip link add %s type veth peer name %s" % (port, ovs_port))
        self.configure_veth_offloads(port)
        self.run("ip link set %s netns %s" % (port, ns))
        self.run("ip link set dev %s up" % ovs_port)
        settings = 'external-ids:iface-id="%s"' % port
        if self.port_type():
            settings += " type=%s" % self.port_type()
        self.vsctl("add-port %s %s -- set interface %s %s"
                   % (bridge, ovs_port, ovs_port, settings))
        run("ip addr add %s dev %s %s" % (ip, port, ip_flags), ns=ns)
        run("ip link set dev %s up" % port, ns=ns)
        if mac:
            run("ip link set dev %s address %s" % (port, mac), ns=ns)
        if gateway:
            run("ip route add default via %s" % gateway, ns=ns)

    def add_internal(self, port, ns, bridge, ip):
        """Add internal port ``port`` to ``bridge`` and move it to ``ns``.

        Like ADD_INT.
        """
        self.vsctl("add-port %s %s -- set int %s type=internal"
                   % (bridge, port, port))
        self.run("ip link set %s netns %s" % (port, ns))
        run("ip addr add %s dev %s" % (ip, port), ns=ns)
        run("ip link set dev %s up" % port, ns=ns)

    def add_veth_bond(self, ports, ns, bridge, bond, mode, ip):
        """Connect ``ns`` to ``bridge`` with a bond, like ADD_VETH_BOND.

        Args:
            ports: Names of the veths in ``ns`` that form bond ``bond``.
            ns: The ``NetNS`` to connect.
            bridge: The OVS bridge.
            bond: Name of the bond.  The OVS bond is 'ovs-<bond>'.
            mode: Bond settings for 'ovs-vsctl add-bond', e.g.,
                'bond_mode=balance-tcp lacp=active'.
            ip: IP address in CIDR notation for the bond in ``ns``.
        """
        ovs_ports = []
        for port in ports:
            self.run("ip link add %s type veth peer name ovs-%s"
                     % (port, port))
            self.configure_veth_offloads(port)
            self.run("ip link set %s netns %s" % (port, ns))
            self.run("ip link set dev ovs-%s up" % port)
            ovs_ports.append("ovs-" + port)
        run("ip link add name %s type bond" % bond, ns=ns)
        m = re.search(r"lacp=(\S+)", mode)
        if m and m.group(1) in ("active", "passive"):
            run("sh -c 'echo 802.3ad > /sys/class/net/%s/bonding/mode'"
                % bond, ns=ns)
            run("sh -c 'echo 100 > /sys/class/net/%s/bonding/miimon'"
                % bond, ns=ns)
        for port in ports:
            run("ip link set dev %s master %s" % (port, bond), ns=ns)
        run("ip addr add %s dev %s" % (ip, bond), ns=ns)
        run("ip link set dev %s up" % bond, ns=ns)
        self.vsctl("add-bond %s ovs-%s %s %s"
                   % (bridge, bond, " ".join(ovs_ports), mode))

    def add_ovs_tunnel(self, tunnel_type, bridge, port, remote, overlay_ip,
                       args="", mtu=1450):
        """Add an OVS tunnel port, like ADD_OVS_TUNNEL.

        ``bridge`` is configured with ``overlay_ip``.  Use ``mtu=1430``
        for an IPv6 underlay (ADD_OVS_TUNNEL6).
        """
        self.vsctl("add-port %s %s -- set int %s type=%s options:remote_ip=%s"
                   " %s" % (bridge, port, port, tunnel_type, remote, args))
        self.run("ip addr add dev %s %s" % (bridge, overlay_ip))
        self.run("ip link set dev %s up" % bridge)
        self.run("ip link set dev %s mtu %d" % (bridge, mtu))

    def require_log(self, message, reason=None):
        """Skip the test unless ovs-vswitchd logged ``message``.

        For datapath features that ovs-vswitchd probes on startup, like
        OVS_CHECK_CT_CLEAR or OVS_CHECK_DROP_ACTION.
        """
        with open(self.test_dir + "/ovs-vswitchd.log",
                  errors="replace") as f:
            if message not in f.read():
                pytest.skip(reason or "'%s' not in ovs-vswitchd.log"
                            % message)

    def vlan_header_stack_length(self):
        """Return the probed VLAN header stack length, or 0."""
        with open(self.test_dir + "/ovs-vswitchd.log",
                  errors="replace") as f:
            m = re.search(r"VLAN header stack length probed as (\d+)",
                          f.read())
        return int(m.group(1)) if m else 0


class OVSNodeSystem(SystemNode):
    """OVS with the kernel datapath, like system-kmod-macros.at.

    Args:
        offload: Enable hardware offload (other_config:hw-offload=true),
            like system-offloads-testsuite-macros.at.
    """

    VSWITCHD_STDERR_ALLOW = OVSNode.VSWITCHD_STDERR_ALLOW + [
        r"dpif_offload\|INFO\|Flow HW offload is enabled",
        r"probe tc:",
        r"setting extended ack support failed",
        r"tc: Using policy",
        r"hw-offload-priority configuration has an unknown type;",
    ]

    def __init__(self, test_dir, offload=False, **kwargs):
        super().__init__(test_dir, **kwargs)
        self.offload = offload

    def db_init_args(self):
        args = super().db_init_args()
        if self.offload:
            args += ["--", "set", "Open_vSwitch", ".",
                     "other_config:hw-offload=true"]
        return args

    def create_node(self, name, node_cls=None, ns=None, **kwargs):
        if node_cls is None or issubclass(node_cls, OVSNodeSystem):
            kwargs.setdefault("offload", self.offload)
        return super().create_node(name, node_cls=node_cls, ns=ns, **kwargs)


class OVSNodeUserspace(SystemNode):
    """OVS with the userspace datapath, like system-userspace-macros.at.

    Args:
        tso: Enable userspace TSO, like system-tso-macros.at.
        afxdp: Use AF_XDP ports for veths, like system-afxdp-macros.at.
        pmd_cpu_mask: CPU mask for PMD threads (other_config:pmd-cpu-mask).
    """

    dp_type = "netdev"

    LOG_ALLOW = [
        r"netdev_linux.*obtaining netdev stats via vport failed",
        r"dpif_netlink.*Generic Netlink family 'ovs_datapath' does not "
        r"exist. The Open vSwitch kernel module is probably not loaded.",
        r"dpif_netdev\(revalidator.*\)\|ERR\|internal error parsing flow "
        r"key.*proto=2.*",
        r"dpif\(revalidator.*\)\|WARN\|netdev@ovs-netdev: failed to"
        r".*proto=2.*",
    ]

    def __init__(self, test_dir, tso=False, afxdp=False, pmd_cpu_mask=None,
                 **kwargs):
        super().__init__(test_dir, **kwargs)
        if tso and afxdp:
            raise OVSError("TSO and AF_XDP modes are mutually exclusive")
        self.tso = tso
        self.afxdp = afxdp
        self.pmd_cpu_mask = pmd_cpu_mask

    def db_init_args(self):
        args = super().db_init_args()
        if self.pmd_cpu_mask:
            args += ["--", "set", "Open_vSwitch", ".",
                     "other_config:pmd-cpu-mask=" + self.pmd_cpu_mask]
        return args

    def vswitchd_options(self):
        return ["--disable-system"] + super().vswitchd_options()

    def start(self):
        super().start()
        if self.tso:
            self.vsctl("set Open_vSwitch . "
                       "other_config:userspace-tso-enable=true")

    def create_node(self, name, node_cls=None, ns=None, **kwargs):
        if node_cls is None or issubclass(node_cls, OVSNodeUserspace):
            kwargs.setdefault("tso", self.tso)
            kwargs.setdefault("afxdp", self.afxdp)
        return super().create_node(name, node_cls=node_cls, ns=ns, **kwargs)

    def port_type(self):
        return "afxdp" if self.afxdp else None

    def configure_veth_offloads(self, port, ns=None):
        if self.tso:
            features = ["sg on", "tso on"]
        elif self.afxdp:
            features = ["tx off", "txvlan off"]
        else:
            features = ["tx off"]
        for feature in features:
            run("ethtool -K %s %s" % (port, feature), ns=ns, stdout=True,
                stderr=True)
