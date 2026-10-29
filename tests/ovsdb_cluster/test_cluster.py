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

"""OVSDB cluster tests, migrated from ovsdb-cluster.at."""

import os
import signal

from tests.lib import env
from tests.lib.ovsdb import RaftCluster

# 'ovsdb-client wait' is killed by SIGALRM on timeout.
EXIT_TIMEOUT = -signal.SIGALRM


def test_initial_status_should_be_disconnected(node):
    schema = os.path.join(env.srcdir(), "tests", "idltest.ovsschema")
    cluster = RaftCluster(node, 3, schema)
    for i in range(1, 4):
        cluster.start(i)
    for i in range(1, 4):
        cluster.wait(i)

    # Stop all servers, and start only s1, to test the initial connection
    # status when there is no leader yet.
    for i in range(1, 4):
        cluster.stop(i)
    cluster.start(1)

    # The initial status should be disconnected, so the wait times out.
    cluster.wait(1, timeout=1, rc=EXIT_TIMEOUT)
    cluster.stop(1)
