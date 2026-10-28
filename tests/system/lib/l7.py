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

"""Application level helpers: L7 servers, HTTP clients, netcat."""

import os
import subprocess
import sys

from tests.lib.cmd import run, wait_until
from tests.lib.env import srcdir

DEFAULT_PORTS = {"http": 80, "http6": 80, "ftp": 21, "tftp": 69}


def start_l7(node, ns, proto, port=None):
    """Start a 'proto' server in ``ns`` and wait until it listens.

    Like OVS_START_L7.  The server runs tests/test-l7.py in the current
    directory, so it serves files from the test directory.  It is stopped
    when ``node`` stops, or earlier with ``stop()`` on the returned
    ``BackgroundProcess``.

    Args:
        node: The ``OVSNode`` that owns the server process.
        ns: Network namespace to run the server in.
        proto: 'http', 'http6', 'ftp' or 'tftp'.
        port: Port number, defaults to the standard port of ``proto``.
    """
    script = os.path.join(srcdir(), "tests", "test-l7.py")
    cmd = "%s %s %s" % (sys.executable, script, proto)
    if port is not None:
        cmd += " %d" % port
    else:
        port = DEFAULT_PORTS[proto]
    proc = node.start_background(cmd, ns=ns,
                                 stdout="l7-%s-%d.log" % (proto, port),
                                 stderr="l7-%s-%d.err" % (proto, port))

    def server_listening():
        if not proc.alive():
            raise RuntimeError("%s server exited with status %s"
                               % (proto, proc.returncode))
        return listening(port, ns=ns, udp=proto == "tftp")

    wait_until(server_listening, description="%s server listens on port %d"
               % (proto, port))
    return proc


def listening(port, ns=None, udp=False):
    """Whether a TCP (or UDP) socket listens on ``port`` in ``ns``."""
    r = run("ss -Hln %s" % ("-u" if udp else "-t"), ns=ns, stdout=True)
    return any(fields[3].endswith(":%d" % port)
               for fields in map(str.split, r.stdout.splitlines())
               if len(fields) > 3)


def http_get(url, ns=None, args="", **kwargs):
    """Fetch ``url`` with curl, like OVS_GET_HTTP.

    Returns the ``run()`` result.  Additional keyword arguments are passed
    to ``run()``, by default any output is accepted.
    """
    kwargs.setdefault("stdout", True)
    kwargs.setdefault("stderr", True)
    return run("curl %s --retry 3 --max-time 1 --retry-connrefused -v %s"
               % (url, args), ns=ns, **kwargs)


_nc_eof_opt = None


def nc_eof_opt():
    """Return netcat options to exit after sending the input.

    Same as NC_EOF_OPT in tests/atlocal.in.
    """
    global _nc_eof_opt
    if _nc_eof_opt is None:
        r = subprocess.run("nc --version", shell=True,
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                           universal_newlines=True)
        if "nmap.org" in r.stdout:
            _nc_eof_opt = "--send-only -w 5"
        else:
            _nc_eof_opt = "-q 1 -w 5"
    return _nc_eof_opt
