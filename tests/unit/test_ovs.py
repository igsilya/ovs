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

"""Tests for tests.lib.ovs."""

import os
import shutil
import signal

import pytest

from tests.lib.cmd import run, wait_until
from tests.lib.ovs import OVSError, OVSNodeDummy, check_logs, check_stderr
from tests.lib.process import process_alive

needs_ovs = pytest.mark.skipif(shutil.which("ovs-vswitchd") is None,
                               reason="OVS binaries are not in PATH")


def read_pid(node, program):
    with open(os.path.join(node.test_dir, program + ".pid")) as f:
        return int(f.read())


class TestCheckLogs:
    def write(self, path, name, text):
        with open(os.path.join(str(path), name), "w") as f:
            f.write(text)

    def test_clean(self, tmp_path):
        self.write(tmp_path, "a.log", "2026|00001|vlog|INFO|opened\n")
        check_logs(str(tmp_path))

    def test_unexpected(self, tmp_path):
        for level in ("WARN", "ERR", "EMER"):
            self.write(tmp_path, "a.log", "x|bridge|%s|bad thing\n" % level)
            with pytest.raises(OVSError) as e:
                check_logs(str(tmp_path))
            assert "a.log: x|bridge|%s|bad thing" % level in str(e.value)

    def test_builtin_allowed(self, tmp_path):
        self.write(tmp_path, "a.log",
                   "x|jsonrpc|WARN|unix: send error: Broken pipe\n"
                   "x|timeval|WARN|Unreasonably long 1234ms poll interval\n"
                   "x|vlog|WARN|Dropped 5 log messages in last 1 seconds\n")
        check_logs(str(tmp_path))

    def test_allow(self, tmp_path):
        self.write(tmp_path, "a.log", "x|bridge|WARN|could not open p1\n")
        check_logs(str(tmp_path), allow=[r"could not open p\d"])
        with pytest.raises(OVSError):
            check_logs(str(tmp_path), allow=["something else"])

    def test_skipped_files(self, tmp_path):
        self.write(tmp_path, "pytest.log", "x|bridge|WARN|logged command\n")
        self.write(tmp_path, "testsuite.gw0.log", "x|bridge|WARN|test\n")
        self.write(tmp_path, "notes.txt", "x|bridge|WARN|not a log\n")
        check_logs(str(tmp_path))


class TestCheckStderr:
    def test_allowed(self):
        check_stderr("ovsdb-server",
                     "x|vlog|INFO|opened log file /tmp/x.log\n\n",
                     OVSNodeDummy.OVSDB_STDERR_ALLOW)

    def test_unexpected(self):
        with pytest.raises(OVSError) as e:
            check_stderr("ovsdb-server", "x|ovsdb_server|ERR|failure\n",
                         OVSNodeDummy.OVSDB_STDERR_ALLOW)
        assert "x|ovsdb_server|ERR|failure" in str(e.value)

    def test_literal_pipes(self):
        # '|' in the patterns is a literal character, not an alternation.
        with pytest.raises(OVSError):
            check_stderr("ovsdb-server", "x|vlog|ERR|failure\n",
                         OVSNodeDummy.OVSDB_STDERR_ALLOW)


