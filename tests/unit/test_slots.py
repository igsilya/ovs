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

"""Tests for tests.lib.slots."""

import os
import subprocess
import sys
import time

from tests.lib.slots import SlotPool, available_cpus


def test_acquire_release(tmp_path):
    pool = SlotPool(str(tmp_path), 3)
    a = pool.acquire(2)
    assert len(a.numbers) == 2
    b = pool.acquire()
    assert len(b.numbers) == 1
    # All the slots are different.
    assert sorted(a.numbers + b.numbers) == [0, 1, 2]
    a.release()
    b.release()
    # Asking for more than there is takes all of them.
    with pool.acquire(5) as c:
        assert c.numbers == [0, 1, 2]
    with pool.acquire(3):
        pass


def test_minimum_one_slot(tmp_path):
    assert SlotPool(str(tmp_path), 0).count == 1


def test_shared_between_processes(tmp_path):
    root = os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))))
    code = ("import sys, time; sys.path.insert(0, %r); "
            "from tests.lib.slots import SlotPool; "
            "s = SlotPool(%r, 1).acquire(); "
            "print('got', s.numbers, flush=True); time.sleep(0.5)"
            % (root, str(tmp_path)))
    pool = SlotPool(str(tmp_path), 1)
    held = pool.acquire()
    proc = subprocess.Popen([sys.executable, "-c", code],
                            stdout=subprocess.PIPE, universal_newlines=True)
    time.sleep(0.5)
    # The other process waits while the slot is taken.
    assert proc.poll() is None
    held.release()
    assert proc.stdout.readline() == "got [0]\n"
    proc.wait()
    proc.stdout.close()
    # The slot is free again after the process exits.
    pool.acquire().release()


def test_available_cpus():
    cpus = available_cpus()
    assert cpus and cpus == sorted(cpus)
