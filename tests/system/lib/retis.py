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

"""Packet tracing with retis for system tests on the kernel datapath.

With ``--retis`` (or OVS_TEST_WITH_RETIS=yes in the environment, as for
the Autotest testsuites), every test on the kernel datapath runs 'retis
collect' while the OVS bridge is up, like RETIS_CHECK_AND_RUN() does for
the Autotest tests.  The test directory gets:

- ``retis.err``: stderr of 'retis collect';
- ``retis.log``: stdout of 'retis collect', the events as they happen;
- ``retis.data``: the raw events, for 'retis sort' and other commands;
- ``retis.sorted``: output of 'retis sort' on retis.data.

retis probes are global, they see packets of all network namespaces, even
if retis runs in the namespace of the test.  When tests run in parallel,
the capture is limited to packets on the network devices of the network
namespace of the test, which has the OVS ports and the datapath.  Packets
inside the other namespaces of the test (``at_ns0`` and so on) or without
a device are not captured then.  The OVS collector is not used either,
since retis finds ovs-vswitchd by its name and can't tell which of the
running instances belongs to the test.
"""

import os
import shutil

from tests.lib.cmd import run, wait_until


def enabled(config):
    return config.getoption("retis") \
        or os.environ.get("OVS_TEST_WITH_RETIS") == "yes"


def configure(config):
    """Set up the environment for retis.  Returns an error message or None.
    """
    if not enabled(config):
        return None
    if shutil.which("retis") is None:
        return "retis is not installed"
    # For the Autotest tests, see RETIS_CHECK_AND_RUN().
    os.environ["OVS_TEST_WITH_RETIS"] = "yes"
    return None


def parallel(config):
    """Whether other tests run at the same time."""
    # Set by pytest-xdist in the workers, which don't see 'numprocesses'.
    return int(os.environ.get("PYTEST_XDIST_WORKER_COUNT", "1")) > 1


def netns_filter():
    """Return a retis meta filter for the network namespace of the caller.
    """
    path = "/proc/thread-self/ns/net"
    if not os.path.exists(path):
        path = "/proc/self/ns/net"
    return "sk_buff.dev.nd_net.net.ns.inum == %d" % os.stat(path).st_ino


def autotest_environment(config):
    """Return environment variables for an Autotest test, see
    RETIS_CHECK_AND_RUN().  Must be called in the namespace of the test.
    """
    if not enabled(config) or not parallel(config):
        return {}
    return {"OVS_TEST_RETIS_FILTER": netns_filter()}


class Capture:
    """'retis collect' running in the background for a test."""

    def __init__(self, node, test_dir, meta_filter=None):
        self.test_dir = str(test_dir)
        cmd = ["retis", "-p", "ifdump", "collect", "--utc",
               "--allow-system-changes",
               "--out", os.path.join(self.test_dir, "retis.data"),
               "--print"]
        if meta_filter:
            cmd += ["-m", "'%s'" % meta_filter,
                    "--collectors", "skb-tracking,skb,skb-drop,ct,dev,ns"]
        else:
            cmd += ["--ovs-track"]
        err = os.path.join(self.test_dir, "retis.err")
        self.proc = node.start_background(
            " ".join(cmd), stdout=os.path.join(self.test_dir, "retis.log"),
            stderr=err)
        wait_until(lambda: "loaded" in _read(err) or not self.proc.alive(),
                   description="retis to load its probes")
        if not self.proc.alive():
            raise RuntimeError("retis failed to start:\n" + _read(err))

    def stop(self):
        self.proc.stop()
        data = os.path.join(self.test_dir, "retis.data")
        if os.path.exists(data):
            run("retis sort --utc %s > %s"
                % (data, os.path.join(self.test_dir, "retis.sorted")),
                rc=None, stderr=True)


def _read(path):
    try:
        with open(path) as f:
            return f.read()
    except OSError:
        return ""
