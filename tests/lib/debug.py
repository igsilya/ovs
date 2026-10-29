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

"""Help for debugging tests interactively.

With ``pytest --pdb``, the debugger starts at the point of failure, before
the fixtures are torn down, so the OVS daemons are still running and the
network namespaces of the test still exist.  This replaces OVS_PAUSE_TEST
of Autotest.  ``pytest_exception_interact()`` prints how to get into the
environment of the test from another terminal.
"""

import os
import shlex

import pytest

from tests.lib.ovs import OVSNode

NETNS_DIR = "/run/netns"


def _nodes(node):
    yield node
    for child in node._children:
        yield from _nodes(child)


def environment_lines(item):
    """Return lines describing how to enter the environment of ``item``."""
    lines = []
    test_dir = item.funcargs.get("test_dir")
    if test_dir is not None:
        lines.append("Test directory: %s" % test_dir)

    commands = []
    isolated = item.funcargs.get("isolated_ns") is not None
    if isolated:
        # The test process itself is in the namespaces of the test.
        commands.append("nsenter -t %d -n -m  # network and mount namespaces "
                        "of the test" % os.getpid())
    commands.append("export PATH=%s" % shlex.quote(os.environ["PATH"]))

    for value in item.funcargs.values():
        if not isinstance(value, OVSNode):
            continue
        for node in _nodes(value):
            assignments = " ".join("%s=%s" % (k, shlex.quote(v))
                                   for k, v in sorted(node.env.items()))
            if node.ns:
                commands.append("ip netns exec %s env %s sh"
                                % (node.ns, assignments))
            else:
                commands.append("export " + assignments)

    if isolated and os.path.isdir(NETNS_DIR):
        for name in sorted(os.listdir(NETNS_DIR)):
            commands.append("ip netns exec %s sh" % name)

    lines.append("From another terminal, as root:")
    lines += ["  " + c for c in commands]
    return lines


# pytest calls this for every failure, so only act if the debugger runs, and
# before it starts.
@pytest.hookimpl(tryfirst=True)
def pytest_exception_interact(node, call, report):
    if not node.config.getoption("usepdb") or not hasattr(node, "funcargs"):
        return
    reporter = node.config.pluginmanager.getplugin("terminalreporter")
    if reporter is None:
        return
    reporter.write_sep("=", "test environment is still active")
    for line in environment_lines(node):
        reporter.write_line(line)
    reporter.write_sep("=")
