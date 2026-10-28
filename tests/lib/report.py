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

"""Per-test artifact directories and failure reporting.

Every test runs in its own directory under the pytest base temporary
directory (``tests/pytest.dir`` when started from the Makefile), the
same way Autotest runs each test in ``tests/testsuite.dir/NNNN``.  The
directory holds:

 - ``pytest.log`` -- transcript of all commands run by the test and
   the failure report, if any.
 - daemon logs, databases and other files created by the test.
 - ``sanitizers.*`` -- AddressSanitizer / UBSan reports, if any.

The directory is removed after a successful test, unless
``--keep-artifacts`` is given, and preserved otherwise.

This module is a pytest plugin, its hooks and fixtures are registered
by ``tests/conftest.py``.
"""

import glob
import logging
import os
import re
import shutil

import pytest

log = logging.getLogger("ovs.test")

_LOG_FORMAT = "%(asctime)s.%(msecs)03d %(message)s"
_LOG_DATE_FORMAT = "%H:%M:%S"


def pytest_addoption(parser):
    parser.addoption(
        "--keep-artifacts", action="store_true", default=False,
        help="Keep test directories of successful tests "
             "(like Autotest's -d).")


def _artifacts_root(config, tmp_path_factory):
    # getbasetemp() cleans up the base directory on first use, so it must
    # be called before creating anything in there.
    root = str(tmp_path_factory.getbasetemp())
    if hasattr(config, "workerinput"):
        # xdist workers get a 'popen-gwN' subdirectory of the common base
        # directory, prepared by the controller.  Test directory names are
        # unique, and a flat layout is easier to browse.
        root = os.path.dirname(root)
    return root


def _dir_name(nodeid):
    """Make a directory name from a node ID.

    For example, 'unit/test_a.py::TestA::test_x[1-2]' becomes
    'unit.test_a.TestA.test_x_1-2'.
    """
    name = nodeid.replace(".py::", ".").replace("::", ".").replace("/", ".")
    name = re.sub(r"[^A-Za-z0-9_.=+-]+", "_", name).strip("_")
    return name[:200]


def artifact_dir(item):
    """Return the artifact directory of a test item, or None."""
    return getattr(item, "_ovs_test_dir", None)


@pytest.fixture(autouse=True)
def test_dir(request, tmp_path_factory, monkeypatch):
    """Per-test artifact and working directory.

    The test runs with this directory as the current working directory,
    and with the sanitizers configured to write their reports into it.
    """
    root = _artifacts_root(request.config, tmp_path_factory)
    path = os.path.join(root, _dir_name(request.node.nodeid))
    shutil.rmtree(path, ignore_errors=True)
    os.makedirs(path)
    request.node._ovs_test_dir = path

    monkeypatch.chdir(path)

    # Same as tests/atlocal.in, but the reports go to the test directory.
    sanitizers = os.path.join(path, "sanitizers")
    monkeypatch.setenv(
        "ASAN_OPTIONS", "detect_leaks=0:abort_on_error=true:log_path=%s:%s"
        % (sanitizers, os.environ.get("ASAN_OPTIONS", "")))
    monkeypatch.setenv(
        "UBSAN_OPTIONS", "print_stacktrace=1:halt_on_error=true:"
        "log_path=%s:%s" % (sanitizers, os.environ.get("UBSAN_OPTIONS", "")))

    handler = logging.FileHandler(os.path.join(path, "pytest.log"))
    handler.setFormatter(logging.Formatter(_LOG_FORMAT, _LOG_DATE_FORMAT))
    handler.setLevel(logging.DEBUG)
    log.addHandler(handler)
    log.setLevel(logging.DEBUG)
    try:
        yield path
    finally:
        log.removeHandler(handler)
        handler.close()

    # This fixture is set up before all others (it is autouse), so it is
    # torn down after them, i.e., after all the daemons are stopped and
    # had a chance to report sanitizer errors on exit.
    reports = sanitizer_reports(path)
    if reports:
        pytest.fail("Sanitizer reported errors:\n\n" + reports,
                    pytrace=False)


def sanitizer_reports(path):
    """Return the contents of sanitizer reports in ``path``."""
    reports = []
    for name in sorted(glob.glob(os.path.join(path, "sanitizers.*"))):
        try:
            with open(name, errors="replace") as f:
                content = f.read()
        except OSError:
            continue
        if content.strip():
            reports.append("=== %s ===\n%s" % (os.path.basename(name),
                                               content))
    return "\n".join(reports)


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    rep = outcome.get_result()
    setattr(item, "_ovs_rep_" + rep.when, rep)

    path = artifact_dir(item)
    if not rep.failed or not path or not os.path.isdir(path):
        return

    try:
        with open(os.path.join(path, "pytest.log"), "a") as f:
            f.write("\n=== FAILURE (%s) ===\n%s\n" % (rep.when, rep.longrepr))
    except OSError:
        pass
    rep.sections.append(("Artifacts", "Test directory: %s\n" % path))


@pytest.hookimpl(trylast=True)
def pytest_runtest_teardown(item, nextitem):
    # Not reached if teardown of a fixture failed, so the directory of
    # such a test is preserved as well.
    if item.config.getoption("keep_artifacts"):
        return
    for when in ("setup", "call"):
        rep = getattr(item, "_ovs_rep_" + when, None)
        if rep is None or rep.failed:
            return
    path = artifact_dir(item)
    if path:
        shutil.rmtree(path, ignore_errors=True)
