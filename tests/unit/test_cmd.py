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

"""Tests for tests.lib.cmd."""

import logging
import os
import time

import pytest

from tests.lib.cmd import (
    CommandFailed,
    OutputMismatch,
    WaitTimeout,
    caller_location,
    grep_lines,
    ns_name,
    run,
    sort_lines,
    wait_until,
    wait_until_equal,
    wait_while,
)


class TestRun:
    def test_silent_command(self):
        r = run("true")
        assert r.returncode == 0

    def test_expected_rc(self):
        run("exit 28", rc=28)

    def test_rc_none(self):
        assert run("exit 3", rc=None).returncode == 3

    def test_unexpected_rc(self):
        with pytest.raises(CommandFailed) as e:
            run("echo out; echo err >&2; exit 2", stdout=True, stderr=True)
        assert e.value.result.returncode == 2
        assert "expected exit code: 0" in str(e.value)
        assert "out" in str(e.value) and "err" in str(e.value)

    def test_unexpected_rc_with_rc(self):
        with pytest.raises(CommandFailed):
            run("true", rc=1)

    def test_stdout_ignored(self):
        assert run("echo hello", stdout=True).stdout == "hello\n"

    def test_stdout_str(self):
        run("printf 'a\\nb\\n'", stdout="a\nb\n")
        with pytest.raises(OutputMismatch):
            run("printf 'a\\nb'", stdout="a\nb\n")

    def test_stdout_lines(self):
        run("printf 'a\\nb\\n'", stdout=["a", "b"])
        run("printf 'a\\nb'", stdout=["a", "b"])
        run("true", stdout=[])

    def test_unexpected_stdout(self):
        with pytest.raises(OutputMismatch) as e:
            run("echo oops")
        assert "Unexpected stdout" in str(e.value)
        assert "oops" in str(e.value)

    def test_unexpected_stderr(self):
        with pytest.raises(OutputMismatch) as e:
            run("echo oops >&2")
        assert "Unexpected stderr" in str(e.value)

    def test_stderr_lines(self):
        run("echo err >&2; exit 1", rc=1, stderr=["err"])

    def test_mismatch_shows_diff(self):
        with pytest.raises(OutputMismatch) as e:
            run("printf 'a\\nb\\nc\\n'", stdout=["a", "x", "c"])
        msg = str(e.value)
        assert "-x" in msg and "+b" in msg

    def test_rc_checked_before_output(self):
        with pytest.raises(CommandFailed):
            run("echo oops; exit 1")

    def test_timeout(self):
        with pytest.raises(Exception) as e:
            run("sleep 5 | cat", timeout=0.1)
        assert "timed out" in str(e.value)

    def test_background_process_keeps_output(self):
        # Like AT_CHECK, only the command itself is waited for, not the
        # processes it leaves in the background with its output open.
        start = time.monotonic()
        r = run("sleep 3 & echo started", stdout="started\n")
        assert time.monotonic() - start < 2
        assert r.returncode == 0

    def test_ns(self, monkeypatch):
        commands = []

        def fake_execute(cmd, timeout, env):
            commands.append(cmd)
            raise RuntimeError("stop")

        monkeypatch.setattr("tests.lib.cmd._execute", fake_execute)

        class NS:
            name = "ns1"

        for ns in ("ns0", NS()):
            with pytest.raises(RuntimeError):
                run("true", ns=ns)
        assert commands == ["ip netns exec ns0 true",
                            "ip netns exec ns1 true"]

    def test_env(self, monkeypatch):
        monkeypatch.setenv("OVS_TEST_A", "a")
        run("echo $OVS_TEST_A $OVS_TEST_B", stdout=["a b"],
            env={"OVS_TEST_B": "b"})
        run("echo $OVS_TEST_A", stdout=["c"], env={"OVS_TEST_A": "c"})
        assert "OVS_TEST_B" not in os.environ

    def test_logging(self, caplog):
        with caplog.at_level(logging.INFO, logger="ovs.test"):
            run("echo out; echo err >&2; exit 3", rc=3,
                stdout=True, stderr=True)
        lines = [r.getMessage() for r in caplog.records]
        loc = "test_cmd.py:"
        assert lines[0].startswith(loc)
        assert lines[0].endswith(
            "$ echo out; echo err >&2; exit 3")
        assert lines[1].strip() == "exit: 3"
        assert [line.strip() for line in lines[2:]] == [
            "stdout:", "out", "stderr:", "err"]
        # Continuation lines are aligned after the location column.
        assert not lines[1].startswith(loc)


class TestHelpers:
    def test_ns_name(self):
        class NS:
            name = "x"

        assert ns_name(None) is None
        assert ns_name("y") == "y"
        assert ns_name(NS()) == "x"

    def test_caller_location(self):
        line = caller_location()
        assert line.startswith(os.path.basename(__file__) + ":")


class TestWait:
    def test_wait_until_immediate(self):
        assert wait_until(lambda: 42, timeout=1) == 42

    def test_wait_until_delayed(self):
        start = time.monotonic()
        wait_until(lambda: time.monotonic() - start > 0.2, timeout=5)

    def test_wait_until_timeout(self):
        start = time.monotonic()
        with pytest.raises(WaitTimeout) as e:
            wait_until(lambda: False, timeout=0.3, description="never")
        assert "never" in str(e.value)
        assert 0.3 <= time.monotonic() - start < 2

    def test_wait_until_describes_lambda(self):
        with pytest.raises(WaitTimeout) as e:
            wait_until(lambda: 1 == 2, timeout=0.1)
        assert "1 == 2" in str(e.value)

    def test_wait_while(self):
        wait_while(lambda: False, timeout=1)
        with pytest.raises(WaitTimeout) as e:
            wait_while(lambda: True, timeout=0.1, description="forever")
        assert "not (forever)" in str(e.value)

    def test_wait_until_equal(self):
        wait_until_equal("echo hello", ["hello"], timeout=1)
        wait_until_equal("echo hello", "hello\n", timeout=1)

    def test_wait_until_equal_retries(self, tmp_path):
        f = tmp_path / "file"
        start = time.monotonic()

        def cmd_output():
            if time.monotonic() - start > 0.2:
                f.write_text("ready\n")
            return True

        wait_until(lambda: cmd_output() and f.exists(), timeout=5)
        wait_until_equal("cat %s" % f, ["ready"], timeout=1)

    def test_wait_until_equal_timeout(self):
        with pytest.raises(WaitTimeout) as e:
            wait_until_equal("echo wrong", ["right"], timeout=0.1)
        assert "-right" in str(e.value) and "+wrong" in str(e.value)

    def test_wait_until_equal_failing_command(self):
        with pytest.raises(WaitTimeout):
            wait_until_equal("echo right; exit 1", ["right"], timeout=0.1)

    def test_wait_until_equal_filters(self):
        wait_until_equal("printf 'c\\nb\\na\\nb\\n'", ["b", "b"],
                         filters=grep_lines("b"), timeout=1)
        wait_until_equal("printf 'c1\\nb\\na1\\n'", ["a1", "c1"],
                         filters=[grep_lines("1"), sort_lines], timeout=1)


class TestFilters:
    def test_grep_lines(self):
        assert grep_lines("foo")("foo 1\nbar\nfoo 2\n") == "foo 1\nfoo 2\n"
        assert grep_lines("x")("foo\n") == ""

    def test_sort_lines(self):
        assert sort_lines("c\na\nb\n") == "a\nb\nc\n"
        assert sort_lines("") == ""
