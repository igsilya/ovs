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

"""OVS instances for tests.

An ``OVSNode`` is an ovsdb-server and ovs-vswitchd pair running in a
directory of its own, optionally inside a network namespace.  It is the
equivalent of ``OVS_VSWITCHD_START`` / ``OVS_VSWITCHD_STOP`` in Autotest,
and it also owns everything else a test creates around it: background
processes, child nodes (for multi-node topologies) and other resources
like network namespaces.  All of them are cleaned up in reverse order
when the node is stopped.

``OVSNodeDummy`` uses the dummy datapath and needs no privileges.
Datapath-specific subclasses for system tests live in
``tests.system.lib.ovs``.

Usage::

    with OVSNodeDummy(test_dir) as ovs:
        ovs.add_bridge("br0")
        ovs.ofctl("add-flow br0 actions=normal")
"""

import os
import re
import signal

from tests.lib import cmd
from tests.lib.cmd import ctl_timeout, log_line, wait_until, wait_while
from tests.lib.env import srcdir
from tests.lib.process import BackgroundProcess, process_alive

BRIDGE_PROTOCOLS = ("OpenFlow10,OpenFlow11,OpenFlow12,"
                    "OpenFlow13,OpenFlow14,OpenFlow15")

# WARN/ERR/EMER messages that never fail a test.  Same as check_logs() in
# tests/ofproto-macros.at.
LOG_ALLOW_BUILTIN = [
    r"reset by peer",
    r"Broken pipe",
    r"is not connected",
    r"timeval.*Unreasonably long [0-9]*ms poll interval",
    r"timeval.*faults: [0-9]* minor, [0-9]* major",
    r"timeval.*disk: [0-9]* reads, [0-9]* writes",
    r"timeval.*context switches: [0-9]* voluntary, [0-9]* involuntary",
    r"ovs_rcu.*blocked [0-9]* ms waiting for .* to quiesce",
    r"Dropped [0-9]* log messages",
    r"setting extended ack support failed",
    r"ETHTOOL_GSSET_INFO",
    r"Spent an unreasonably long .*ms dumping flows",
]

_LOG_LEVELS = re.compile(r"\|(WARN|ERR|EMER)\|")


class OVSError(AssertionError):
    """Unexpected behavior of an OVS instance, e.g., errors in the logs."""


def check_logs(log_dir, allow=()):
    """Check daemon logs for unexpected WARN, ERR and EMER messages.

    The equivalent of ``check_logs`` from ``tests/ofproto-macros.at``.
    Scans all ``*.log`` files in ``log_dir``, except the test transcript.

    Args:
        log_dir: Directory with the log files.
        allow: Regular expressions for messages to ignore, in addition
            to ``LOG_ALLOW_BUILTIN``.

    Raises:
        OVSError: if unexpected messages are found.
    """
    filters = [re.compile(p) for p in LOG_ALLOW_BUILTIN + list(allow)]
    unexpected = []
    for name in sorted(os.listdir(log_dir)):
        if not name.endswith(".log") or name == "pytest.log" \
                or "testsuite" in name:
            continue
        with open(os.path.join(log_dir, name), errors="replace") as f:
            for line in f:
                if _LOG_LEVELS.search(line) \
                        and not any(r.search(line) for r in filters):
                    unexpected.append("%s: %s" % (name, line.rstrip("\n")))
    if unexpected:
        raise OVSError("Unexpected messages in daemon logs:\n"
                       + "\n".join("  " + m for m in unexpected))


def check_stderr(program, stderr, allow):
    """Check startup stderr of a daemon for unexpected messages.

    Raises:
        OVSError: if a line of ``stderr`` doesn't match any of the regular
            expressions in ``allow``.
    """
    filters = [re.compile(p) for p in allow]
    unexpected = [line for line in stderr.splitlines()
                  if line and not any(r.search(line) for r in filters)]
    if unexpected:
        raise OVSError("Unexpected stderr from %s:\n%s" % (
            program, "\n".join("  " + line for line in unexpected)))


