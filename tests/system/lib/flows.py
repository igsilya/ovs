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

"""OpenFlow and datapath flow dumps, parsed with the ovs.flow library.

Requires the 'netaddr' and 'pyparsing' Python packages, see
python/test_requirements.txt.

Example::

    flows = dump_flows(ovs, "br0")
    assert any(f.match.get("in_port") == 1 and f.info["n_packets"] == 3
               for f in flows)
"""

from tests.lib.cmd import run


def _run(node, cmd):
    return node.run(cmd, stdout=True) if node else run(cmd, stdout=True)


def dump_flows(node, bridge, args=""):
    """Return the OpenFlow flows of ``bridge`` as ``OFPFlow`` objects.

    Args:
        node: The ``OVSNode``, or None to use the process environment.
        bridge: Bridge name.
        args: Additional arguments for 'ovs-ofctl dump-flows', e.g.,
            '-O OpenFlow15' or a flow filter.
    """
    from ovs.flow.ofp import OFPFlow

    r = _run(node, "ovs-ofctl dump-flows %s %s" % (args, bridge))
    return [OFPFlow(line) for line in r.stdout.splitlines()
            if line.strip() and "_FLOW reply" not in line
            and not line.startswith("OFPST_FLOW")]


def dump_dp_flows(node=None, args=""):
    """Return the datapath flows as ``ODPFlow`` objects.

    Args:
        node: The ``OVSNode``, or None to use the process environment.
        args: Additional arguments for 'ovs-appctl dpctl/dump-flows'.
    """
    from ovs.flow.odp import ODPFlow

    r = _run(node, "ovs-appctl dpctl/dump-flows " + args)
    return [ODPFlow(line) for line in r.stdout.splitlines()
            if line.strip() and not line.startswith("flow-dump")]
