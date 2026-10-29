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

"""Tests for tests.lib.debug."""

import os

from tests.lib import debug
from tests.lib.ovs import OVSNodeDummy


class FakeItem:
    def __init__(self, **funcargs):
        self.funcargs = funcargs


def test_environment_lines(tmp_path):
    node = OVSNodeDummy(tmp_path)
    lines = debug.environment_lines(FakeItem(test_dir=tmp_path, ovs=node))
    assert lines[0] == "Test directory: %s" % tmp_path
    text = "\n".join(lines)
    assert "export OVS_DBDIR=" in text
    assert " OVS_RUNDIR=%s " % tmp_path in text
    assert "export PATH=" in text
    # Not a system test.
    assert "nsenter" not in text


def test_environment_lines_isolated(tmp_path, monkeypatch):
    netns_dir = tmp_path / "netns"
    netns_dir.mkdir()
    (netns_dir / "at_ns0").write_text("")
    monkeypatch.setattr(debug, "NETNS_DIR", str(netns_dir))
    text = "\n".join(debug.environment_lines(FakeItem(isolated_ns=None)))
    assert "nsenter -t %d -n -m" % os.getpid() in text
    assert "ip netns exec at_ns0 sh" in text
