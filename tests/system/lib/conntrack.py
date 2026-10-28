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

"""Conntrack table helpers.

``dump_conntrack()`` parses 'ovs-appctl dpctl/dump-conntrack' into
``ConntrackEntry`` objects for assertions on specific fields, and
``format_ct()`` produces the same text as ``FORMAT_CT`` in Autotest.
"""

import re

from tests.lib.cmd import run


def _split_top_level(text):
    """Split ``text`` on commas that are not inside parentheses."""
    parts, depth, start = [], 0, 0
    for i, c in enumerate(text):
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
        elif c == "," and depth == 0:
            parts.append(text[start:i])
            start = i + 1
    parts.append(text[start:])
    return [p for p in parts if p]


def _parse_fields(text):
    fields = {}
    for part in _split_top_level(text):
        key, sep, value = part.partition("=")
        if not sep:
            fields[key] = None
        elif value.startswith("(") and value.endswith(")"):
            fields[key] = _parse_fields(value[1:-1])
        else:
            fields[key] = value
    return fields


class ConntrackEntry:
    """A parsed conntrack entry.

    Attributes:
        proto: Protocol name, e.g., 'tcp' or 'icmp'.
        orig: Dict of the original direction tuple, e.g.,
            {'src': '10.1.1.1', 'dst': '10.1.1.2', 'sport': '34567', ...}.
        reply: Dict of the reply direction tuple.
        zone: Zone as an int, 0 if not shown.
        mark: Mark as an int, 0 if not shown.
        labels: Labels as an int, 0 if not shown.
        protoinfo: Dict of protocol information, e.g., {'state': 'SYN_SENT'}.
        fields: All the fields as a dict.
        line: The original line.
    """

    def __init__(self, line):
        self.line = line.strip()
        proto, _, rest = self.line.partition(",")
        self.proto = proto
        self.fields = _parse_fields(rest)
        self.orig = self.fields.get("orig") or {}
        self.reply = self.fields.get("reply") or {}
        self.protoinfo = self.fields.get("protoinfo") or {}
        self.zone = int(self.fields.get("zone", 0))
        self.mark = int(self.fields.get("mark", "0"), 0)
        self.labels = int(self.fields.get("labels", "0"), 0)

    @property
    def state(self):
        return self.protoinfo.get("state")

    def __repr__(self):
        return "ConntrackEntry(%r)" % self.line


def dump_conntrack(node=None, zone=None, ip=None, args=""):
    """Dump the conntrack table of the datapath.

    Args:
        node: The ``OVSNode`` to run 'ovs-appctl' for, or None to use the
            process environment.
        zone: Only dump entries of this zone.
        ip: Only return entries whose original destination is ``ip``.
        args: Additional arguments for 'dpctl/dump-conntrack'.

    Returns:
        A list of ``ConntrackEntry``.
    """
    cmd = "ovs-appctl dpctl/dump-conntrack"
    if zone is not None:
        cmd += " zone=%d" % zone
    if args:
        cmd += " " + args
    r = node.run(cmd, stdout=True) if node else run(cmd, stdout=True)
    entries = [ConntrackEntry(line) for line in r.stdout.splitlines()
               if line.strip()]
    if ip is not None:
        entries = [e for e in entries if e.orig.get("dst") == ip]
    return entries


def format_ct(output, ip):
    """Filter conntrack dump ``output`` like FORMAT_CT([ip]).

    Keeps the lines with 'dst=<ip>', clears ports, IDs and states, and
    returns the sorted unique lines as a list.
    """
    lines = set()
    for line in output.splitlines():
        if "dst=" + ip not in line:
            continue
        line = re.sub(r"port=[0-9]*", "port=<cleared>", line)
        line = re.sub(r"id=[0-9]*", "id=<cleared>", line)
        line = re.sub(r"state=[0-9_A-Z]*", "state=<cleared>", line)
        lines.add(line)
    return sorted(lines)


def flush_conntrack(node=None, args=""):
    """Flush the conntrack table of the datapath."""
    cmd = "ovs-appctl dpctl/flush-conntrack " + args
    return node.run(cmd) if node else run(cmd)
