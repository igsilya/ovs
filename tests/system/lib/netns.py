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

"""Network namespaces for system tests.

``IsolatedNetNS`` moves the test into network and mount namespaces of its
own, so system tests can run in parallel: every test has its own network
devices, OVS kernel datapath, conntrack table, and its own set of named
network namespaces created with 'ip netns add'.

``NetNS`` is a named network namespace inside the test, the equivalent of
``ADD_NAMESPACES`` in Autotest, typically used to simulate a host
connected to an OVS bridge.
"""

import ctypes
import ctypes.util
import os
import signal

from tests.lib.cmd import log_line, run

_CLONE_NEWNS = 0x00020000
_CLONE_NEWNET = 0x40000000
_MS_REC = 0x4000
_MS_PRIVATE = 0x40000
_MNT_DETACH = 2

# Pseudo file systems mounted on top of a fresh /sys.
_SYS_MOUNTS = [(b"tracefs", b"/sys/kernel/tracing"),
               (b"debugfs", b"/sys/kernel/debug"),
               (b"bpf", b"/sys/fs/bpf")]

_libc = None


def _libc_call(name, *args):
    global _libc
    if _libc is None:
        _libc = ctypes.CDLL(ctypes.util.find_library("c"), use_errno=True)
    if getattr(_libc, name)(*args) != 0:
        errno = ctypes.get_errno()
        raise OSError(errno, "%s: %s" % (name, os.strerror(errno)))


def _ns_path(nstype):
    # Namespaces are per thread, so use the namespaces of the current
    # thread, not of the main thread of the process.
    if os.path.exists("/proc/thread-self"):
        return "/proc/thread-self/ns/" + nstype
    return "/proc/self/ns/" + nstype


def netns_id(path):
    """Return an identifier of the network namespace at ``path``."""
    st = os.stat(path)
    return (st.st_dev, st.st_ino)


class IsolatedNetNS:
    """Run the current thread in new network and mount namespaces.

    On entry:
     - new network and mount namespaces are created with unshare(2),
     - all mounts are made private, so nothing leaks to the original
       mount namespace,
     - a fresh tmpfs is mounted on /run/netns, so names of namespaces
       created with 'ip netns add' don't collide with other tests (the
       files under /run/netns are shared otherwise),
     - a fresh sysfs is mounted on /sys, so it shows the network devices
       of the new namespace (like 'ip netns exec' does), with tracefs,
       debugfs and bpffs on top of it, for tracing tools like retis,
     - the loopback interface is brought up.

    Processes started by the test inherit the namespaces.  On exit, the
    remaining processes in the network namespace are killed and the
    thread returns to its original namespaces, which destroys the new
    ones along with all their network devices, the OVS datapath, etc.
    """

    def __init__(self):
        self._orig = None
        self.id = None

    def __enter__(self):
        cwd = os.getcwd()
        self._orig = {nstype: os.open(_ns_path(nstype), os.O_RDONLY)
                      for nstype in ("net", "mnt")}
        try:
            _libc_call("unshare", _CLONE_NEWNET | _CLONE_NEWNS)
            self.id = netns_id(_ns_path("net"))
            _libc_call("mount", None, b"/", None, _MS_REC | _MS_PRIVATE,
                       None)
            os.makedirs("/run/netns", exist_ok=True)
            _libc_call("mount", b"tmpfs", b"/run/netns", b"tmpfs", 0, None)
            _libc_call("umount2", b"/sys", _MNT_DETACH)
            _libc_call("mount", b"sysfs", b"/sys", b"sysfs", 0, None)
            for fstype, path in _SYS_MOUNTS:
                try:
                    _libc_call("mount", fstype, path, fstype, 0, None)
                except OSError:
                    # Not supported by the kernel.
                    pass
            run("ip link set lo up")
        except BaseException:
            self._restore(cwd)
            raise
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False

    def close(self):
        if self._orig is None:
            return
        self.kill_processes()
        self._restore(os.getcwd())

    def _restore(self, cwd):
        # setns() for the mount namespace changes the current directory.
        _libc_call("setns", self._orig["net"], _CLONE_NEWNET)
        _libc_call("setns", self._orig["mnt"], _CLONE_NEWNS)
        for fd in self._orig.values():
            os.close(fd)
        self._orig = None
        os.chdir(cwd)

    def kill_processes(self):
        """Kill all processes left in the network namespace."""
        for pid in pids_in_netns(self.id):
            if pid == os.getpid():
                continue
            log_line("   killing leftover process %d" % pid, location=False)
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass


def pids_in_netns(ns_id):
    """Return PIDs of processes in the network namespace ``ns_id``."""
    pids = []
    for entry in os.listdir("/proc"):
        if not entry.isdigit():
            continue
        try:
            if netns_id("/proc/%s/ns/net" % entry) == ns_id:
                pids.append(int(entry))
        except OSError:
            pass
    return pids


class NetNS:
    """A named network namespace, like ``ADD_NAMESPACES`` in Autotest.

    Created with 'ip netns add', so commands can run in it with
    'ip netns exec', e.g., via ``run(cmd, ns=netns)``.  Usually created
    with ``OVSNode.netns()``, which deletes the namespace when the node
    is stopped.
    """

    def __init__(self, name):
        self.name = name
        run("ip netns add " + name)
        # Same as ADD_NAMESPACES, may fail if conntrack is not loaded.
        self.exec("sysctl -w net.netfilter.nf_conntrack_helper=0",
                  rc=None, stdout=True, stderr=True)

    def __repr__(self):
        return "NetNS(%r)" % self.name

    def __str__(self):
        return self.name

    def exec(self, cmd, **kwargs):
        """Run ``cmd`` in this namespace, see ``tests.lib.cmd.run()``."""
        __tracebackhide__ = True
        return run(cmd, ns=self.name, **kwargs)

    def close(self):
        """Kill the processes in the namespace and delete it."""
        if self.name is None:
            return
        try:
            ns_id = netns_id("/run/netns/" + self.name)
        except OSError:
            ns_id = None
        if ns_id is not None:
            for pid in pids_in_netns(ns_id):
                try:
                    os.kill(pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
        run("ip netns del " + self.name, rc=None, stderr=True)
        self.name = None

    # Helpers for configuring interfaces in the namespace.

    def add_vlan(self, port, vlan, ip, proto="802.1q", mtu=None):
        """Add VLAN device '<port>.<vlan>' with address ``ip``.

        Like ``ADD_VLAN`` or, with ``proto="802.1ad"`` and ``mtu=1496``,
        ``ADD_SVLAN``.
        """
        dev = "%s.%d" % (port, vlan)
        self.exec("ip link add link %s name %s type vlan proto %s id %d"
                  % (port, dev, proto, vlan))
        self.exec("ip link set dev %s up" % dev)
        self.exec("ip addr add dev %s %s" % (dev, ip))
        if mtu:
            self.exec("ip link set %s mtu %d" % (dev, mtu))
        return dev

    def add_native_tunnel(self, tunnel_type, port, remote, overlay_ip,
                          type_args="", link_args="", mtu=1450):
        """Add a native tunnel device, like ``ADD_NATIVE_TUNNEL``.

        Use ``mtu=1430`` for an IPv6 underlay (``ADD_NATIVE_TUNNEL6``).
        """
        self.exec("ip link add dev %s type %s remote %s %s"
                  % (port, tunnel_type, remote, type_args))
        self.exec("ip addr add dev %s %s" % (port, overlay_ip))
        self.exec("ip link set dev %s mtu %d %s up" % (port, mtu, link_args))
