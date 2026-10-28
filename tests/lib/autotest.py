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

"""Running Autotest tests from pytest.

Starting an Autotest testsuite takes a noticeable fraction of a second,
which adds up over thousands of tests.  So instead of starting the
testsuite for every test, ``AutotestServer`` keeps one instance running
and feeds it test numbers.

For that, it creates a copy of the generated testsuite with a small
"server" loop inserted right before the driver loop, and extracts the
bodies of all the tests into separate files.  The loop reads test numbers,
runs each test the same way the serial driver loop does, and reports the
result.  The copy is named after the pytest worker (e.g.,
'testsuite.gw0'), and Autotest names its log file and directory after
the script, so every worker has its own 'testsuite.gw0.dir' and
'testsuite.gw0.log', as if it was a separate testsuite.
"""

import os
import re
import shutil
import subprocess

import pytest

from tests.lib.cmd import log_line

# Protocol marker printed by the server loop.
_MARKER = "@AT_SERVER@"

# The server loop.  Inserted after the "Driver loop." text box.  The test
# number is read from fd 6 and the tests get /dev/null as stdin, so a test
# reading from stdin doesn't interfere with the protocol.
_SERVER_LOOP = r"""
# Server mode for running tests one by one from pytest (tests/lib/autotest.py).
# Test bodies are pre-extracted into files in $at_server, named by number.
if test -n "$at_server"; then
  exec 6<&0 </dev/null
@SETUP@
  echo "@AT_SERVER@ ready"
  while read at_group <&6; do
    case $at_group in
      ''|*[!0-9]*) break ;;
    esac
    if test ! -f "$at_server/$at_group"; then
      echo "@AT_SERVER@ result $at_group unknown - -"
      continue
    fi
    mkdir -p "$at_helper_dir/$at_group"
    at_fn_group_prepare
    if cd "$at_group_dir" &&
       . "$at_server/$at_group"; then :; else
      echo "$as_me: WARNING: unable to parse test group: $at_group" >&2
      at_failed=:
    fi
    at_fn_group_postprocess
    at_check_line=`cat "$at_check_line_file" 2>/dev/null`
    echo "@AT_SERVER@ result $at_group $at_res ${at_check_line:--}" \
         "$at_group_dir"
    at_first=false
  done
  cd "$at_dir"
  rm -rf "$at_helper_dir"
  exit 0
fi
"""

_DRIVER_LOOP_BOX = "## Driver loop. ##"


class AutotestError(AssertionError):
    pass


def list_tests(testsuite, rundir, flags=()):
    """Return the tests of an Autotest testsuite.

    Args:
        testsuite: Path to the generated testsuite script.
        rundir: Directory with atconfig and atlocal.
        flags: Additional Autotest flags, e.g., test numbers or
            keywords to select a subset of tests.

    Returns:
        A list of (number, location, name) tuples.
    """
    result = subprocess.run(
        ["/bin/sh", testsuite, "-C", rundir, "--list"] + list(flags),
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        universal_newlines=True)
    if result.returncode != 0:
        raise AutotestError("%s --list failed:\n%s"
                            % (testsuite, result.stderr))
    tests = []
    for line in result.stdout.splitlines():
        m = re.match(r"^\s*(\d+): (\S+)\s+(.*?)\s*$", line)
        if m:
            tests.append((int(m.group(1)), m.group(2), m.group(3)))
    return tests


def make_server_script(testsuite, path, setup=""):
    """Prepare a server copy of ``testsuite`` at ``path``.

    Writes a copy of the testsuite with the server loop, and the bodies
    of all its tests into directory '<path>.d', one file per test, named
    by test number.  A test body is what Autotest itself extracts from the
    testsuite before running a test: everything between the '#AT_START_N'
    and '#AT_STOP_N' lines.

    ``setup`` is shell code to run in the server before the first test.
    Shell functions defined there are available to the tests.
    """
    # The testsuite is not necessarily valid UTF-8, it contains test data.
    with open(testsuite, "rb") as f:
        lines = f.readlines()

    bodies_dir = path + ".d"
    shutil.rmtree(bodies_dir, ignore_errors=True)
    os.mkdir(bodies_dir)
    loop_index = None
    body = None
    for i, line in enumerate(lines):
        if line.startswith(b"#AT_START_"):
            body = []
        elif line.startswith(b"#AT_STOP_"):
            number = int(line[len(b"#AT_STOP_"):])
            with open(os.path.join(bodies_dir, str(number)), "wb") as f:
                f.writelines(body)
            body = None
        elif body is not None:
            body.append(line)
        elif loop_index is None \
                and line.rstrip(b"\n") == _DRIVER_LOOP_BOX.encode():
            # Insert after the closing line of the text box.
            loop_index = i + 2
    if loop_index is None:
        raise AutotestError("%s: no '%s' found, unsupported Autotest version"
                            % (testsuite, _DRIVER_LOOP_BOX))

    loop = _SERVER_LOOP.replace("@SETUP@", setup or "  :")
    lines.insert(loop_index, loop.encode())
    with open(path + ".tmp", "wb") as f:
        f.writelines(lines)
    os.chmod(path + ".tmp", 0o755)
    os.rename(path + ".tmp", path)
    return bodies_dir