class OVSNode:
    """An OVS instance: ovsdb-server and ovs-vswitchd.

    Subclasses set ``dp_type`` and may extend ``vswitchd_options()``,
    ``db_init_args()``, ``vswitchd_stderr_allow()`` and ``exit_args()``.

    Args:
        test_dir: Directory for the database, sockets, pidfiles and logs.
        ns: Network namespace to run the daemons in (a name or an object
            with ``name``), or None.
        parent: The parent node, if this node was created with
            ``create_node()``.
        wrapper: Command prefix for the daemons, e.g., valgrind.
        export_env: Whether to export the OVS environment variables of
            this node (``OVS_RUNDIR`` and friends) to the test process,
            so that commands run with ``run()`` talk to this node, like
            in Autotest.  Defaults to True for nodes without a parent.
    """

    # The value for the 'datapath_type' column of new bridges.
    dp_type = None

    OVSDB_STDERR_ALLOW = [
        r"vlog\|INFO\|opened log file",
        r"ovsdb_server\|INFO\|ovsdb-server \(Open vSwitch\)",
    ]

    VSWITCHD_STDERR_ALLOW = [
        r"ovs_numa\|INFO\|Discovered ",
        r"odp_execute_impl\|INFO\|Action implementation ",
        r"vlog\|INFO\|opened log file",
        r"vswitchd\|INFO\|ovs-vswitchd \(Open vSwitch\)",
        r"reconnect\|INFO\|",
        r"dpif_netlink\|INFO\|Generic Netlink family .ovs_datapath. "
        r"does not exist",
        r"ofproto\|INFO\|using datapath ID",
        r"netdev_linux\|INFO\|.*device has unknown hardware address family",
        r"ofproto\|INFO\|datapath ID changed to fedcba9876543210",
        r"dpdk\|INFO\|DPDK Disabled - Use other_config:dpdk-init to enable",
        r"netlink_socket\|INFO\|netlink: could not enable listening to "
        r"all nsid",
    ]

    def __init__(self, test_dir, ns=None, parent=None, wrapper=None,
                 export_env=None):
        self.test_dir = os.path.abspath(str(test_dir))
        self.ns = ns
        self.parent = parent
        self.wrapper = tuple(wrapper or ())
        self.export_env = parent is None if export_env is None \
            else export_env
        self.env = {var: self.test_dir for var in (
            "OVS_RUNDIR", "OVS_LOGDIR", "OVS_DBDIR", "OVS_SYSCONFDIR",
            "OVS_PKGDATADIR")}

        self._children = []
        self._daemons = []       # (program, pidfile, appctl target)
        self._background = []
        self._resources = []     # Objects with close().
        self._saved_env = None
        self.started = False

    def __enter__(self):
        try:
            self.start()
        except BaseException:
            self.stop(check=False)
            raise
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop(check=exc_type is None)
        return False

    def __repr__(self):
        return "%s(%r)" % (type(self).__name__, self.test_dir)

    # Running commands.

    def run(self, command, **kwargs):
        """Run a command in the environment and namespace of this node.

        Same arguments as ``tests.lib.cmd.run()``.
        """
        __tracebackhide__ = True
        kwargs.setdefault("ns", self.ns)
        env = dict(self.env)
        env.update(kwargs.pop("env", None) or {})
        return cmd.run(command, env=env, **kwargs)

    def vsctl(self, args, **kwargs):
        """Run ``ovs-vsctl`` against this node."""
        __tracebackhide__ = True
        return self.run("ovs-vsctl " + args, **kwargs)

    def ofctl(self, args, **kwargs):
        """Run ``ovs-ofctl`` against this node."""
        __tracebackhide__ = True
        return self.run("ovs-ofctl " + args, **kwargs)

    def add_flows(self, bridge, flows, args="", name=None):
        """Add OpenFlow rules to ``bridge`` with 'ovs-ofctl add-flows'.

        ``flows`` is a block of rules in ovs-ofctl syntax, one per line,
        like a flows file in Autotest tests.  Leading and trailing white
        space and empty lines are ignored, so the block can be indented
        with the code.  Don't wrap the rules, they are harder to read
        wrapped.  Long lines can be allowed with '# noqa: E501' after the
        closing quotes.

        Args:
            bridge: Bridge name.
            flows: The rules.
            args: Additional arguments for 'ovs-ofctl', e.g., '--bundle'
                or '-O OpenFlow13'.
            name: Name of the file for the rules in the test directory,
                'flows-<bridge>.txt' by default.
        """
        __tracebackhide__ = True
        path = os.path.join(self.test_dir, name or "flows-%s.txt" % bridge)
        with open(path, "w") as f:
            for line in flows.splitlines():
                if line.strip():
                    f.write(line.strip() + "\n")
        return self.ofctl("%s add-flows %s %s" % (args, bridge, path))

    def appctl(self, args, target="ovs-vswitchd", **kwargs):
        """Run ``ovs-appctl`` against a daemon of this node."""
        __tracebackhide__ = True
        return self.run("ovs-appctl -t %s %s" % (target, args), **kwargs)

    def start_background(self, command, stdout=None, stderr=None, ns=None):
        """Start a background process, stopped when this node stops.

        The process runs in the environment of this node and in its
        namespace, unless ``ns`` is given.
        """
        return BackgroundProcess(command, ns=ns or self.ns, stdout=stdout,
                                 stderr=stderr, owner=self, env=self.env)

    # Resources.

    def track(self, resource):
        """Close ``resource`` when this node stops.

        Resources are closed in reverse order, after the daemons are
        stopped.  ``resource`` must have a ``close()`` method.
        """
        self._resources.append(resource)
        return resource

    def create_node(self, name, node_cls=None, ns=None, **kwargs):
        """Create a child node in subdirectory ``name``.

        The child is stopped before this node.  It is not started.

        Args:
            name: Name of the subdirectory.
            node_cls: Class of the child, defaults to the class of this
                node.
            ns: Network namespace for the child.
            **kwargs: Additional arguments for the child constructor.
        """
        node_cls = node_cls or type(self)
        child_dir = os.path.join(self.test_dir, name)
        os.makedirs(child_dir, exist_ok=True)
        kwargs.setdefault("wrapper", self.wrapper)
        child = node_cls(child_dir, ns=ns, parent=self, **kwargs)
        self._children.append(child)
        return child

    # Daemons.

    def start_daemon(self, program, *args, pidfile=None, target=None,
                     stderr_allow=None, detach=True, wrap=True):
        """Start a daemon that detaches and writes a pidfile.

        Args:
            program: The daemon executable.
            *args: Command line arguments.
            pidfile: Path of the pidfile.  Defaults to
                ``<test_dir>/<program>.pid``, which is passed to the
                daemon with ``--pidfile`` if ``detach`` is True.
            target: ``ovs-appctl`` target for stopping the daemon, or
                None if it should be stopped with a signal.
            stderr_allow: Regular expressions for allowed stderr output.
                Any other output fails the start.  None to not check.
            detach: Whether to add the OVS daemon options:
                ``--detach --no-chdir --pidfile=... --log-file=...``.
            wrap: Whether to run the daemon under ``wrapper``.
        """
        args = list(args)
        if detach:
            if pidfile is None:
                pidfile = os.path.join(self.test_dir, program + ".pid")
            args += ["--detach", "--no-chdir", "--pidfile=" + pidfile,
                     "--log-file=" + os.path.join(self.test_dir,
                                                  program + ".log")]
        if pidfile is None:
            raise ValueError("pidfile is required for %s" % program)

        argv = (list(self.wrapper) if wrap else []) + [program] + args
        result = self.run(" ".join(argv), stdout=True, stderr=True)
        # Track the daemon before checking stderr, so it is stopped even
        # if the check fails.
        self._daemons.append((program, pidfile, target))
        if stderr_allow is not None:
            check_stderr(program, result.stderr, stderr_allow)

    def stop_daemon(self, pidfile):
        """Stop the daemon started with ``pidfile`` and wait for it to exit.

        Raises:
            OVSError: if the daemon is not known or doesn't stop cleanly.
        """
        __tracebackhide__ = True
        for daemon in self._daemons:
            if daemon[1] == pidfile:
                self._daemons.remove(daemon)
                problems = self._stop_daemon(*daemon)
                if problems:
                    raise OVSError("\n".join(problems))
                return
        raise OVSError("no daemon with pidfile %s" % pidfile)

    def _stop_daemon(self, program, pidfile, target):
        """Stop a daemon.  Returns a list of problems encountered."""
        try:
            with open(pidfile) as f:
                pid = int(f.read().strip())
        except (OSError, ValueError):
            return ["%s: no valid pidfile %s" % (program, pidfile)]

        if not process_alive(pid, program):
            return ["%s (pid %d) is not running" % (program, pid)]

        errors = []
        if target:
            result = self.appctl(" ".join(["exit"] + self.exit_args(program)),
                                 target=target, rc=None, stdout=True,
                                 stderr=True, timeout=ctl_timeout())
            if result.returncode != 0 or result.stdout or result.stderr:
                errors.append("%s: 'ovs-appctl exit' failed" % program)
        else:
            log_line("$ kill %d  # %s" % (pid, program))
            os.kill(pid, signal.SIGTERM)

        try:
            wait_while(lambda: process_alive(pid, program),
                       description="%s (pid %d) is running" % (program, pid))
        except AssertionError:
            log_line("   sending SIGKILL to %d" % pid, location=False)
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            errors.append("%s (pid %d) did not exit" % (program, pid))
        return errors

    def exit_args(self, program):
        """Return arguments for 'ovs-appctl exit' for ``program``."""
        return ["--cleanup"] if program == "ovs-vswitchd" else []

    # Starting and stopping.

    def vswitchd_options(self):
        """Return additional ovs-vswitchd command line options."""
        return ["-vvconn", "-vofproto_dpif", "-vunixctl"]

    def db_init_args(self):
        """Return additional arguments for 'ovs-vsctl init'."""
        return []

    def vswitchd_stderr_allow(self):
        """Return regular expressions for allowed ovs-vswitchd stderr."""
        return list(self.VSWITCHD_STDERR_ALLOW)

    def start(self):
        """Create the database and start ovsdb-server and ovs-vswitchd."""
        if self.started:
            return
        self.started = True

        if self.export_env:
            self._saved_env = {k: os.environ.get(k) for k in self.env}
            os.environ.update(self.env)

        db = os.path.join(self.test_dir, "conf.db")
        open(os.path.join(self.test_dir, ".conf.db.~lock~"), "a").close()
        self.run("ovsdb-tool create %s %s" % (
            db, os.path.join(srcdir(), "vswitchd", "vswitch.ovsschema")))
        self.start_daemon(
            "ovsdb-server", db,
            "--remote=punix:" + os.path.join(self.test_dir, "db.sock"),
            target="ovsdb-server", stderr_allow=self.OVSDB_STDERR_ALLOW)

        self.vsctl(" ".join(["--no-wait", "init"] + self.db_init_args()))

        self.start_daemon("ovs-vswitchd", *self.vswitchd_options(),
                          target="ovs-vswitchd",
                          stderr_allow=self.vswitchd_stderr_allow())

    def wait_for_log(self, text, program="ovs-vswitchd"):
        """Wait for ``text`` to appear in the log of ``program``."""
        path = os.path.join(self.test_dir, program + ".log")

        def logged():
            try:
                with open(path, errors="replace") as f:
                    return text in f.read()
            except OSError:
                return False

        wait_until(logged, description="'%s' in %s.log" % (text, program))

    def check_logs(self, allow=()):
        """Check the daemon logs of this node.  See ``check_logs()``."""
        __tracebackhide__ = True
        check_logs(self.test_dir, allow)

    def stop(self, check=True, log_allow=()):
        """Stop everything this node owns, in reverse order.

        Child nodes are stopped first, then background processes, then the
        daemons of this node, and then the tracked resources are closed.

        Args:
            check: Whether to check the daemon logs before stopping and to
                fail if a daemon doesn't stop cleanly, like
                ``OVS_VSWITCHD_STOP``.  Use False when the test already
                failed.
            log_allow: Additional regular expressions for ``check_logs()``.

        Raises:
            OVSError: if ``check`` is True and any of the checks failed.
                Everything is stopped regardless.
        """
        __tracebackhide__ = True
        errors = []

        if check and self.started:
            try:
                self.check_logs(log_allow)
            except OVSError as e:
                errors.append(str(e))

        for child in reversed(list(self._children)):
            try:
                child.stop(check=check, log_allow=log_allow)
            except OVSError as e:
                errors.append(str(e))
        self._children.clear()

        for proc in reversed(list(self._background)):
            proc.stop()

        for program, pidfile, target in reversed(self._daemons):
            problems = self._stop_daemon(program, pidfile, target)
            if check:
                errors += problems
        self._daemons.clear()

        for resource in reversed(self._resources):
            resource.close()
        self._resources.clear()

        if self._saved_env is not None:
            for var, value in self._saved_env.items():
                if value is None:
                    os.environ.pop(var, None)
                else:
                    os.environ[var] = value
            self._saved_env = None

        if self.parent is not None and self in self.parent._children:
            self.parent._children.remove(self)
        self.started = False

        if errors:
            raise OVSError("\n".join(errors))

    # Bridges.

    def add_bridge(self, name, *args, dpid=None, hwaddr=None):
        """Add a bridge with the usual test settings.

        The bridge uses ``dp_type``, fail-mode=secure and all OpenFlow
        versions.

        Args:
            name: Bridge name.
            *args: Additional ovs-vsctl commands, each a string, run in
                the same transaction.
            dpid: Optional datapath ID.
            hwaddr: Optional MAC address of the bridge.
        """
        settings = ["fail-mode=secure",
                    'protocols="[%s]"' % BRIDGE_PROTOCOLS]
        if self.dp_type:
            settings.insert(0, "datapath-type=" + self.dp_type)
        if dpid:
            settings.append("other-config:datapath-id=" + dpid)
        if hwaddr:
            settings.append("other-config:hwaddr=" + hwaddr)
        commands = ["add-br " + name,
                    "set bridge %s %s" % (name, " ".join(settings))]
        commands += args
        self.vsctl(" ".join("-- " + c for c in commands))


