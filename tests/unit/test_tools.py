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

"""Tests for tests.lib.tools."""

import argparse
import os

import pytest

from tests.lib import env, tools


class FakeConfig:
    def __init__(self, **selected):
        self.option = argparse.Namespace(keep_artifacts=False)
        self._selected = selected

    def getoption(self, name):
        return self._selected.get(name, False)


def test_selected():
    assert tools.selected(FakeConfig()) is None
    assert tools.selected(FakeConfig(strace=True)) == "strace"
    with pytest.raises(ValueError, match="mutually exclusive"):
        tools.selected(FakeConfig(valgrind=True, helgrind=True))


def test_command():
    supp = os.path.join(env.srcdir(), "tests", "glibc.supp")
    assert "--suppressions=" + supp in tools.command("valgrind")
    assert "--log-file=valgrind.%p" in tools.command("valgrind")
    assert "--tool=helgrind" in tools.command("helgrind")
    assert tools.command("strace").startswith("strace -D -ff ")


def test_configure_none():
    assert tools.configure(FakeConfig()) is None


def test_configure(monkeypatch, tmp_path):
    wrappers = tmp_path / "tests" / "valgrind"
    wrappers.mkdir(parents=True)
    (wrappers / "ovs-vswitchd").write_text("")
    monkeypatch.setattr(env, "builddir", lambda: str(tmp_path))
    monkeypatch.setattr(tools.shutil, "which", lambda program: program)
    monkeypatch.delenv("VALGRIND", raising=False)
    monkeypatch.setenv("AUTOTEST_PATH", "utilities:vswitchd")

    config = FakeConfig(helgrind=True)
    assert tools.configure(config) is None
    assert os.environ["VALGRIND"] == tools.command("helgrind")
    assert os.environ["AUTOTEST_PATH"] == str(wrappers) + ":utilities:vswitchd"
    assert config.option.keep_artifacts
    # Not added again, e.g., in pytest-xdist workers.
    assert tools.configure(config) is None
    assert os.environ["AUTOTEST_PATH"] == str(wrappers) + ":utilities:vswitchd"

    # The command from the environment, e.g., from the Makefile, is used.
    monkeypatch.setenv("VALGRIND", "valgrind -q")
    assert tools.configure(FakeConfig(valgrind=True)) is None
    assert os.environ["VALGRIND"] == "valgrind -q"


def test_configure_errors(monkeypatch, tmp_path):
    monkeypatch.setattr(env, "builddir", lambda: str(tmp_path))
    monkeypatch.setattr(tools.shutil, "which", lambda program: None)
    assert "not installed" in tools.configure(FakeConfig(strace=True))

    monkeypatch.setattr(tools.shutil, "which", lambda program: program)
    assert "wrapper scripts" in tools.configure(FakeConfig(valgrind=True))

    error = tools.configure(FakeConfig(valgrind=True, strace=True))
    assert "mutually exclusive" in error


def test_reports(tmp_path):
    (tmp_path / "1").mkdir()
    (tmp_path / "2").mkdir()
    bad = tmp_path / "1" / "valgrind.123"
    bad.write_text("==123== ERROR SUMMARY: 2 errors from 2 contexts\n")
    (tmp_path / "2" / "valgrind.456").write_text(
        "==456== ERROR SUMMARY: 0 errors from 0 contexts\n")
    (tmp_path / "2" / "helgrind.789").write_text(
        "==789== ERROR SUMMARY: 5 errors from 1 contexts\n")
    assert tools.reports([str(tmp_path)], "valgrind") == [str(bad)]
    assert tools.reports([str(tmp_path)], "strace") == []
