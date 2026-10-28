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

"""Sharing the hugepages of the system between parallel DPDK tests.

Every DPDK test needs a good amount of hugepage memory: about 760 MB for
ovs-vswitchd with a couple of ports, plus 512 MB for testpmd, if used.
The hugepages are split into slots of ``SLOT_BYTES``, and a test runs only
when it holds enough of them, see ``tests.lib.slots``.
"""

from tests.lib.slots import SlotPool

SLOT_BYTES = 800 * 1024 * 1024


def hugepage_bytes():
    """Return the total size of the default size hugepages in the system."""
    total = size = 0
    with open("/proc/meminfo") as f:
        for line in f:
            fields = line.split()
            if fields[0] == "HugePages_Total:":
                total = int(fields[1])
            elif fields[0] == "Hugepagesize:":
                size = int(fields[1]) * 1024
    return total * size


def hugepage_slots(directory):
    """Return the ``SlotPool`` for the hugepages of the system."""
    return SlotPool(directory, hugepage_bytes() // SLOT_BYTES)
