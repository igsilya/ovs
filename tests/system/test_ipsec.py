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

"""IPsec tests, migrated from system-ipsec.at."""

import pytest

from tests.system.lib.ipsec import IPsecNode, check_esp_traffic

pytestmark = pytest.mark.requires("kernel_datapath", "libreswan", "tcpdump")


# Geneve may not work on older kernels due to CVE-2020-25645, see
# https://bugzilla.redhat.com/show_bug.cgi?id=1883988.
@pytest.mark.requires("geneve")
def test_libreswan_ipv4_geneve_defaultroute_psk(ovs):
    ovs.ofctl("add-flow br0 actions=normal")
    left = IPsecNode(ovs, "left", "p0", "10.1.1.1", "10.1.1.2")
    right = IPsecNode(ovs, "right", "p1", "10.1.1.2", "10.1.1.1")

    left.add_tunnel("geneve", "options:remote_ip=10.1.1.2 "
                              "options:psk=swordfish")
    right.add_tunnel("geneve", "options:remote_ip=10.1.1.1 "
                               "options:psk=swordfish")
    check_esp_traffic(ovs, left, right)
