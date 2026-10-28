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

"""Sharing limited resources between tests running in parallel.

Some resources of the system can only support a few tests at a time, e.g.,
hugepage memory, or CPUs for busy polling threads.  A ``SlotPool`` splits
such a resource into numbered slots, and a test holds the slots it needs
while it runs.  Slot numbers are unique among the running tests, so they
can also identify a part of the resource, e.g., a CPU.

The slots are lock files in a directory shared by all the test processes
(e.g., pytest-xdist workers), taken with flock(2).  The kernel releases
the lock when the file is closed or the process exits for any reason, so
slots of a crashed worker don't stay taken.
"""

import fcntl
import os
import random
import time

from tests.lib.cmd import log_line


class SlotPool:
    """A pool of ``count`` slots shared by processes using ``directory``.

    Usage::

        pool = SlotPool(directory, 4)
        slots = pool.acquire(2)
        try:
            ... slots.numbers ...
        finally:
            slots.release()
    """

    def __init__(self, directory, count):
        self.directory = directory
        self.count = max(1, count)
        os.makedirs(directory, exist_ok=True)

    def _try_lock(self, number):
        f = open(os.path.join(self.directory, "slot%d" % number), "w")
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            f.close()
            return None
        return f

    def acquire(self, n=1):
        """Wait until ``n`` slots are free and take them.

        Asking for more slots than the pool has takes all of them.
        Partially taken slots are released while waiting, so tests waiting
        for multiple slots can't deadlock each other.

        Returns:
            ``Slots`` with the numbers of the taken slots.
        """
        n = min(n, self.count)
        logged = False
        while True:
            held = {}
            order = list(range(self.count))
            random.shuffle(order)
            for number in order:
                f = self._try_lock(number)
                if f is not None:
                    held[number] = f
                    if len(held) == n:
                        return Slots(held)
            Slots(held).release()
            if not logged:
                log_line("waiting for %d of %d slots in %s"
                         % (n, self.count, self.directory))
                logged = True
            time.sleep(0.1 + random.random() * 0.2)


class Slots:
    """Slots taken from a ``SlotPool``."""

    def __init__(self, held):
        self._held = held
        self.numbers = sorted(held)

    def release(self):
        for f in self._held.values():
            f.close()
        self._held = {}

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.release()
        return False


def available_cpus():
    """Return the sorted list of CPUs the process may run on."""
    if hasattr(os, "sched_getaffinity"):
        return sorted(os.sched_getaffinity(0))
    return list(range(os.cpu_count() or 1))
