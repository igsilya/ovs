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

"""Process management helpers for OVS tests.

``BackgroundProcess`` runs a long-running command that stays in the
foreground (e.g., a test-l7.py server, tcpdump or nc), the equivalent of
``NETNS_DAEMONIZE`` and ``on_exit 'kill ...'`` in Autotest.  Daemons that
detach on their own and write a pidfile (ovsdb-server, ovs-vswitchd) are
handled by ``OVSNode`` instead.
"""

import os
import signal
import subprocess

from tests.lib.cmd import log_line, make_env, ns_name


def _cmdline(pid):
    """Return the command line arguments of process ``pid`` or None."""
    if os.path.isdir("/proc/self"):
        try:
            with open("/proc/%d/cmdline" % pid, "rb") as f:
                raw = f.read()
        except OSError:
            return None
        if not raw:
            # Zombies have an empty command line, but so does a process for
            # a moment while it executes a new program.
            try:
                with open("/proc/%d/stat" % pid) as f:
                    state = f.read().rsplit(")", 1)[1].split()[0]
                with open("/proc/%d/comm" % pid) as f:
                    comm = f.read().strip()
            except (OSError, IndexError):
                return None
            return None if state in ("Z", "X") else [comm]
        return [a.decode(errors="replace") for a in raw.split(b"\0") if a]

    result = subprocess.run(["ps", "-o", "args=", "-p", str(pid)],
                            stdout=subprocess.PIPE,
                            stderr=subprocess.DEVNULL,
                            universal_newlines=True)
    if result.returncode != 0 or not result.stdout.strip():
        return None
    return result.stdout.split()


def process_alive(pid, program=None):
    """Check whether process ``pid`` exists.

    If ``program`` is given, also check that it is running this program,
    i.e., that the PID was not reused by another process.  The program can
    be anywhere on the command line, so processes started under a wrapper
    such as valgrind are recognized as well.
    """
    args = _cmdline(pid)
    if args is None:
        return False
    if program is None:
        return True
    program = os.path.basename(program)
    return any(os.path.basename(arg) == program for arg in args)


def _signal_group(pgid, sig):
    try:
        os.killpg(pgid, sig)
    except (ProcessLookupError, PermissionError):
        pass


class BackgroundProcess:
    """A command running in the background for the duration of a test.

    The command runs in a shell in its own process group, and ``stop()``
    terminates the whole group.  If an ``owner`` is given, the process is
    added to its ``_background`` list, so the owner can stop it during its
    cleanup, and removed from it when stopped.

    Can be used as a context manager::

        with BackgroundProcess("tcpdump -i p0 -w p0.pcap", ns=ns0):
            ...
    """

    def __init__(self, cmd, ns=None, stdout=None, stderr=None, owner=None,
                 env=None):
        """Start ``cmd``.

        Args:
            cmd: Shell command string.
            ns: Network namespace to run the command in.
            stdout: File name for stdout, or None for /dev/null.
            stderr: File name for stderr, or None for /dev/null.
            owner: Object with a ``_background`` list that tracks this
                process, typically an ``OVSNode``.
            env: Optional dict of environment variables to set for the
                command, in addition to the current environment.
        """
        ns = ns_name(ns)
        self.cmd = "ip netns exec %s %s" % (ns, cmd) if ns else cmd
        self._owner = owner

        log_line("$ %s &" % self.cmd)
        out = open(stdout, "w") if stdout else subprocess.DEVNULL
        err = open(stderr, "w") if stderr else subprocess.DEVNULL
        try:
            self._proc = subprocess.Popen(self.cmd, shell=True,
                                          stdin=subprocess.DEVNULL,
                                          stdout=out, stderr=err,
                                          start_new_session=True,
                                          env=make_env(env))
        finally:
            for f in (out, err):
                if f is not subprocess.DEVNULL:
                    f.close()
        log_line("   pid: %d" % self._proc.pid, location=False)

        if owner is not None:
            owner._background.append(self)

    @property
    def pid(self):
        return self._proc.pid

    @property
    def returncode(self):
        return self._proc.poll()

    def alive(self):
        return self._proc.poll() is None

    def wait(self, timeout=None):
        """Wait for the process to exit and return its exit code."""
        return self._proc.wait(timeout)

    def stop(self, timeout=5):
        """Terminate the process group.

        Sends SIGTERM and then SIGKILL if the process doesn't exit within
        ``timeout`` seconds.  Does nothing if the process already exited.
        Returns the exit code.
        """
        if self._proc.poll() is None:
            log_line("$ kill %d  # %s" % (self._proc.pid, self.cmd))
            _signal_group(self._proc.pid, signal.SIGTERM)
            try:
                self._proc.wait(timeout)
            except subprocess.TimeoutExpired:
                log_line("   pid %d did not exit, sending SIGKILL"
                         % self._proc.pid, location=False)
                _signal_group(self._proc.pid, signal.SIGKILL)
                self._proc.wait()
            # Other processes of the group may survive the shell, e.g., if
            # they ignore SIGTERM.  The PID of the shell was just reaped and
            # PIDs are allocated sequentially, so it is not reused yet.
            _signal_group(self._proc.pid, signal.SIGKILL)

        if self._owner is not None and self in self._owner._background:
            self._owner._background.remove(self)
        return self._proc.returncode

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop()
        return False

    def __repr__(self):
        return "BackgroundProcess(pid=%d, %s, %r)" % (
            self._proc.pid, "running" if self.alive() else "exited",
            self.cmd)
