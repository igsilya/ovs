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

"""AF_XDP tests, migrated from system-afxdp.at."""

import pytest

from tests.system.lib.ping import check_ping

pytestmark = pytest.mark.requires("afxdp")


def test_ping_between_pmd_and_non_pmd_ports(ovs):
    ovs.ofctl("add-flow br0 actions=normal")

    ns0 = ovs.netns("at_ns0")
    ns1 = ovs.netns("at_ns1")
    ovs.add_veth("p0", ns0, "br0", "10.1.1.1/24")
    ovs.add_veth("p1", ns1, "br0", "10.1.1.2/24")

    # Re-add one of the ports as a non-PMD port.
    ovs.vsctl("del-port ovs-p0")
    ovs.vsctl("add-port br0 ovs-p0 -- set interface ovs-p0 "
              "type=afxdp-nonpmd options:n_rxq=1", stderr=True)

    check_ping("10.1.1.2", ns=ns0)