class OVSNodeDummy(OVSNode):
    """OVS with the dummy datapath, like ``OVS_VSWITCHD_START``.

    Needs no privileges and no real network devices.
    """

    dp_type = "dummy"

    def vswitchd_options(self):
        return ["--enable-dummy", "--disable-system",
                "--disable-system-route"] + super().vswitchd_options()

    def add_of_br(self, num, *args):
        """Add bridge 'br<num>' the same way as Autotest's add_of_br."""
        self.add_bridge("br%d" % num, *args,
                        dpid="fedcba987654321%d" % num,
                        hwaddr="aa:55:aa:55:00:0%d" % num)

    def add_of_ports(self, bridge, *numbers, pcap=False, pmd=False):
        """Add dummy ports 'p<number>' with OpenFlow port numbers
        ``numbers`` to ``bridge``, like Autotest's add_of_ports.

        Args:
            pcap: Record the received and transmitted packets of every port
                in 'p<number>-rx.pcap' and 'p<number>-tx.pcap'.
            pmd: Use ports polled by PMD threads, like add_pmd_of_ports.
        """
        args = []
        for n in numbers:
            args.append("-- add-port %s p%d -- set Interface p%d type=%s "
                        "ofport_request=%d" % (bridge, n, n, "dummy-pmd"
                                               if pmd else "dummy", n))
            if pcap:
                args.append("-- set Interface p%d options:rxq_pcap="
                            "p%d-rx.pcap options:tx_pcap=p%d-tx.pcap"
                            % (n, n, n))
        self.vsctl(" ".join(args))
