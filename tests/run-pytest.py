#! /usr/bin/env python3
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

"""Run pytest-based OVS tests from the Makefile.

  PYTESTFLAGS     Passed to pytest as is (split with shell rules).
  RECHECK=yes     Failed tests are run once more at the end ('--lf'),
                  unless a sanitizer reported an error.

If tests run in parallel ('-n' in PYTESTFLAGS) and pytest-xdist supports it,
tests are sent to workers one by one ('--maxschedchunk=1'), unless the
distribution is configured in PYTESTFLAGS.  By default, pytest-xdist sends
chunks of consecutive tests to each worker, which is not good for the
Autotest tests: long tests are often next to each other.

Exits with status 77 if a usable pytest is not available, so the caller
can fall back to a plain Autotest run.
"""

import argparse
import glob
import os
import re
import shlex
import shutil
import subprocess
import sys

PYTEST_MIN_VERSION = (6, 2)

EXIT_UNAVAILABLE = 77
# pytest exit codes.
EXIT_OK = 0
EXIT_TESTS_FAILED = 1
EXIT_NO_TESTS_COLLECTED = 5


def version_tuple(version):
    parts = []
    for part in version.split(".")[:3]:
        m = re.match(r"\d+", part)
        if not m:
            break
        parts.append(int(m.group()))
    return tuple(parts)


def module_version(name):
    """Return the version of module ``name`` or None if not available."""
    try:
        module = __import__(name)
    except Exception:
        return None
    return version_tuple(getattr(module, "__version__", "0"))


def has_option(args, *names):
    """Whether any of the options ``names`` is in ``args``."""
    for arg in args:
        for name in names:
            if arg == name or arg.startswith(name + "=") \
                    or (len(name) == 2 and arg.startswith(name)
                        and not arg.startswith("--")):
                return True
    return False


def xdist_args(user_args):
    """Return default pytest-xdist arguments for ``user_args``."""
    if not has_option(user_args, "-n", "--numprocesses") \
            or has_option(user_args, "--dist", "--maxschedchunk", "-d"):
        return []
    version = module_version("xdist")
    if version is None or version < (3, 4):
        return []
    return ["--maxschedchunk=1"]


def sanitizer_reports(basetemp):
    """Return sanitizer reports from pytest and Autotest test directories."""
    rundir = os.path.dirname(basetemp)
    dirs = [basetemp]
    for pattern in ("*testsuite.gw[0-9]*.dir", "*testsuite.pytest.dir"):
        dirs += glob.glob(os.path.join(rundir, pattern))
    # Reports are in the test directories, one level down.  Deeper levels
    # are, e.g., temporary directories of tests, with anything inside.
    reports = []
    for d in dirs:
        reports += glob.glob(os.path.join(d, "*", "sanitizers.*"))
    return reports


def remove_autotest_artifacts(rundir):
    """Remove leftovers of Autotest testsuites run by previous runs."""
    for pattern in ("*testsuite.gw[0-9]*", "*testsuite.pytest*"):
        for path in glob.glob(os.path.join(rundir, pattern)):
            if os.path.isdir(path) and not os.path.islink(path):
                shutil.rmtree(path, ignore_errors=True)
            else:
                os.unlink(path)


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--pytestflags", default="",
                        help="Extra pytest flags (PYTESTFLAGS).")
    parser.add_argument("--recheck", default="",
                        help="'yes' to rerun failed tests (RECHECK).")
    parser.add_argument("--basetemp", required=True,
                        help="Directory for test artifacts.")
    parser.add_argument("--cache-dir", required=True,
                        help="pytest cache directory.")
    parser.add_argument("args", nargs="*",
                        help="Test paths and other pytest arguments.")
    opts = parser.parse_args()

    pytest_version = module_version("pytest")
    if pytest_version is None:
        print("pytest is not available for %s." % sys.executable)
        return EXIT_UNAVAILABLE
    if pytest_version < PYTEST_MIN_VERSION:
        print("pytest %s is too old, at least %s is required."
              % (".".join(map(str, pytest_version)),
                 ".".join(map(str, PYTEST_MIN_VERSION))))
        return EXIT_UNAVAILABLE

    args = [sys.executable, "-m", "pytest",
            "--basetemp=" + opts.basetemp,
            "-o", "cache_dir=" + opts.cache_dir]
    args += opts.args
    user_args = shlex.split(opts.pytestflags)
    args += xdist_args(user_args) + user_args

    remove_autotest_artifacts(os.path.dirname(opts.basetemp))

    print(" ".join(shlex.quote(a) for a in args), flush=True)
    rc = subprocess.call(args)
    if rc == EXIT_NO_TESTS_COLLECTED:
        rc = EXIT_OK

    if rc == EXIT_TESTS_FAILED and opts.recheck == "yes":
        if sanitizer_reports(opts.basetemp):
            print("Sanitizer errors detected, not rechecking.")
            return rc
        print("Rechecking failed tests.", flush=True)
        recheck_args = [a for a in args
                        if not a.startswith("--basetemp=")]
        recheck_args += ["--basetemp=" + opts.basetemp + ".recheck",
                         "--last-failed", "--last-failed-no-failures=none"]
        print(" ".join(shlex.quote(a) for a in recheck_args), flush=True)
        rc = subprocess.call(recheck_args)

    return rc


if __name__ == "__main__":
    sys.exit(main())
