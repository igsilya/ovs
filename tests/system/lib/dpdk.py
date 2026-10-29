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

"""DPDK test applications for system tests."""

import glob
import os
import shlex


def numa_nodes():
    """Return the number of NUMA nodes of the system."""
    return max(1, len(glob.glob("/sys/devices/system/node/node[0-9]*")))


class TestPMD:
    """dpdk-testpmd, like OVS_DPDK_START_TESTPMD and OVS_DPDK_STOP_TESTPMD.

    Args:
        node: The ``OVSNode`` that runs testpmd in the background.
        eal_options: EAL options, e.g., DPDK_EAL_OPTIONS with the lcores
            for the test.
    """

    # Not a test class, despite the name.
    __test__ = False

    def __init__(self, node, eal_options=""):
        self.node = node
        self.eal_options = eal_options
        self.proc = None

    def start(self, options):
        """Start testpmd in the background.

        ``options`` are additional EAL options, optionally followed by
        ' -- ' and testpmd options, e.g., '--vdev=net_tap0,iface=tap0'.
        """
        socket_mem = ",".join(["512"] * numa_nodes())
        eal = ("%s --in-memory --socket-mem=%s --single-file-segments "
               "--no-pci --file-prefix testpmd"
               % (self.eal_options, socket_mem))
        eal_extra, _, testpmd_options = options.partition(" -- ")
        cmd = "dpdk-testpmd %s %s -- -a --stats-period 2 %s" % (
            eal, eal_extra, testpmd_options)
        test_dir = self.node.test_dir
        with open(os.path.join(test_dir, "testpmd.cmd"), "w") as f:
            f.write(cmd + "\n")
        self.proc = self.node.start_background(
            cmd + " 2>&1", stdout=os.path.join(test_dir, "testpmd.log"))
        return self

    def stop(self):
        """Stop testpmd, if it is running."""
        if self.proc is not None:
            self.proc.stop()
            self.proc = None

    def __repr__(self):
        return "TestPMD(%s)" % shlex.quote(self.eal_options)
