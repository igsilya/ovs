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

"""OVS route table tests, migrated from system-route.at."""

import pytest

from tests.lib.cmd import grep_lines, run, sort_lines, wait_until_equal

pytestmark = pytest.mark.requires("userspace_datapath")


def test_add_remove_system_route(ovs):
    run("ip tuntap add name p1-route mode tap")
    run("ip link set p1-route up")

    # OVS catches route updates.
    run("ip addr add 10.0.0.17/24 dev p1-route")
    wait_until_equal("ovs-appctl ovs/route/show",
                     "Cached: 10.0.0.0/24 dev p1-route SRC 10.0.0.17\n"
                     "Cached: 10.0.0.17/32 dev p1-route SRC 10.0.0.17 local\n",
                     filters=[grep_lines("p1-route"), sort_lines])

    # And removes the routes.
    run("ip addr del 10.0.0.17/24 dev p1-route")
    wait_until_equal("ovs-appctl ovs/route/show", "",
                     filters=[grep_lines("p1-route")])
