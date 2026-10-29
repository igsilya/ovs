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

"""DPDK tests, migrated from system-dpdk.at."""

import pytest

from tests.lib.cmd import run, wait_until
from tests.system.lib.ping import check_ping

pytestmark = pytest.mark.requires("dpdk")


@pytest.mark.requires("testpmd")
@pytest.mark.log_allow(
    r"VHOST_CONFIG: \(.*dpdkvhostuser0\) recvmsg failed",
    r"VHOST_CONFIG: \(.*dpdkvhostuser0\) failed to connect: No such file "
    r"or directory",
    r"dpdkvhostuser ports are considered deprecated;  please migrate to "
    r"dpdkvhostuserclient ports.",
    r"failed to enumerate system datapaths: No such file or directory")
def test_ping_vhost_user_ports(ovs, testpmd):
    ovs.vsctl("add-br br10 -- set bridge br10 datapath_type=netdev")
    socket = ovs.add_vhost_user_port("br10", "dpdkvhostuser0")

    ns1 = ovs.netns("ns1")
    ns2 = ovs.netns("ns2")
    ovs.add_veth("tap1", ns2, "br10", "172.31.110.12/24")

    # testpmd connects the vhost-user port to tap0.
    testpmd.start('--vdev="net_virtio_user,path=%s" '
                  '--vdev="net_tap0,iface=tap0"' % socket)
    ovs.wait_for_log("virtio is now ready for processing")
    wait_until(lambda: "LOWER_UP" in run("ip link show dev tap0",
                                         stdout=True).stdout,
               description="tap0 to be up")

    run("ip link set tap0 netns %s" % ns1)
    run("ip link set tap0 up", ns=ns1)
    run("ip addr add 172.31.110.11/24 dev tap0", ns=ns1)
    check_ping("172.31.110.12", ns=ns1, count=4, args="-I tap0")

    testpmd.stop()
    ovs.wait_for_log("vHost Device '%s' has been removed" % socket)
    ovs.vsctl("del-port br10 dpdkvhostuser0")
