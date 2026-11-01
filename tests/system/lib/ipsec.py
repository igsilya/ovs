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
import threading

from tests.lib.cmd import log_line, run, wait_until, wait_while
from tests.lib.env import srcdir
from tests.lib.process import process_alive
from tests.system.lib.ping import check_ping


# 'ovs-pki req+sign' updates the files of the certificate authority.
_ca_lock = threading.Lock()


def _pki(base, args):
    run("ovs-pki -b -d %s -l %s/ovs-pki.log %s" % (base, base, args),
        stdout=True, stderr=True)


def pki_init(ovs):
    """Create a certificate authority in the test directory.

    Returns:
        The path of the certificate of the authority, the ``ca_cert`` for
        ``IPsecNode.ca_signed_cert()``.
    """
    _pki(ovs.test_dir, "--force init")
    return os.path.join(ovs.test_dir, "switchca", "cacert.pem")


def libreswan_version():
    """Return the version of Libreswan as a tuple of integers."""
    out = run("ipsec --version", stdout=True).stdout
    m = re.search(r"Libreswan (?:U|v)?(\d+(?:\.\d+)*)", out)
    return tuple(int(x) for x in m.group(1).split(".")) if m else ()


class _Pluto:
    """The Libreswan IKE daemon of a node, stopped with ``close()``."""

    def __init__(self, ns, base, rundir):
        self.ns = ns
        self.base = base
        self.rundir = rundir
        self.pidfile = os.path.join(rundir, "pluto.pid")
        os.makedirs(os.path.join(base, "ipsec.d"), exist_ok=True)
        for name in ("ipsec.conf", "secrets"):
            open(os.path.join(base, name), "a").close()
        run("ipsec initnss --nssdir %s/ipsec.d" % base, stdout=True,
            stderr=True)
        self.start()

    def start(self):
        base = self.base
        self.ns.exec("ipsec pluto --config %s/ipsec.conf --ipsecdir %s "
                     "--nssdir %s/ipsec.d --logfile %s/pluto.log "
                     "--secretsfile %s/secrets --rundir %s"
                     % (base, base, base, base, base, self.rundir),
                     stderr=True)

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


class _StatusSaver:
    """Saves 'ipsec status' of a node to 'status' in its directory when
    the node stops, for debugging."""

    def __init__(self, node):
        self.node = node

    def close(self):
        with open(os.path.join(self.node.base, "status"), "w") as f:
            f.write(self.node.status())


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
        self.pki_dir = ovs.test_dir
        self.cert = None
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
        # ovs-monitor-ipsec reads the schema from OVS_PKGDATADIR, which is
        # the directory of the node, like IPSEC_SETUP_UNDERLAY.
        shutil.copy(os.path.join(srcdir(), "vswitchd", "vswitch.ovsschema"),
                    base)

        # The control socket of pluto is in its run directory, which must
        # have a short path, see https://github.com/libreswan/libreswan/
        # issues/428.
        self.rundir = self.node.track(_TempDir("ovs-ipsec-")).path
        self.pluto = self.node.track(_Pluto(self.ns, base, self.rundir))
        self.node.track(_StatusSaver(self))
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
        # Unlike in Autotest, every node has its own OVS_RUNDIR with the
        # default management socket of the bridge, so there is no need for
        # an extra one.
        self.node.vsctl("add-br br-ipsec")

    def status(self):
        """Return the output of 'ipsec status'."""
        r = run("ipsec --rundir %s status" % self.rundir, rc=None,
                stdout=True, stderr=True)
        return r.stdout + r.stderr

    def pluto_running(self):
        return not re.search(r"is Pluto running\?|refused", self.status())

    def restart_pluto(self):
        """Start pluto again, e.g., after it crashed."""
        log_line("pluto of %s is not running, restarting" % self.name)
        self.pluto.start()

    def set_certificate(self, cert, key, ca_cert=None):
        """Use certificate ``cert`` with private key ``key``, and the
        certificate authority ``ca_cert``, if any."""
        self.cert = cert
        self.node.vsctl("set Open_vSwitch . other_config:certificate=%s "
                        "other_config:private_key=%s%s"
                        % (cert, key, " other_config:ca_cert=%s" % ca_cert
                           if ca_cert else ""))

    def _pki_path(self, suffix):
        return os.path.join(self.pki_dir, "%s-%s.pem" % (self.name, suffix))

    def self_signed_cert(self):
        """Create a self-signed certificate for this node and use it.

        The peers need it as ``options:remote_cert``.

        Returns:
            The path of the certificate.
        """
        for args in ("req -u %s", "self-sign %s"):
            _pki(self.pki_dir, args % self.name)
        self.set_certificate(self._pki_path("cert"),
                             self._pki_path("privkey"))
        return self.cert

    def ca_signed_cert(self, ca_cert):
        """Create a certificate for this node, signed by the authority
        created with ``pki_init()``, and use it.

        The peers refer to it with ``options:remote_name=<name>``.

        Returns:
            The path of the certificate.
        """
        with _ca_lock:
            _pki(self.pki_dir, "req+sign -u %s" % self.name)
        self.set_certificate(self._pki_path("cert"),
                             self._pki_path("privkey"), ca_cert)
        return self.cert

    def monitor_log(self):
        """Return the contents of the log of ovs-monitor-ipsec."""
        try:
            with open(os.path.join(self.base, "ovs-monitor-ipsec.log"),
                      errors="replace") as f:
                return f.read()
        except OSError:
            return ""

    def delete_connection(self, conn):
        """Delete IPsec connection ``conn`` from pluto."""
        # 'ipsec auto' is deprecated in Libreswan 5.
        auto = "" if run("ipsec auto --help", rc=None, stdout=True,
                         stderr=True).stderr else "auto"
        run("ipsec %s --ctlsocket %s/pluto.ctl --config %s/ipsec.conf "
            "--delete %s" % (auto, self.rundir, self.base, conn),
            stdout=True)

    def connections(self):
        """Return the numbers of (loaded, active) IPsec connections."""
        m = re.search(r"Total IPsec connections:.*loaded (\d+).*active "
                      r"(\d+)", self.status())
        return (int(m.group(1)), int(m.group(2))) if m else (0, 0)

    def wait_for_connections(self, loaded, active=False, revive=False,
                             timeout=None):
        """Wait for ``loaded`` connections to be loaded into pluto.

        Args:
            loaded: The expected number of loaded connections.
            active: Whether to also wait for all of them to be active.
            revive: Whether to start pluto again if it crashed while
                waiting, unfortunately it happens.
            timeout: Maximum time in seconds.  Defaults to
                ``ctl_timeout()``.
        """
        def ready():
            if revive and not self.pluto_running():
                self.restart_pluto()
                return False
            n_loaded, n_active = self.connections()
            return n_loaded == loaded and (not active or n_active == loaded)

        wait_until(ready, timeout=timeout,
                   description="%d IPsec connections %s on %s"
                   % (loaded, "active" if active else "loaded", self.name))

    def add_tunnel(self, tunnel_type, options):
        """Add tunnel port 'tun' to 'br-ipsec', like IPSEC_ADD_TUNNEL.

        Waits for the IPsec connections of the tunnel to be loaded into
        Libreswan: one for GRE, two for the other types.
        """
        self.node.vsctl("add-port br-ipsec tun -- set Interface tun type=%s "
                        "%s" % (tunnel_type, options))
        self.wait_for_connections(1 if tunnel_type == "gre" else 2)


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
