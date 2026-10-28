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

"""Command execution and wait primitives for OVS tests.

``run()`` replaces the Autotest ``AT_CHECK`` macro, and ``wait_until()``,
``wait_while()`` and ``wait_until_equal()`` replace ``OVS_WAIT_UNTIL``,
``OVS_WAIT_WHILE`` and ``OVS_WAIT_UNTIL_EQUAL``.

Every command is logged to the ``ovs.test`` logger together with the
source location of the test code that issued it, so the per-test log
reads like the Autotest transcript.
"""

import difflib
import inspect
import logging
import os
import signal
import subprocess
import sys
import tempfile
import time

log = logging.getLogger("ovs.test")

# Width of the source location column in log output.
LOC_WIDTH = 20
LOC_PAD = " " * LOC_WIDTH

# Library directories skipped when looking for the caller's location.
_LIB_DIRS = (
    os.sep + os.path.join("tests", "lib") + os.sep,
    os.sep + os.path.join("tests", "system", "lib") + os.sep,
)


def ctl_timeout():
    """Return the default timeout for OVS control commands and waits.

    Matches ``OVS_CTL_TIMEOUT`` from ``tests/atlocal.in``.
    """
    try:
        return int(os.environ.get("OVS_CTL_TIMEOUT", "30"))
    except ValueError:
        return 30


def caller_location():
    """Return ``"file.py:line"`` of the closest caller outside the library.

    Returns an empty string if no such frame is found.
    """
    frame = sys._getframe(1)
    while frame is not None:
        filename = frame.f_code.co_filename
        if not any(d in filename for d in _LIB_DIRS):
            return "%s:%d" % (os.path.basename(filename), frame.f_lineno)
        frame = frame.f_back
    return ""


def log_line(msg, location=True, level=logging.INFO):
    """Log ``msg`` with the source location column.

    If ``location`` is False, the location column is left blank, which is
    used for continuation lines.
    """
    loc = caller_location() if location else ""
    log.log(level, "%s %s", loc.ljust(LOC_WIDTH), msg)


def ns_name(ns):
    """Return the name of a network namespace.

    ``ns`` can be None, a string, or an object with a ``name`` attribute.
    """
    if ns is None or isinstance(ns, str):
        return ns
    return ns.name


class CommandError(AssertionError):
    """Base class for command execution failures."""


class CommandFailed(CommandError):
    """Raised when a command exits with an unexpected return code."""

    def __init__(self, cmd, expected_rc, result):
        super().__init__(cmd, expected_rc, result)
        self.cmd = cmd
        self.expected_rc = expected_rc
        self.result = result

    def __str__(self):
        msg = ["Command failed: %s" % self.cmd,
               "  expected exit code: %s" % self.expected_rc,
               "  actual exit code:   %s" % self.result.returncode]
        if self.result.stdout:
            msg.append("  stdout:\n" + _indent(self.result.stdout, 4))
        if self.result.stderr:
            msg.append("  stderr:\n" + _indent(self.result.stderr, 4))
        return "\n".join(msg)


class OutputMismatch(CommandError):
    """Raised when command output doesn't match the expected value."""

    def __init__(self, cmd, stream, expected, actual):
        super().__init__(cmd, stream, expected, actual)
        self.cmd = cmd
        self.stream = stream
        self.expected = expected
        self.actual = actual

    def __str__(self):
        if self.expected is False:
            return "Unexpected %s from: %s\n%s" % (
                self.stream, self.cmd, _indent(self.actual, 2))

        expected = self.expected
        if isinstance(expected, str):
            expected = expected.splitlines()
        diff = difflib.unified_diff(expected, self.actual.splitlines(),
                                    "expected", "actual", lineterm="")
        return "Unexpected %s from: %s\n%s" % (
            self.stream, self.cmd, _indent("\n".join(diff), 2))