@needs_ovs
class TestOVSNodeDummy:
    def test_fixture(self, ovs, test_dir):
        assert ovs.test_dir == test_dir
        assert os.environ["OVS_RUNDIR"] == test_dir
        for program in ("ovsdb-server", "ovs-vswitchd"):
            assert process_alive(read_pid(ovs, program), program)
        run("ovs-vsctl list-br", stdout=["br0"])
        run("ovs-vsctl get bridge br0 datapath_type", stdout=["dummy"])
        run("ovs-vsctl get bridge br0 other-config:datapath-id",
            stdout=["fedcba9876543210"])
        run("ovs-ofctl -O OpenFlow15 add-flow br0 actions=drop")
        assert "actions=drop" in ovs.ofctl("dump-flows br0",
                                           stdout=True).stdout

    def test_add_flows(self, ovs):
        ovs.add_flows("br0", """
            table=0 priority=10 actions=drop

            table=1 actions=normal
        """, args="--bundle")
        with open("flows-br0.txt") as f:
            assert f.read() == ("table=0 priority=10 actions=drop\n"
                                "table=1 actions=normal\n")
        dump = ovs.ofctl("dump-flows br0", stdout=True).stdout
        assert "priority=10 actions=drop" in dump
        assert "table=1, n_packets=0" in dump

    def test_lifecycle(self, test_dir, monkeypatch):
        monkeypatch.setenv("OVS_RUNDIR", "/nonexistent")
        with OVSNodeDummy(test_dir) as node:
            assert os.environ["OVS_RUNDIR"] == test_dir
            pids = [read_pid(node, p) for p in ("ovsdb-server",
                                                "ovs-vswitchd")]
            node.add_bridge("br1", "set bridge br1 stp_enable=true")
            node.vsctl("get bridge br1 stp_enable", stdout=["true"])
            node.appctl("version", stdout=True)
            node.appctl("version", target="ovsdb-server", stdout=True)
        assert os.environ["OVS_RUNDIR"] == "/nonexistent"
        for pid in pids:
            assert not process_alive(pid)

    def test_unexpected_log_message(self, test_dir):
        node = OVSNodeDummy(test_dir)
        node.start()
        pid = read_pid(node, "ovs-vswitchd")
        with open(os.path.join(test_dir, "ovs-vswitchd.log"), "a") as f:
            f.write("2026-01-01T00:00:00Z|1|bridge|WARN|fake warning\n")
        with pytest.raises(OVSError) as e:
            node.stop()
        assert "fake warning" in str(e.value)
        # Everything is stopped anyway.
        assert not process_alive(pid)

        node = OVSNodeDummy(os.path.join(test_dir, "allowed"))
        os.mkdir(node.test_dir)
        node.start()
        with open(os.path.join(node.test_dir, "ovs-vswitchd.log"), "a") as f:
            f.write("2026-01-01T00:00:00Z|1|bridge|WARN|fake warning\n")
        node.stop(log_allow=["fake warning"])

    def test_no_checks_after_failure(self, test_dir):
        node = OVSNodeDummy(test_dir)
        node.start()
        with open(os.path.join(test_dir, "ovs-vswitchd.log"), "a") as f:
            f.write("2026-01-01T00:00:00Z|1|bridge|WARN|fake warning\n")
        os.kill(read_pid(node, "ovs-vswitchd"), signal.SIGKILL)
        node.stop(check=False)

    def test_crashed_daemon(self, test_dir):
        node = OVSNodeDummy(test_dir)
        node.start()
        db_pid = read_pid(node, "ovsdb-server")
        vswitchd_pid = read_pid(node, "ovs-vswitchd")
        os.kill(vswitchd_pid, signal.SIGKILL)
        wait_until(lambda: not process_alive(vswitchd_pid))
        with pytest.raises(OVSError) as e:
            node.stop()
        assert "ovs-vswitchd" in str(e.value)
        assert "is not running" in str(e.value)
        assert not process_alive(db_pid)

    def test_failed_start(self, test_dir):
        open(os.path.join(test_dir, "conf.db"), "w").close()
        with pytest.raises(Exception):
            with OVSNodeDummy(test_dir):
                pass
        assert "OVS_RUNDIR" not in os.environ \
            or os.environ["OVS_RUNDIR"] != test_dir

    def test_background(self, test_dir):
        with OVSNodeDummy(test_dir) as node:
            proc = node.start_background("echo $OVS_RUNDIR; sleep 30",
                                         stdout="out.txt")
            assert node._background == [proc]
            wait_until(lambda: open("out.txt").read(), timeout=5)
        assert not proc.alive()
        assert open("out.txt").read() == test_dir + "\n"

    def test_cleanup_order(self, test_dir):
        events = []

        class Resource:
            def __init__(self, name):
                self.name = name

            def close(self):
                vswitchd = process_alive(vswitchd_pid, "ovs-vswitchd")
                events.append((self.name, vswitchd))

        with OVSNodeDummy(test_dir) as node:
            vswitchd_pid = read_pid(node, "ovs-vswitchd")
            node.track(Resource("first"))
            node.track(Resource("second"))
        assert events == [("second", False), ("first", False)]

    def test_child_nodes(self, test_dir):
        with OVSNodeDummy(test_dir) as parent:
            child = parent.create_node("hv1")
            child.start()
            assert child.test_dir == os.path.join(test_dir, "hv1")
            assert child.parent is parent
            # The process environment still points to the parent.
            assert os.environ["OVS_RUNDIR"] == test_dir

            parent.add_of_br(0)
            child.add_of_br(1)
            run("ovs-vsctl list-br", stdout=["br0"])
            child.vsctl("list-br", stdout=["br1"])
            child.ofctl("add-flow br1 actions=drop")
            child_pid = read_pid(child, "ovs-vswitchd")

            grandchild = child.create_node("nested")
            grandchild.start()
            grandchild.vsctl("list-br", stdout=[])
        assert not process_alive(child_pid)
        assert parent._children == []

    def test_child_stopped_explicitly(self, test_dir):
        with OVSNodeDummy(test_dir) as parent:
            child = parent.create_node("hv1")
            child.start()
            child.stop()
            assert parent._children == []

    @pytest.mark.skipif(not os.path.isdir("/proc/self"),
                        reason="needs /proc")
    def test_wrapper(self, test_dir):
        with OVSNodeDummy(test_dir, wrapper=["env", "OVS_TEST=1"]) as node:
            pid = read_pid(node, "ovs-vswitchd")
            with open("/proc/%d/environ" % pid, "rb") as f:
                assert b"OVS_TEST=1" in f.read().split(b"\0")
            child = node.create_node("hv1")
            assert child.wrapper == ("env", "OVS_TEST=1")


@needs_ovs
class TestFixture:
    """Tests for the 'ovs' fixture and the 'log_allow' marker."""

    @pytest.fixture
    def inner(self, pytester):
        pytester.makeini("[pytest]\n"
                         "markers = log_allow: allowed log messages\n")

        def run(*args):
            return pytester.runpytest(
                "--confcutdir=%s" % pytester.path,
                "-p", "tests.lib.report", "-p", "tests.unit.conftest",
                "-W", "ignore::pytest.PytestAssertRewriteWarning",
                "--basetemp=%s" % (pytester.path / "artifacts"), *args)

        return run

    def test_log_check(self, pytester, inner):
        pytester.makepyfile(test_a="""
            import pytest

            def warn(ovs):
                ovs.appctl("vlog/set ANY:file:dbg")
                with open(ovs.test_dir + "/ovs-vswitchd.log", "a") as f:
                    f.write("x|bridge|WARN|fake warning\\n")

            def test_unexpected(ovs):
                warn(ovs)

            @pytest.mark.log_allow("fake warn", "unused")
            def test_allowed(ovs):
                warn(ovs)

            def test_failed(ovs):
                warn(ovs)
                assert False
        """)
        result = inner()
        result.assert_outcomes(passed=2, failed=1, errors=1)
        result.stdout.fnmatch_lines([
            "*ERROR at teardown of test_unexpected*",
            "*Unexpected messages in daemon logs*",
            "*fake warning*"])
