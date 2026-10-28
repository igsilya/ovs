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

"""Tests for tests/run-pytest.py."""

import importlib.util
import os

import pytest


@pytest.fixture(scope="module")
def rp():
    path = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                        "run-pytest.py")
    spec = importlib.util.spec_from_file_location("run_pytest", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_version_tuple(rp):
    assert rp.version_tuple("6.2.2") == (6, 2, 2)
    assert rp.version_tuple("8.0.0rc1") == (8, 0, 0)
    assert rp.version_tuple("3.4") == (3, 4)


def test_has_option(rp):
    assert rp.has_option(["-n8"], "-n")
    assert rp.has_option(["-n", "8"], "-n")
    assert rp.has_option(["--numprocesses=4"], "--numprocesses")
    assert not rp.has_option(["--no-header"], "-n")
    assert not rp.has_option(["-k", "nothing"], "-n")


@pytest.mark.parametrize("version, args, expected", [
    ((3, 8), ["-n8"], ["--maxschedchunk=1"]),
    ((3, 8), ["-v"], []),
    ((3, 8), ["-n8", "--dist=worksteal"], []),
    ((3, 8), ["-n8", "--maxschedchunk=4"], []),
    ((3, 3), ["-n8"], []),
    (None, ["-n8"], []),
])
def test_xdist_args(rp, monkeypatch, version, args, expected):
    monkeypatch.setattr(rp, "module_version", lambda name: version)
    assert rp.xdist_args(args) == expected


def test_sanitizer_reports(rp, tmp_path):
    basetemp = tmp_path / "pytest.dir"
    for d in ("pytest.dir/unit.test_a", "pytest.dir/popen-gw0/t0/a",
              "testsuite.gw1.dir/0042", "testsuite.dir/0001"):
        (tmp_path / d).mkdir(parents=True)
    assert rp.sanitizer_reports(str(basetemp)) == []
    # Deeper directories may contain anything, e.g., pytester runs.
    (tmp_path / "pytest.dir/popen-gw0/t0/a/sanitizers.1").write_text("x")
    # Directories of direct Autotest runs don't matter either.
    (tmp_path / "testsuite.dir/0001/sanitizers.1").write_text("x")
    assert rp.sanitizer_reports(str(basetemp)) == []
    for f in ("pytest.dir/unit.test_a/sanitizers.2",
              "testsuite.gw1.dir/0042/sanitizers.3"):
        (tmp_path / f).write_text("x")
    assert sorted(os.path.basename(r) for r in
                  rp.sanitizer_reports(str(basetemp))) \
        == ["sanitizers.2", "sanitizers.3"]


@pytest.mark.parametrize("version, args, expected", [
    ((3, 8), ["-n8"], ["--dist=loadgroup"]),
    ((2, 5), ["-n", "4"], ["--dist=loadgroup"]),
    ((2, 4), ["-n8"], []),
    ((3, 8), ["-n8", "--dist=load"], []),
    ((3, 8), [], []),
])
def test_xdist_args_loadgroup(rp, monkeypatch, version, args, expected):
    monkeypatch.setattr(rp, "module_version", lambda name: version)
    assert rp.xdist_args(args, loadgroup=True) == expected
