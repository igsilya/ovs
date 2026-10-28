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

"""Tests for tests.lib.report, the per-test artifact handling."""

import os

import pytest


@pytest.fixture
def inner(pytester):
    # The inner session may run inside the source tree (tests/pytest.dir),
    # don't let it pick up the ini file and conftest.py files from there.
    pytester.makeini("[pytest]")
    basetemp = pytester.path / "artifacts"

    def run(*args):
        return pytester.runpytest(
            "--confcutdir=%s" % pytester.path, "-p", "tests.lib.report",
            "-W", "ignore::pytest.PytestAssertRewriteWarning",
            "--basetemp=%s" % basetemp, *args)

    run.basetemp = basetemp
    return run


def test_dir_is_cwd_and_has_log(pytester, inner):
    pytester.makepyfile(test_a="""
        import os
        from tests.lib.cmd import run

        def test_pass(test_dir):
            assert os.getcwd() == test_dir
            run("echo hello", stdout=True)
            log = open("pytest.log").read()
            assert "$ echo hello" in log
            assert "hello" in log
    """)
    result = inner()
    result.assert_outcomes(passed=1)
    assert not (inner.basetemp / "test_a.test_pass").exists()


def test_keep_artifacts(pytester, inner):
    pytester.makepyfile(test_a="""
        def test_pass():
            open("file", "w").close()
    """)
    inner("--keep-artifacts").assert_outcomes(passed=1)
    assert (inner.basetemp / "test_a.test_pass" / "file").exists()
    assert (inner.basetemp / "test_a.test_pass" / "pytest.log").exists()


def test_failure_preserved(pytester, inner):
    pytester.makepyfile(test_a="""
        import pytest
        from tests.lib.cmd import run

        @pytest.mark.parametrize("x", [1, 2])
        def test_fail(x):
            run("echo output; false", stdout=True)
    """)
    result = inner()
    result.assert_outcomes(failed=2)
    for x in (1, 2):
        path = inner.basetemp / ("test_a.test_fail_%d" % x)
        log = (path / "pytest.log").read_text()
        assert "$ echo output; false" in log
        assert "=== FAILURE (call) ===" in log
        assert "Command failed" in log
    result.stdout.fnmatch_lines(["*Artifacts*",
                                 "Test directory: *test_a.test_fail_1"])


def test_setup_failure_preserved(pytester, inner):
    pytester.makepyfile(test_a="""
        import pytest

        @pytest.fixture
        def broken():
            raise RuntimeError("broken fixture")

        def test_x(broken):
            pass
    """)
    inner().assert_outcomes(errors=1)
    log = (inner.basetemp / "test_a.test_x" / "pytest.log").read_text()
    assert "=== FAILURE (setup) ===" in log


def test_teardown_failure_preserved(pytester, inner):
    pytester.makepyfile(test_a="""
        import pytest

        @pytest.fixture
        def broken():
            yield
            raise RuntimeError("broken teardown")

        def test_x(broken):
            pass
    """)
    result = inner()
    result.assert_outcomes(passed=1, errors=1)
    log = (inner.basetemp / "test_a.test_x" / "pytest.log").read_text()
    assert "=== FAILURE (teardown) ===" in log


def test_sanitizer_report(pytester, inner):
    pytester.makepyfile(test_a="""
        import os
        import pytest

        @pytest.fixture
        def daemon():
            yield
            # A daemon reports an error on exit, after the test body.
            path = os.environ["ASAN_OPTIONS"].split("log_path=")[1]
            path = path.split(":")[0]
            with open(path + ".1234", "w") as f:
                f.write("ERROR: AddressSanitizer: heap-use-after-free\\n")

        def test_x(daemon):
            assert "detect_leaks=0" in os.environ["ASAN_OPTIONS"]
            assert "print_stacktrace=1" in os.environ["UBSAN_OPTIONS"]
    """)
    result = inner()
    result.assert_outcomes(passed=1, errors=1)
    result.stdout.fnmatch_lines(["*Sanitizer reported errors*",
                                 "*heap-use-after-free*"])
    assert (inner.basetemp / "test_a.test_x" / "sanitizers.1234").exists()


def test_environment_restored(pytester, inner):
    pytester.makepyfile(test_a="""
        import os

        BASE = os.environ.get("ASAN_OPTIONS", "").count("log_path=")

        def test_1():
            assert os.environ["ASAN_OPTIONS"].count("log_path=") == BASE + 1

        def test_2():
            assert os.environ["ASAN_OPTIONS"].count("log_path=") == BASE + 1
    """)
    inner().assert_outcomes(passed=2)


def test_artifact_names_unique(pytester, inner):
    pytester.makepyfile(test_a="""
        class TestA:
            def test_x(self):
                assert False

        class TestB:
            def test_x(self):
                assert False
    """)
    inner().assert_outcomes(failed=2)
    assert sorted(os.listdir(inner.basetemp)) == [
        "test_a.TestA.test_x", "test_a.TestB.test_x"]
