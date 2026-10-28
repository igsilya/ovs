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

"""Tests for tests.lib.process."""

import os
import sys
import time

import pytest

from tests.lib import process
from tests.lib.cmd import wait_until
from tests.lib.process import BackgroundProcess, process_alive


class Owner:
    def __init__(self):
        self._background = []


class TestBackgroundProcess:
    def test_start_stop(self):
        proc = BackgroundProcess("sleep 30")
        assert proc.alive()
        assert process_alive(proc.pid)
        proc.stop()
        assert not proc.alive()
        assert not process_alive(proc.pid)

    def test_stop_kills_whole_group(self):
        proc = BackgroundProcess("sleep 30 & echo $! > child.pid; wait")
        wait_until(lambda: os.path.exists("child.pid")
                   and open("child.pid").read().strip(), timeout=5)
        child = int(open("child.pid").read())
        wait_until(lambda: process_alive(child, "sleep"), timeout=5)
        proc.stop()
        wait_until(lambda: not process_alive(child), timeout=5)

    def test_stop_ignoring_sigterm(self):
        proc = BackgroundProcess("trap '' TERM; sleep 30 & wait")
        time.sleep(0.2)
        start = time.monotonic()
        proc.stop(timeout=0.5)
        assert time.monotonic() - start < 5
        assert not proc.alive()

    def test_already_exited(self):
        proc = BackgroundProcess("exit 3")
        assert proc.wait(timeout=5) == 3
        assert proc.stop() == 3

    def test_context_manager(self):
        with BackgroundProcess("sleep 30") as proc:
            assert proc.alive()
        assert not proc.alive()

    def test_owner(self):
        owner = Owner()
        p1 = BackgroundProcess("sleep 30", owner=owner)
        p2 = BackgroundProcess("sleep 30", owner=owner)
        assert owner._background == [p1, p2]
        p1.stop()
        assert owner._background == [p2]
        p2.stop()
        p2.stop()
        assert owner._background == []

    def test_output_files(self):
        proc = BackgroundProcess("echo out; echo err >&2",
                                 stdout="out.txt", stderr="err.txt")
        proc.wait(timeout=5)
        assert open("out.txt").read() == "out\n"
        assert open("err.txt").read() == "err\n"

    def test_env(self):
        proc = BackgroundProcess("echo $OVS_TEST_A", stdout="out.txt",
                                 env={"OVS_TEST_A": "a"})
        proc.wait(timeout=5)
        assert open("out.txt").read() == "a\n"

    def test_ns(self, monkeypatch, caplog):
        monkeypatch.setattr("subprocess.Popen", None)

        class NS:
            name = "ns1"

        with pytest.raises(TypeError):
            BackgroundProcess("true", ns=NS())
        assert caplog.records[-1].getMessage().endswith(
            "$ ip netns exec ns1 true &")

    def test_logging(self, caplog):
        with BackgroundProcess("sleep 30") as proc:
            pass
        messages = [r.getMessage() for r in caplog.records]
        assert any(m.endswith("$ sleep 30 &") for m in messages)
        assert any("pid: %d" % proc.pid in m for m in messages)
        assert any("$ kill %d" % proc.pid in m for m in messages)


class TestProcessAlive:
    def test_self(self):
        assert process_alive(os.getpid())
        assert process_alive(os.getpid(), sys.executable)
        assert not process_alive(os.getpid(), "ovs-vswitchd")

    def test_nonexistent(self):
        proc = BackgroundProcess("exit 0")
        proc.wait(timeout=5)
        assert not process_alive(proc.pid)

    def test_wrapped_program(self):
        # The program is an argument of the wrapper, like with valgrind.
        with BackgroundProcess("exec %s -c 'import time; time.sleep(30)' "
                               "--some-option /path/to/ovs-vswitchd"
                               % sys.executable) as proc:
            wait_until(lambda: process_alive(proc.pid, "ovs-vswitchd"),
                       timeout=5)
            assert not process_alive(proc.pid, "ovsdb-server")

    def test_ps_fallback(self, monkeypatch):
        isdir = os.path.isdir
        monkeypatch.setattr(
            process.os.path, "isdir",
            lambda p: False if p == "/proc/self" else isdir(p))
        assert process_alive(os.getpid())
        assert process_alive(os.getpid(), sys.executable)
        assert not process_alive(os.getpid(), "ovs-vswitchd")
        with BackgroundProcess("exit 0") as proc:
            proc.wait(timeout=5)
        assert not process_alive(proc.pid)
