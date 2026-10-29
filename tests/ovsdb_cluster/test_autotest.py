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

"""The OVSDB cluster Autotest testsuite (tests/ovsdb-cluster-testsuite), run
through pytest.

Artifacts of failed tests are in 'tests/ovsdb-cluster-testsuite.<worker>.dir'.
"""

import os

import pytest

from tests.lib import env
from tests.lib.autotest import AutotestSuite

SUITE = AutotestSuite(
    os.path.join(env.srcdir(), "tests", "ovsdb-cluster-testsuite"),
    os.path.join(env.builddir(), "tests"))


@pytest.fixture(scope="session")
def autotest_runner(request):
    yield from SUITE.runner(request)


@SUITE.parametrize
def test_autotest(autotest_runner, number):
    SUITE.run(autotest_runner, number)