class AutotestServer:
    """A running Autotest testsuite that executes tests on request.

    The server process is started on creation.  It can also be stopped
    and started again with ``stop()`` and ``start()``, e.g., to run tests
    in different network namespaces, without preparing the server script
    again.

    Args:
        testsuite: Path to the generated testsuite script.
        rundir: Directory with atconfig and atlocal.  The server script,
            its log and its directory are created there.
        name: Name for the server script, e.g., 'testsuite.gw0'.
        flags: Additional Autotest flags.
        setup: Shell code to run in the server before the first test.
    """

    def __init__(self, testsuite, rundir, name, flags=(), setup=""):
        self.rundir = rundir = os.path.abspath(rundir)
        self.name = name
        self.script = os.path.join(rundir, name)
        self.suite_dir = self.script + ".dir"
        self.suite_log = self.script + ".log"
        self.failed = False

        self.bodies_dir = make_server_script(os.path.abspath(testsuite),
                                             self.script, setup)
        self._cmd = ["/bin/sh", self.script, "-C", rundir,
                     "at_server=" + self.bodies_dir]
        if os.environ.get("AUTOTEST_PATH"):
            self._cmd.append("AUTOTEST_PATH=" + os.environ["AUTOTEST_PATH"])
        self._cmd += list(flags)
        # The server runs tests from self.bodies_dir.  Select a single test,
        # so Autotest doesn't prepare for running all of them (scanning the
        # whole script for test boundaries, keeping them in variables,
        # creating helper directories), it would only slow things down.
        self._cmd.append("1")
        self._proc = None
        self.check_line = None
        self.start()

    def start(self):
        """Start the server process, if it is not running."""
        if self.alive():
            return
        log_line("$ " + " ".join(self._cmd))
        self._proc = subprocess.Popen(self._cmd, stdin=subprocess.PIPE,
                                      stdout=subprocess.PIPE,
                                      universal_newlines=True)
        self._read_until(_MARKER + " ready")

    def stop(self):
        """Stop the server process."""
        if self._proc is None:
            return
        if self._proc.poll() is None:
            try:
                self._proc.stdin.close()
            except OSError:
                pass
            try:
                self._proc.wait(timeout=30)
            except subprocess.TimeoutExpired:
                self._proc.kill()
                self._proc.wait()
        self._proc.stdout.close()
        self._proc = None

    def _read_until(self, prefix):
        """Read the server output until a line starting with ``prefix``."""
        while True:
            line = self._proc.stdout.readline()
            if not line:
                self._proc.wait()
                raise AutotestError(
                    "Autotest server %s exited unexpectedly (status %s)"
                    % (self.name, self._proc.returncode))
            if line.startswith(prefix):
                return line.rstrip("\n")

    def alive(self):
        return self._proc is not None and self._proc.poll() is None

    def run(self, number):
        """Run test ``number``.

        Returns:
            A tuple (result, group_dir), where result is one of 'pass',
            'skip', 'xfail', 'xpass' or 'fail', and group_dir is the
            directory of the test.  The directory of a passed or skipped
            test is already removed, unless -d was given.  The location of
            the last check of the test, e.g., the one that skipped it, is
            stored in ``check_line``.
        """
        self._proc.stdin.write("%d\n" % number)
        self._proc.stdin.flush()
        line = self._read_until("%s result %d " % (_MARKER, number))
        result, check_line, group_dir = line.split(None, 5)[3:]
        self.check_line = check_line if check_line != "-" else None
        if result == "unknown":
            raise AutotestError("Unknown Autotest test %d" % number)
        if result not in ("pass", "skip", "xfail"):
            self.failed = True
        return result, group_dir

    def close(self, keep=False):
        """Stop the server and clean up.

        Removes the server script, and also the log and the directory of
        the testsuite if no test failed and ``keep`` is False.
        """
        self.stop()
        os.unlink(self.script)
        shutil.rmtree(self.bodies_dir, ignore_errors=True)
        if not keep and not self.failed:
            shutil.rmtree(self.suite_dir, ignore_errors=True)
            if os.path.exists(self.suite_log):
                os.unlink(self.suite_log)


