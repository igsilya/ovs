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

"""Command line options for system tests.

Registered by tests/conftest.py, since pytest only registers options of
conftest.py files that are loaded on startup, and tests/system/conftest.py
is not when tests are started for the whole tests/ directory.
"""


def add_options(parser):
    group = parser.getgroup("ovs-system", "OVS system tests")
    group.addoption("--datapath", choices=("system", "userspace"),
                    default="system",
                    help="Datapath for system tests (default: system).")
    group.addoption("--offload", action="store_true", default=False,
                    help="Enable hardware offload.")
    group.addoption("--tso", action="store_true", default=False,
                    help="Enable userspace TSO.")
    group.addoption("--afxdp", action="store_true", default=False,
                    help="Use AF_XDP ports.")
    group.addoption("--dpdk", action="store_true", default=False,
                    help="Use DPDK.")
    group.addoption("--retis", action="store_true", default=False,
                    help="Trace packets of tests on the kernel datapath "
                         "with retis.")
