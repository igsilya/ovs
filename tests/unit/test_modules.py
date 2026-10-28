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

"""Tests for tests.lib.modules, with a fake modprobe."""

import subprocess

import pytest

from tests.lib import modules
from tests.lib.modules import KernelModules


@pytest.fixture
def fake(monkeypatch):
    state = {"loaded": {"builtin"}, "broken": {"broken"}, "calls": []}

    def fake_run(args, **kwargs):
        state["calls"].append(args)
        name = args[-1]
        if name in state["broken"]:
            return subprocess.CompletedProcess(args, 1, "FATAL: no module")
        if args[1] == "-r":
            state["loaded"].discard(name)
        else:
            state["loaded"].add(name)
        return subprocess.CompletedProcess(args, 0, "")

    monkeypatch.setattr(modules.subprocess, "run", fake_run)
    monkeypatch.setattr(modules, "is_loaded",
                        lambda name: name in state["loaded"])
    return state


def test_load_and_unload(fake):
    mods = KernelModules()
    assert mods.load("openvswitch")
    assert mods.load("nf_conntrack")
    assert fake["loaded"] == {"builtin", "openvswitch", "nf_conntrack"}
    mods.unload_all()
    assert fake["loaded"] == {"builtin"}
    assert fake["calls"][-2:] == [["modprobe", "-r", "nf_conntrack"],
                                  ["modprobe", "-r", "openvswitch"]]


def test_already_loaded(fake):
    mods = KernelModules()
    assert mods.load("builtin")
    mods.unload_all()
    assert fake["calls"] == []
    assert "builtin" in fake["loaded"]


def test_failure(fake):
    mods = KernelModules()
    assert not mods.load("broken", required=False)
    with pytest.raises(RuntimeError) as e:
        mods.load("broken")
    assert "FATAL: no module" in str(e.value)
    mods.unload_all()
    assert ["modprobe", "-r", "broken"] not in fake["calls"]


def test_is_loaded():
    assert not modules.is_loaded("surely-not-a-kernel-module")