def group_log(group_dir, name):
    """Return the contents of the log of a test in ``group_dir``."""
    try:
        with open(os.path.join(group_dir, name + ".log"),
                  errors="replace") as f:
            return f.read()
    except OSError:
        return ""


class AutotestSuite:
    """An Autotest testsuite whose tests are run as pytest tests.

    Usage in a test module::

        SUITE = AutotestSuite(path_to_testsuite, rundir)

        @SUITE.parametrize
        def test_autotest(autotest_runner, number):
            SUITE.run(autotest_runner, number)

    where ``autotest_runner`` is a session-scoped fixture returning
    ``SUITE.runner(request)``.

    Args:
        testsuite: Path to the generated testsuite script.
        rundir: Directory with atconfig and atlocal.
        marks: pytest marks for all the tests.
        setup: Shell code to run in the testsuite before the first test,
            see ``AutotestServer``.
        process_per_test: Run every test in a new testsuite process,
            started from the test.  Needed if tests run in different
            environments, e.g., network namespaces.  Otherwise, a single
            process runs all the tests of a pytest worker.
    """

    def __init__(self, testsuite, rundir, marks=(), setup="",
                 process_per_test=False):
        self.testsuite = testsuite
        self.rundir = rundir
        self.marks = list(marks)
        self.setup = setup
        self.process_per_test = process_per_test
        self._tests = None

    def available(self):
        return os.path.isfile(self.testsuite) \
            and os.path.isfile(os.path.join(self.rundir, "atconfig"))

    def tests(self):
        """Return the tests as a {number: (location, name)} dict."""
        if self._tests is None:
            self._tests = {}
            if self.available():
                for number, location, name in list_tests(self.testsuite,
                                                         self.rundir):
                    self._tests[number] = (location, name)
        return self._tests

    def params(self):
        """Return a list of pytest.param objects for the tests."""
        params = []
        for number, (location, name) in sorted(self.tests().items()):
            safe_name = re.sub(r"[^A-Za-z0-9_.=+-]+", "_", name).strip("_")
            params.append(pytest.param(number, marks=self.marks,
                                       id="%04d-%s" % (number, safe_name)))
        return params

    def parametrize(self, fn):
        """Decorator that parametrizes a test with the Autotest tests."""
        return pytest.mark.parametrize("number", self.params())(fn)

    def runner(self, request):
        """Generator for a session-scoped fixture that runs the tests."""
        runner = _Runner(self, request.config.getoption("keep_artifacts"))
        yield runner
        runner.close()

    def run(self, runner, number):
        """Run test ``number`` and report its result to pytest."""
        __tracebackhide__ = True
        location, name = self.tests()[number]
        result, group_dir = runner.run(number)
        check_line = runner.server.check_line or location
        if result == "skip":
            pytest.skip("skipped by Autotest (%s)" % check_line)
        elif result == "xfail":
            pytest.xfail("expected failure (%s)" % check_line)
        elif result != "pass":
            msg = "Autotest test %d (%s) %s: %s" % (
                number, location,
                "passed unexpectedly" if result == "xpass" else "failed",
                name)
            msg += "\nTest directory: %s" % group_dir
            msg += "\n\n" + group_log(group_dir, runner.name)
            pytest.fail(msg, pytrace=False)


class _Runner:
    """Starts an AutotestServer when needed and restarts it if it dies."""

    def __init__(self, suite, keep):
        worker = os.environ.get("PYTEST_XDIST_WORKER", "pytest")
        self.name = "%s.%s" % (os.path.basename(suite.testsuite), worker)
        self.suite = suite
        self.keep = keep
        # With -d, Autotest keeps directories of successful tests.
        self.flags = ["-d"] if keep else []
        self.server = None
        self.failed = False

    def run(self, number):
        if self.suite.process_per_test:
            if self.server is None:
                self.server = AutotestServer(self.suite.testsuite,
                                             self.suite.rundir, self.name,
                                             self.flags, self.suite.setup)
            else:
                self.server.start()
            try:
                return self.server.run(number)
            finally:
                self.server.stop()

        if self.server is None or not self.server.alive():
            if self.server is not None:
                self.failed = True
                self.server.close(keep=True)
            self.server = AutotestServer(self.suite.testsuite,
                                         self.suite.rundir, self.name,
                                         self.flags, self.suite.setup)
        return self.server.run(number)

    def close(self):
        if self.server is not None:
            self.server.close(keep=self.keep or self.failed)
            self.server = None
