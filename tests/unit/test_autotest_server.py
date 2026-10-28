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

"""Tests for tests.lib.autotest, using a small generated testsuite."""

import os
import shutil
import subprocess

import pytest

from tests.lib.autotest import (
    AutotestError,
    AutotestServer,
    list_tests,
    make_server_script,
)

TESTSUITE_AT = r"""
m4_define([AT_PACKAGE_STRING], [mini])
m4_define([AT_PACKAGE_BUGREPORT], [nobody])
AT_INIT

AT_SETUP([passing test])
AT_KEYWORDS([alpha])
AT_CHECK([echo hello], [0], [hello
])
AT_CLEANUP

AT_SETUP([failing test])
AT_KEYWORDS([beta])
AT_CHECK([echo unexpected; exit 1])
AT_CLEANUP

AT_SETUP([skipped test])
AT_SKIP_IF([true])
AT_CLEANUP

AT_SETUP([expected failure])
AT_XFAIL_IF([true])
AT_CHECK([false])
AT_CLEANUP

AT_SETUP([reads stdin])
AT_CHECK([cat], [0], [])
AT_CLEANUP

AT_SETUP([kills the testsuite])
AT_CHECK([kill -9 $$])
AT_CLEANUP

AT_SETUP([leaves a file])
AT_CHECK([touch some-file])
AT_CLEANUP
"""


@pytest.fixture(scope="module")
def testsuite(tmp_path_factory):
    if shutil.which("autom4te") is None:
        pytest.skip("autom4te is not available")
    path = tmp_path_factory.mktemp("autotest")
    (path / "testsuite.at").write_text(TESTSUITE_AT)
    subprocess.run(["autom4te", "--language=autotest", "-o", "testsuite",
                    "testsuite.at"], cwd=str(path), check=True)
    (path / "atconfig").write_text("at_testdir='.'\n")
    return str(path / "testsuite")


@pytest.fixture
def rundir(tmp_path):
    (tmp_path / "atconfig").write_text("at_testdir='.'\n")
    return str(tmp_path)


def test_list_tests(testsuite, rundir):
    assert list_tests(testsuite, rundir) == [
        (1, "testsuite.at:6", "passing test"),
        (2, "testsuite.at:12", "failing test"),
        (3, "testsuite.at:17", "skipped test"),
        (4, "testsuite.at:21", "expected failure"),
        (5, "testsuite.at:26", "reads stdin"),
        (6, "testsuite.at:30", "kills the testsuite"),
        (7, "testsuite.at:34", "leaves a file"),
    ]
    assert [t[0] for t in list_tests(testsuite, rundir, ["-k", "beta"])] \
        == [2]
    assert [t[0] for t in list_tests(testsuite, rundir, ["3-4", "7"])] \
        == [3, 4, 7]


def test_server_results(testsuite, rundir):
    server = AutotestServer(testsuite, rundir, "testsuite.gw0")
    assert os.path.exists(os.path.join(rundir, "testsuite.gw0"))
    assert server.run(1) == ("pass", server.suite_dir + "/1")
    assert not server.failed
    assert server.run(3)[0] == "skip"
    assert server.run(4)[0] == "xfail"
    assert server.run(5)[0] == "pass"
    assert not server.failed

    result, group_dir = server.run(2)
    assert result == "fail"
    assert server.failed
    log = open(os.path.join(group_dir, "testsuite.gw0.log")).read()
    assert "unexpected" in log

    # Tests can run again and in any order.
    assert server.run(1)[0] == "pass"
    with pytest.raises(AutotestError):
        server.run(42)

    server.close()
    assert not os.path.exists(server.script)
    # Artifacts of the failed test are preserved.
    assert os.path.exists(os.path.join(server.suite_dir, "2"))
    assert os.path.exists(server.suite_log)


def test_server_cleanup(testsuite, rundir):
    server = AutotestServer(testsuite, rundir, "testsuite.pytest")
    assert server.run(7) == ("pass", server.suite_dir + "/7")
    assert not os.path.exists(os.path.join(server.suite_dir, "7"))
    server.close()
    assert os.listdir(rundir) == ["atconfig"]


def test_server_keep(testsuite, rundir):
    server = AutotestServer(testsuite, rundir, "testsuite.pytest", ["-d"])
    server.run(7)
    server.close(keep=True)
    assert os.path.exists(os.path.join(server.suite_dir, "7", "some-file"))


def test_server_death(testsuite, rundir):
    server = AutotestServer(testsuite, rundir, "testsuite.pytest")
    with pytest.raises(AutotestError):
        server.run(6)
    assert not server.alive()
    server.close(keep=True)


def test_unsupported_testsuite(tmp_path):
    (tmp_path / "testsuite").write_text("#! /bin/sh\nexit 0\n")
    with pytest.raises(AutotestError):
        make_server_script(str(tmp_path / "testsuite"),
                           str(tmp_path / "copy"))


def test_server_relative_paths(testsuite, rundir, monkeypatch):
    monkeypatch.chdir(os.path.dirname(rundir))
    rel_rundir = os.path.basename(rundir)
    rel_testsuite = os.path.relpath(testsuite)
    server = AutotestServer(rel_testsuite, rel_rundir, "testsuite.pytest")
    assert server.run(1)[0] == "pass"
    assert os.path.isdir(server.bodies_dir)
    server.close()
    assert not os.path.exists(server.bodies_dir)
    assert os.listdir(rundir) == ["atconfig"]


def test_check_line(testsuite, rundir):
    server = AutotestServer(testsuite, rundir, "testsuite.pytest")
    # The check that skipped the test.
    assert server.run(3)[0] == "skip"
    assert server.check_line == "testsuite.at:18"
    assert server.run(2)[0] == "fail"
    assert server.check_line == "testsuite.at:14"
    server.close()


def test_server_restart(testsuite, rundir):
    server = AutotestServer(testsuite, rundir, "testsuite.pytest")
    assert server.run(1)[0] == "pass"
    server.stop()
    assert not server.alive()
    assert os.path.exists(server.script)
    server.start()
    assert server.alive()
    assert server.run(2)[0] == "fail"
    server.stop()
    server.start()
    assert server.run(7)[0] == "pass"
    server.close()
    assert not os.path.exists(server.script)
    # The failed test is preserved.
    assert os.path.exists(os.path.join(server.suite_dir, "2"))