class WaitTimeout(AssertionError):
    """Raised when a wait primitive times out."""

    def __init__(self, description, timeout):
        super().__init__(description, timeout)
        self.description = description
        self.timeout = timeout

    def __str__(self):
        return "Timed out after %ss: %s" % (self.timeout, self.description)


def _indent(text, n):
    pad = " " * n
    return "\n".join(pad + line for line in text.rstrip("\n").splitlines())


def _output_matches(spec, actual):
    if spec is True:
        return True
    if spec is False:
        return actual == ""
    if isinstance(spec, str):
        return actual == spec
    return actual.splitlines() == list(spec)


def _kill_group(pgid):
    try:
        os.killpg(pgid, signal.SIGKILL)
    except ProcessLookupError:
        pass


def make_env(env):
    """Return the process environment updated with ``env``, or None."""
    if not env:
        return None
    full_env = dict(os.environ)
    full_env.update(env)
    return full_env


def _execute(cmd, timeout, env=None):
    """Run ``cmd`` in a shell and return a CompletedProcess.

    The command runs in its own process group, so on timeout the whole
    pipeline is killed, not only the shell.  The output goes to temporary
    files, not pipes, and only the shell is waited for, like with AT_CHECK,
    so processes that the command leaves running in the background with
    its output still open, e.g., under strace, don't block it.
    """
    with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
        proc = subprocess.Popen(cmd, shell=True, stdout=out, stderr=err,
                                start_new_session=True, env=make_env(env))
        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            _kill_group(proc.pid)
            proc.wait()
            log_line("   killed after %ss timeout" % timeout, location=False,
                     level=logging.ERROR)
            raise subprocess.TimeoutExpired(cmd, timeout, _read(out),
                                            _read(err))
        except BaseException:
            _kill_group(proc.pid)
            proc.wait()
            raise
        return subprocess.CompletedProcess(cmd, proc.returncode, _read(out),
                                           _read(err))


def _read(f):
    f.seek(0)
    return f.read().decode(errors="replace")


def run(cmd, rc=0, stdout=False, stderr=False, ns=None, timeout=None,
        env=None):
    """Execute a shell command and check its result.

    A bare ``run("cmd")`` requires exit code 0, empty stdout and empty
    stderr, matching the default ``AT_CHECK([cmd])`` behavior.

    Args:
        cmd: Shell command string.
        rc: Expected exit code, or None to accept any.
        stdout: Expected stdout:
            False -- must be empty (default),
            True -- anything is accepted,
            str -- must match exactly,
            list of str -- must match line by line.
        stderr: Expected stderr, same semantics as ``stdout``.
        ns: Network namespace to run the command in (via
            ``ip netns exec``).  A name or an object with ``name``.
        timeout: Optional timeout in seconds for the command.
        env: Optional dict of environment variables to set for the
            command, in addition to the current environment.

    Returns:
        subprocess.CompletedProcess with text stdout and stderr.

    Raises:
        CommandFailed: if the exit code doesn't match ``rc``.
        OutputMismatch: if stdout or stderr doesn't match.
    """
    __tracebackhide__ = True

    ns = ns_name(ns)
    full_cmd = "ip netns exec %s %s" % (ns, cmd) if ns else cmd

    log_line("$ " + full_cmd)
    indent = "   "
    result = _execute(full_cmd, timeout, env)
    if result.returncode != 0:
        log_line(indent + "exit: %d" % result.returncode, location=False)
    for name in ("stdout", "stderr"):
        output = getattr(result, name)
        if output:
            log_line(indent + name + ":", location=False)
            for line in output.rstrip("\n").splitlines():
                log_line(indent + "    " + line, location=False)

    if rc is not None and result.returncode != rc:
        raise CommandFailed(full_cmd, rc, result)
    if not _output_matches(stdout, result.stdout):
        raise OutputMismatch(full_cmd, "stdout", stdout, result.stdout)
    if not _output_matches(stderr, result.stderr):
        raise OutputMismatch(full_cmd, "stderr", stderr, result.stderr)

    return result


