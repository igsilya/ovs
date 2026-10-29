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

"""Clustered OVSDB databases for tests, like tests/ovsdb-cluster.at.

Paths are relative, like in the Autotest tests, which keeps the paths of
the Unix sockets short.  Files are relative to the current directory and
Unix sockets to OVS_RUNDIR, which are both the test directory.
"""

import os

# Same as ovsdb_client_wait in tests/ovsdb-macros.at.
_CLIENT_WAIT = ("ovsdb-client -vconsole:warn -vreconnect:err -vjsonrpc:err "
                "-vtimeval:off -vfile -vsyslog:off -vvlog:off wait")


class RaftCluster:
    """A clustered database, served by ovsdb-servers 's1' to 's<n>'.

    Server 'i' has the database 's<i>.db', the Raft address 'unix:s<i>.raft',
    the client remote 'unix:s<i>.ovsdb' and the control socket 's<i>'.

    Args:
        node: An OVSNode, which runs and stops the servers.  It doesn't
            have to be started.
        n: Number of servers.
        schema: Path of the database schema.
    """

    def __init__(self, node, n, schema):
        self.node = node
        self.n = n
        node.run("ovsdb-tool '-vPATTERN:console:%%c|%%p|%%m' create-cluster "
                 "s1.db %s unix:s1.raft" % schema, stderr=True)
        self.schema_name = node.run("ovsdb-tool schema-name %s" % schema,
                                    stdout=True).stdout.strip()
        for i in range(2, n + 1):
            node.run("ovsdb-tool join-cluster s%d.db %s unix:s%d.raft "
                     "unix:s1.raft" % (i, self.schema_name, i))

    def pidfile(self, i):
        return os.path.abspath("s%d.pid" % i)

    def start(self, i):
        """Start server i."""
        self.node.start_daemon(
            "ovsdb-server", "-v", "-vconsole:off", "-vsyslog:off",
            "--detach", "--no-chdir", "--log-file=s%d.log" % i,
            "--pidfile=s%d.pid" % i, "--unixctl=s%d" % i,
            "--remote=punix:s%d.ovsdb" % i, "s%d.db" % i,
            pidfile=self.pidfile(i), target=os.path.abspath("s%d" % i),
            detach=False)

    def stop(self, i):
        """Stop server i, like OVS_APP_EXIT_AND_WAIT_BY_TARGET."""
        self.node.stop_daemon(self.pidfile(i))

    def wait(self, i, state="connected", timeout=None, rc=0):
        """Wait for the database of server i to reach state, like
        ovsdb_client_wait.  Returns the result of 'ovsdb-client wait'.
        """
        args = "--timeout=%d " % timeout if timeout else ""
        return self.node.run("%s %sunix:s%d.ovsdb %s %s" % (
            _CLIENT_WAIT, args, i, self.schema_name, state),
            rc=rc, stdout=True, stderr=True)
