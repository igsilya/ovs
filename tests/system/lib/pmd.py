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

"""CPUs for busy polling threads of parallel tests.

PMD threads of the userspace datapath (and testpmd in DPDK tests) poll
their ports continuously.  Without an explicit CPU mask, OVS places the
PMD thread of every instance on the same CPU, so tests running in parallel
would compete for one CPU while the rest are idle, and fail on timeouts.
So every such test takes CPUs from a pool shared by all the test
processes, see ``tests.lib.slots``, one for the PMD thread of OVS and,
optionally, one for testpmd.  The first CPU is not in the pool, it is left
for everything else: test processes, other threads of the daemons, etc.
"""

import os
import re

from tests.lib.slots import SlotPool, available_cpus


def busy_polling(dp):
    """Whether ``DatapathConfig`` ``dp`` has ports polled by PMD threads.

    Ports of the userspace datapath on top of Linux network devices are
    not polled by PMD threads, AF_XDP and DPDK ports are.
    """
    return dp.datapath == "userspace" and (dp.afxdp or dp.dpdk)


def polling_cpus():
    """Return the CPUs for polling threads: all but the first one."""
    cpus = available_cpus()
    return cpus[1:] if len(cpus) > 1 else cpus


def cpu_slots(directory):
    """Return the ``SlotPool`` of the CPUs for polling threads."""
    return SlotPool(directory, len(polling_cpus()))


def pmd_environment(slots, base=None):
    """Return environment variables that place a test on CPUs of ``slots``.

    Args:
        slots: ``Slots`` from ``cpu_slots()``.  The first one is for the
            PMD threads of OVS, the second one, if any, is for testpmd.
        base: The environment to start from, os.environ by default.

    Returns:
        A dict with OVS_PMD_CPU_MASK, for the Autotest macros that create
        the OVS database, and DPDK_EAL_OPTIONS with the testpmd lcores, if
        there is a second CPU.
    """
    base = os.environ if base is None else base
    cpus = polling_cpus()
    pmd_cpu = cpus[slots.numbers[0]]
    result = {"OVS_PMD_CPU_MASK": "0x%x" % (1 << pmd_cpu)}
    if len(slots.numbers) > 1:
        testpmd_cpu = cpus[slots.numbers[1]]
        eal = re.sub(r"--lcores[ =]\S+", "",
                     base.get("DPDK_EAL_OPTIONS", "")).split()
        eal.append("--lcores 0@%d,1@%d,2@%d" % ((testpmd_cpu,) * 3))
        result["DPDK_EAL_OPTIONS"] = " ".join(eal)
    return result
