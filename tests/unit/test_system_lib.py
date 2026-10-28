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

"""Tests for the parts of tests.system.lib that don't need root."""

import pytest

from tests.system.lib.conntrack import ConntrackEntry, format_ct
from tests.system.lib.ping import PingResult, parse_ping


class TestPing:
    def test_parse(self):
        assert parse_ping(
            "PING 10.1.1.2 (10.1.1.2) 56(84) bytes of data.\n\n"
            "--- 10.1.1.2 ping statistics ---\n"
            "3 packets transmitted, 3 received, 0% packet loss, time 405ms\n"
            "rtt min/avg/max/mdev = 0.04/0.05/0.08/0.01 ms\n") \
            == PingResult(3, 3)
        assert parse_ping("7 packets transmitted, 0 received, "
                          "100% packet loss, time 2050ms\n") \
            == PingResult(7, 0)
        # BusyBox and FreeBSD style.
        assert parse_ping("3 packets transmitted, 2 packets received, "
                          "33.3% packet loss\n") == PingResult(3, 2)

    def test_parse_error(self):
        with pytest.raises(ValueError):
            parse_ping("ping: connect: Network is unreachable\n")


DUMP = """\
icmp,orig=(src=10.1.1.1,dst=10.1.1.2,id=4321,type=8,code=0),\
reply=(src=10.1.1.2,dst=10.1.1.1,id=4321,type=0,code=0),zone=1
tcp,orig=(src=10.1.1.1,dst=10.1.1.2,sport=45678,dport=80),\
reply=(src=10.1.1.2,dst=10.1.1.1,sport=80,dport=45678),zone=1,mark=0x10,\
labels=0x200000001,protoinfo=(state=TIME_WAIT)
udp,orig=(src=10.1.1.2,dst=10.1.1.20,sport=1,dport=2),\
reply=(src=10.1.1.20,dst=10.1.1.2,sport=2,dport=1)
"""


class TestConntrack:
    def test_entry(self):
        icmp, tcp, udp = [ConntrackEntry(line)
                          for line in DUMP.splitlines()]
        assert icmp.proto == "icmp"
        assert icmp.orig == {"src": "10.1.1.1", "dst": "10.1.1.2",
                             "id": "4321", "type": "8", "code": "0"}
        assert icmp.reply["src"] == "10.1.1.2"
        assert icmp.zone == 1 and icmp.mark == 0 and icmp.state is None
        assert tcp.orig["dport"] == "80"
        assert tcp.mark == 0x10
        assert tcp.labels == 0x200000001
        assert tcp.state == "TIME_WAIT"
        assert udp.zone == 0

    def test_format_ct(self):
        # Same as FORMAT_CT(10.1.1.2): 'dst=10.1.1.2' is a substring match.
        assert format_ct(DUMP, "10.1.1.2") == [
            "icmp,orig=(src=10.1.1.1,dst=10.1.1.2,id=<cleared>,type=8,"
            "code=0),reply=(src=10.1.1.2,dst=10.1.1.1,id=<cleared>,type=0,"
            "code=0),zone=1",
            "tcp,orig=(src=10.1.1.1,dst=10.1.1.2,sport=<cleared>,"
            "dport=<cleared>),reply=(src=10.1.1.2,dst=10.1.1.1,"
            "sport=<cleared>,dport=<cleared>),zone=1,mark=0x10,"
            "labels=0x200000001,protoinfo=(state=<cleared>)",
            "udp,orig=(src=10.1.1.2,dst=10.1.1.20,sport=<cleared>,"
            "dport=<cleared>),reply=(src=10.1.1.20,dst=10.1.1.2,"
            "sport=<cleared>,dport=<cleared>)",
        ]
        assert format_ct(DUMP, "192.168.0.1") == []