def _describe_callable(fn):
    """Return a short description of ``fn`` for log and error messages."""
    try:
        lines, lineno = inspect.getsourcelines(fn)
        return "%s:%d: %s" % (os.path.basename(inspect.getfile(fn)),
                              lineno, lines[0].strip())
    except (OSError, TypeError, IndexError):
        return repr(fn)


def wait_until(fn, timeout=None, description=None):
    """Poll ``fn`` until it returns a true value.

    Replaces the Autotest ``OVS_WAIT_UNTIL`` macro.

    Args:
        fn: Callable to poll.
        timeout: Maximum time in seconds.  Defaults to ``ctl_timeout()``.
        description: Description for log and error messages.  Defaults
            to the source line of ``fn``.

    Returns:
        The true value returned by ``fn``.

    Raises:
        WaitTimeout: if ``fn`` doesn't return a true value in time.
    """
    __tracebackhide__ = True

    if timeout is None:
        timeout = ctl_timeout()
    desc = description or _describe_callable(fn)
    log_line("wait_until (timeout=%ss): %s" % (timeout, desc))

    start = time.monotonic()
    deadline = start + timeout
    delay = 0.001
    while True:
        result = fn()
        if result:
            log_line("   wait_until: succeeded after %.3fs"
                     % (time.monotonic() - start), location=False)
            return result
        if time.monotonic() >= deadline:
            break
        time.sleep(min(delay, max(deadline - time.monotonic(), 0)))
        delay = min(delay * 2, 0.5)

    log_line("   wait_until: timed out after %ss" % timeout,
             location=False, level=logging.ERROR)
    raise WaitTimeout(desc, timeout)


def wait_while(fn, timeout=None, description=None):
    """Poll ``fn`` until it returns a false value.

    Replaces the Autotest ``OVS_WAIT_WHILE`` macro.

    Raises:
        WaitTimeout: if ``fn`` doesn't return a false value in time.
    """
    __tracebackhide__ = True

    desc = "not (%s)" % (description or _describe_callable(fn))
    wait_until(lambda: not fn(), timeout=timeout, description=desc)


def apply_filters(text, filters):
    """Apply a filter or a list of filters to ``text`` in sequence."""
    if filters is None:
        return text
    if callable(filters):
        filters = [filters]
    for fn in filters:
        text = fn(text)
    return text


def wait_until_equal(cmd, expected, ns=None, timeout=None, filters=None):
    """Run ``cmd`` until its filtered stdout matches ``expected``.

    Replaces the Autotest ``OVS_WAIT_UNTIL_EQUAL`` macro.

    Args:
        cmd: Shell command string.
        expected: Expected output, a str or a list of lines.
        ns: Optional network namespace.
        timeout: Maximum time in seconds.  Defaults to ``ctl_timeout()``.
        filters: A callable or a list of callables applied to stdout
            before comparison, e.g., ``grep_lines()`` or ``sort_lines``.

    Raises:
        WaitTimeout: if the output doesn't match in time.
    """
    __tracebackhide__ = True

    last = []

    def check():
        r = run(cmd, rc=None, stdout=True, stderr=True, ns=ns)
        last[:] = [apply_filters(r.stdout, filters)]
        return r.returncode == 0 and _output_matches(expected, last[0])

    try:
        wait_until(check, timeout=timeout,
                   description="output of '%s' matches" % cmd)
    except WaitTimeout as e:
        if last:
            e.description += "\n" + str(
                OutputMismatch(cmd, "stdout", expected, last[0]))
        raise


def grep_lines(pattern):
    """Return a filter that keeps only lines containing ``pattern``."""
    def _filter(text):
        lines = [line for line in text.splitlines() if pattern in line]
        return "".join(line + "\n" for line in lines)

    _filter.__name__ = "grep_lines(%r)" % pattern
    return _filter


def sort_lines(text):
    """Filter that sorts lines alphabetically."""
    return "".join(line + "\n" for line in sorted(text.splitlines()))
