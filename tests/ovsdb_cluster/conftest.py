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

"""pytest configuration for OVSDB cluster tests."""

import shutil

import pytest

from tests.lib import report
from tests.lib.ovs import OVSNode


@pytest.fixture
def node(request, test_dir):
    """An OVSNode without daemons of its own, for running ovsdb-servers.

    The daemons it starts are stopped at the end of the test.
    """
    if shutil.which("ovsdb-server") is None:
        pytest.skip("OVS binaries are not in PATH")
    node = OVSNode(test_dir)
    yield node
    node.stop(check=report.passed(request.node))
