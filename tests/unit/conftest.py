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

"""pytest configuration for OVS unit tests."""

import shutil

import pytest

from tests.lib import report
from tests.lib.ovs import OVSNodeDummy


@pytest.fixture
def ovs(request, test_dir):
    """OVS with the dummy datapath and bridge br0, like OVS_VSWITCHD_START.

    The daemon logs are checked after a successful test, messages allowed
    in them can be listed with the 'log_allow' marker.
    """
    if shutil.which("ovs-vswitchd") is None:
        pytest.skip("OVS binaries are not in PATH")

    with OVSNodeDummy(test_dir) as node:
        node.add_of_br(0)
        yield node
        marker = request.node.get_closest_marker("log_allow")
        node.stop(check=report.passed(request.node),
                  log_allow=marker.args if marker else ())
