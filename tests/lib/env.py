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

"""Test environment setup.

The Makefile passes ``abs_top_srcdir``, ``abs_top_builddir`` and
``AUTOTEST_PATH`` in the environment.  When pytest is started by hand,
the source directory is derived from the location of this file and the
build directory defaults to the source directory.
"""

import os
import sys

_DEFAULT_AUTOTEST_PATH = "utilities:vswitchd:ovsdb:vtep:tests:ipsec"


def srcdir():
    """Return the absolute path of the top source directory."""
    d = os.environ.get("abs_top_srcdir")
    if d:
        return d
    return os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))))


def builddir():
    """Return the absolute path of the top build directory."""
    return os.environ.get("abs_top_builddir") or srcdir()


def setup():
    """Configure the process environment for running OVS tests.

    Prepends the directories from ``AUTOTEST_PATH`` (relative to the
    build directory) to ``PATH``, so the freshly built binaries are
    used, and sets the variables that ``tests/atlocal.in`` sets for
    Autotest.  Safe to call more than once.
    """
    python_dir = os.path.join(srcdir(), "python")
    if python_dir not in sys.path:
        sys.path.insert(0, python_dir)

    if os.environ.get("OVS_TEST_ENV_READY"):
        return

    autotest_path = os.environ.get("AUTOTEST_PATH", _DEFAULT_AUTOTEST_PATH)
    dirs = []
    for d in autotest_path.split(":"):
        if d:
            dirs.append(d if os.path.isabs(d) else
                        os.path.join(builddir(), d))
    os.environ["PATH"] = os.pathsep.join(dirs + [os.environ["PATH"]])

    os.environ["abs_top_srcdir"] = srcdir()
    os.environ["abs_top_builddir"] = builddir()

    os.environ.setdefault("OVS_CTL_TIMEOUT", "30")
    os.environ["OVS_SYSLOG_METHOD"] = "null"
    os.environ["LC_ALL"] = "C"
    for var in ("http_proxy", "https_proxy", "ftp_proxy", "no_proxy",
                "HTTP_PROXY", "HTTPS_PROXY", "FTP_PROXY", "NO_PROXY"):
        os.environ.pop(var, None)
    if sys.platform.startswith("linux"):
        os.environ["MALLOC_PERTURB_"] = "165"
        os.environ["MALLOC_CHECK_"] = "2"

    # Python scripts started by tests (e.g., test-l7.py) and the tests
    # themselves (e.g., ovs.flow parsers) use the in-tree library.
    os.environ["PYTHONPATH"] = os.pathsep.join(
        [python_dir] + [p for p in [os.environ.get("PYTHONPATH")] if p])
    os.environ["PYTHONCOERCECLOCALE"] = "0"
    os.environ["PYTHONIOENCODING"] = "utf_8"
    os.environ["PYTHONDONTWRITEBYTECODE"] = "yes"

    os.environ["OVS_TEST_ENV_READY"] = "1"
