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

"""Connectivity checks with ping.

Replaces 'ping ... | FORMAT_PING' with expected output in Autotest.
"""

import re
from collections import namedtuple

from tests.lib.cmd import run

PingResult = namedtuple("PingResult", ["transmitted", "received"])


def parse_ping(output):
    """Parse the summary of ping output into a ``PingResult``.

    Raises:
        ValueError: if there is no summary in ``output``.
    """
    m = re.search(r"(\d+) packets transmitted, (\d+) (?:packets )?received",
                  output)
    if not m:
        raise ValueError("No ping summary in output:\n" + output)
    return PingResult(int(m.group(1)), int(m.group(2)))


def ping(dst, ns=None, count=3, interval=0.3, timeout=2, size=None,
         deadline=None, args=""):
    """Ping ``dst`` and return a ``PingResult``.

    IPv6 is used if ``dst`` contains a colon.

    Args:
        dst: Destination address.
        ns: Namespace to ping from.
        count: Number of packets.
        interval: Interval between packets in seconds.
        timeout: Time to wait for each reply in seconds (-W).
        size: Optional payload size (-s).
        deadline: Optional total time limit in seconds (-w).  Replaces
            ``timeout``.
        args: Additional ping arguments.
    """
    cmd = ["ping", "-6" if ":" in dst else "-4", "-q", "-c", str(count),
           "-i", str(interval)]
    if deadline is not None:
        cmd += ["-w", str(deadline)]
    else:
        cmd += ["-W", str(timeout)]
    if size is not None:
        cmd += ["-s", str(size)]
    if args:
        cmd.append(args)
    cmd.append(dst)
    r = run(" ".join(cmd), ns=ns, rc=None, stdout=True, stderr=True)
    return parse_ping(r.stdout)


def check_ping(dst, ns=None, count=3, expect_loss=False, **kwargs):
    """Ping ``dst`` and check that all, or no, replies are received.

    Equivalent of::

        NS_CHECK_EXEC([ns], [ping -q -c 3 -i 0.3 -W 2 dst | FORMAT_PING],
                      [0], [3 packets transmitted, 3 received, ...])

    or, with ``expect_loss=True``, of the same with '-w 2' and
    '..., 0 received, 100% packet loss' as the expected output.

    Args:
        dst: Destination address.
        ns: Namespace to ping from.
        count: Number of packets.
        expect_loss: If True, check that no replies are received within
            a 2 second deadline (or ``deadline``).
        **kwargs: Additional arguments for ``ping()``.
    """
    __tracebackhide__ = True
    if expect_loss:
        kwargs.setdefault("deadline", 2)
        result = ping(dst, ns=ns, count=count, **kwargs)
        assert result.transmitted > 0 and result.received == 0, \
            "ping %s: expected no replies, got %d of %d" % (
                dst, result.received, result.transmitted)
    else:
        result = ping(dst, ns=ns, count=count, **kwargs)
        assert result == PingResult(count, count), \
            "ping %s: expected %d of %d replies, got %d" % (
                dst, count, count, result.received)
