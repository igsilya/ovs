..
      Licensed under the Apache License, Version 2.0 (the "License"); you may
      not use this file except in compliance with the License. You may obtain
      a copy of the License at

          http://www.apache.org/licenses/LICENSE-2.0

      Unless required by applicable law or agreed to in writing, software
      distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
      WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
      License for the specific language governing permissions and limitations
      under the License.

      Convention for heading levels in Open vSwitch documentation:

      =======  Heading 0 (reserved for the title in a document)
      -------  Heading 1
      ~~~~~~~  Heading 2
      +++++++  Heading 3
      '''''''  Heading 4

      Avoid deeper levels because they do not render well.

=======
Testing
=======

It is possible to test Open vSwitch using both tooling provided with Open
vSwitch and using a variety of third party tooling.

Built-in Tooling
----------------

Open vSwitch provides a number of different test suites and other tooling for
validating basic functionality of OVS. Before running any of the tests
described here, you must bootstrap, configure and build Open vSwitch as
described in :doc:`/intro/install/general`. You do not need to install Open
vSwitch or to build or load the kernel module to run these test suites. You do
not need supervisor privilege to run these test suites.

Unit Tests
~~~~~~~~~~

Open vSwitch includes a suite of self-tests. Before you submit patches
upstream, we advise that you run the tests and ensure that they pass. If you
add new features to Open vSwitch, then adding tests for those features will
ensure your features don't break as developers modify other areas of Open
vSwitch.

The tests run with `pytest`_, version 6.2 or newer.  Most of the unit tests
are in the Autotest testsuite (``tests/testsuite``), which runs through pytest
as well: every Autotest test is a separate pytest test.  If pytest is not
available, the Autotest testsuite runs directly, see `Running Autotest
directly`_.

To run all the unit tests in Open vSwitch, one at a time, run::

    $ make check

Additional arguments for pytest can be passed in the ``PYTESTFLAGS``
variable.  For example, to run the tests in parallel with 8 workers, install
`pytest-xdist`_ and run::

    $ make check PYTESTFLAGS=-n8

Tests are named after the file and the test function, e.g.,
``unit/test_ovs.py::TestOVSNodeDummy::test_lifecycle``.  Tests from the
Autotest testsuite are named after their number and title, e.g.,
``unit/test_autotest.py::test_autotest[0907-ofproto_-_echo_request]``.

To see a list of all the available tests, run::

    $ make check PYTESTFLAGS='--collect-only -q'

Tests do not have inter-dependencies, so you may run any subset.  To run
tests matching an expression, e.g., all the tests with ``ovsdb`` in the name,
or a single Autotest test by its number, run::

    $ make check PYTESTFLAGS='-k ovsdb'
    $ make check PYTESTFLAGS="-k 'test_autotest[0907'"

Run ``pytest --help`` for the complete list of pytest options.

Every test runs in a directory of its own.  Directories of failed tests are
preserved, and their paths are printed along with the failures:

* For pytest-based tests: ``tests/pytest.dir/<test name>/``.  The
  ``pytest.log`` file there has the transcript of all the commands the test
  ran, with their output, and the failure report.

* For Autotest tests: ``tests/testsuite.<worker>.dir/<N>/``, where
  ``<worker>`` is the name of the pytest-xdist worker that ran the test (e.g.,
  ``gw0``), or ``pytest`` if the tests didn't run in parallel.  The log of the
  test is in the ``testsuite.<worker>.log`` file in this directory.

Directories of successful tests are removed, unless ``--keep-artifacts`` is
added to ``PYTESTFLAGS``.  Report test failures as bugs and include these
logs in your report.

.. note::
  Sometimes a few tests may fail on some runs but not others. This is usually a
  bug in the testsuite, not a bug in Open vSwitch itself. If you find that a
  test fails intermittently, please report it, since the developers may not
  have noticed. You can make the testsuite automatically rerun tests that fail,
  by adding ``RECHECK=yes`` to the ``make`` command line, e.g.::

      $ make check PYTESTFLAGS=-n8 RECHECK=yes

.. _pytest: https://pytest.org
.. _pytest-xdist: https://pypi.org/project/pytest-xdist/

The tests of OVSDB clustering are in a separate testsuite, which runs the
same way::

    $ make check-ovsdb-cluster PYTESTFLAGS=-n8

Running Autotest directly
+++++++++++++++++++++++++

The Autotest testsuite can also run directly, without pytest::

    $ make check-autotest

Options for Autotest are passed in the ``TESTSUITEFLAGS`` variable.  For
example, to run test 123 and tests 477 through 484 in parallel, or the tests
matching keyword ``ovsdb``, run::

    $ make check-autotest TESTSUITEFLAGS='-j8 123 477-484'
    $ make check-autotest TESTSUITEFLAGS='-k ovsdb'

To see a complete list of Autotest options, run::

    $ make check-autotest TESTSUITEFLAGS=--help

The results of such a run are reported in ``tests/testsuite.log``.  The same
happens with ``make check`` if pytest is not available.

Debugging unit tests
++++++++++++++++++++

For pytest-based tests, add ``--pdb`` to ``PYTESTFLAGS`` to get into the
Python debugger when a test fails, e.g.::

  $ make check PYTESTFLAGS="--pdb -k test_lifecycle"

This happens before the test is cleaned up, so the OVS daemons of the test
are still running.  Their sockets are in the test directory, so OVS utilities
can be used from another terminal after setting ``OVS_RUNDIR`` to it.  The
commands for that are printed before the debugger starts, e.g.::

  ======================= test environment is still active =======================
  Test directory: <dir>/ovs/tests/pytest.dir/<test name>
  From another terminal, as root:
    export PATH=<dir>/ovs/utilities:<dir>/ovs/vswitchd:...
    export OVS_DBDIR=<dir>/ovs/tests/pytest.dir/<test name> OVS_RUNDIR=...

For system tests, these include the ``nsenter`` command that enters the
network and mount namespaces of the test, and ``ip netns exec`` commands for
the network namespaces that the test created.  Tests can't run in parallel
with ``--pdb``.

From the debugger itself, the same can be done with
``import os; os.system("ovs-ofctl dump-flows br0")``.

For Autotest tests, set the ``OVS_PAUSE_TEST`` environment variable to 1 to
pause on error.  This only works when Autotest runs directly.  For example,
to run test case 139 and pause on error::

  $ OVS_PAUSE_TEST=1 make check-autotest TESTSUITEFLAGS='-v 139'

When error occurs, above command would display something like this::

   Set environment variable to use various ovs utilities
   export OVS_RUNDIR=<dir>/ovs/_build-gcc/tests/testsuite.dir/0139
   Press ENTER to continue:

And from another window, one can execute ovs-xxx commands like::

   export OVS_RUNDIR=/opt/vdasari/Developer/ovs/_build-gcc/tests/testsuite.dir/0139
   $ ovs-ofctl dump-ports br0
   .
   .

Once done with investigation, press ENTER to perform cleanup operation.

.. _testing-coverage:

Coverage
~~~~~~~~

If the build was configured with ``--enable-coverage`` and the ``lcov`` utility
is installed, you can run the unit tests and generate a code coverage report
by using the ``check-lcov`` target::

    $ make check-lcov

The tests run the same way as with ``make check``, so the same options are
available.  For example::

    $ make check-lcov PYTESTFLAGS='-n8 -k ovsdb'

Similarly, if `coverage.py`_ is installed, the ``check-pycov`` target runs the
Python scripts of the Autotest tests under it and reports the coverage of the
Python code::

    $ make check-pycov PYTESTFLAGS=-n8

.. _coverage.py: https://coverage.readthedocs.io

.. _testing-valgrind:

Valgrind
~~~~~~~~

If you have ``valgrind`` installed, you can run the unit tests under
valgrind by using the ``check-valgrind`` target::

    $ make check-valgrind PYTESTFLAGS=-n8

The OVS programs that the tests run, both pytest-based and Autotest tests,
run under valgrind, and write their reports to ``valgrind.<pid>`` files in the
directories of the tests.  Directories of all the tests are kept, and the
reports with errors are listed at the end of the run.  Tests don't fail
because of the reported errors.

There are similar targets for the other testsuites, e.g.,
``check-kernel-valgrind`` for the kernel datapath and
``check-ovsdb-cluster-valgrind`` for OVSDB clustering, and the
``check-helgrind`` target, which runs the unit tests under helgrind.

The same can be done with the ``--valgrind`` and ``--helgrind`` pytest
options, which work with any target, as well as ``--strace``, which runs the
OVS programs under ``strace`` and writes the output of every process and
thread to ``strace.<pid>``, e.g.::

    $ make check-kernel PYTESTFLAGS="--strace -k test_ipv4_ping"

.. hint::
  You may find that the valgrind results are easier to interpret if you put
  ``-q`` in ``~/.valgrindrc``, since that reduces the amount of output.

OFTest
~~~~~~

OFTest is an OpenFlow protocol testing suite. Open vSwitch includes a Makefile
target to run OFTest with Open vSwitch in "dummy mode". In this mode of
testing, no packets travel across physical or virtual networks.  Instead, Unix
domain sockets stand in as simulated networks. This simulation is imperfect,
but it is much easier to set up, does not require extra physical or virtual
hardware, and does not require supervisor privileges.

To run OFTest with Open vSwitch, you must obtain a copy of OFTest and install
its prerequisites. You need a copy of OFTest that includes commit 406614846c5
(make ovs-dummy platform work again). This commit was merged into the OFTest
repository on Feb 1, 2013, so any copy of OFTest more recent than that should
work. Testing OVS in dummy mode does not require root privilege, so you may
ignore that requirement.

Optionally, add the top-level OFTest directory (containing the ``oft`` program)
to your ``$PATH``. This slightly simplifies running OFTest later.

To run OFTest in dummy mode, run the following command from your Open vSwitch
build directory::

    $ make check-oftest OFT=<oft-binary>

where ``<oft-binary>`` is the absolute path to the ``oft`` program in OFTest.
If you added "oft" to your $PATH, you may omit the OFT variable
assignment

By default, ``check-oftest`` passes ``oft`` just enough options to enable dummy
mode. You can use ``OFTFLAGS`` to pass additional options. For example, to run
just the ``basic.Echo`` test instead of all tests (the default) and enable
verbose logging, run::

    $ make check-oftest OFT=<oft-binary> OFTFLAGS='--verbose -T basic.Echo'

If you use OFTest that does not include commit 4d1f3eb2c792 (oft: change
default port to 6653), merged into the OFTest repository in October 2013, then
you need to add an option to use the IETF-assigned controller port::

    $ make check-oftest OFT=<oft-binary> OFTFLAGS='--port=6653'

Interpret OFTest results cautiously. Open vSwitch can fail a given test in
OFTest for many reasons, including bugs in Open vSwitch, bugs in OFTest, bugs
in the "dummy mode" integration, and differing interpretations of the OpenFlow
standard and other standards.

.. note::
  Open vSwitch has not been validated against OFTest. Report test failures that
  you believe to represent bugs in Open vSwitch. Include the precise versions
  of Open vSwitch and OFTest in your bug report, plus any other information
  needed to reproduce the problem.

Ryu
~~~

Ryu is an OpenFlow controller written in Python that includes an extensive
OpenFlow testsuite. Open vSwitch includes a Makefile target to run Ryu in
"dummy mode". See `OFTest`_ above for an explanation of dummy mode.

To run Ryu tests with Open vSwitch, first read and follow the instructions
under **Testing** above. Second, obtain a copy of Ryu, install its
prerequisites, and build it. You do not need to install Ryu (some of the tests
do not get installed, so it does not help).

To run Ryu tests, run the following command from your Open vSwitch build
directory::

    $ make check-ryu RYUDIR=<ryu-source-dir>

where ``<ryu-source-dir>`` is the absolute path to the root of the Ryu source
distribution. The default ``<ryu-source-dir>`` is ``$srcdir/../ryu``
where ``$srcdir`` is your Open vSwitch source directory. If this is correct,
omit ``RYUDIR``

.. note::
  Open vSwitch has not been validated against Ryu. Report test failures that
  you believe to represent bugs in Open vSwitch. Include the precise versions
  of Open vSwitch and Ryu in your bug report, plus any other information
  needed to reproduce the problem.

.. _datapath-testing:

Datapath testing
~~~~~~~~~~~~~~~~

Open vSwitch includes a suite of tests specifically for datapath functionality,
which can be run against the userspace or kernel datapaths. If you are
developing datapath features, it is recommended that you use these tests and
build upon them to verify your implementation.

The datapath tests make some assumptions about the environment. They must be
run under root privileges (more precisely, with CAP_SYS_ADMIN and
CAP_NET_ADMIN capabilities) on a Linux system with support for network
namespaces.  The tests are skipped otherwise.

The datapath tests run with pytest, the same way as unit tests, with the
datapath selected by the make target:

* ``check-kernel``: ``--datapath=system``
* ``check-offloads``: ``--datapath=system --offload``
* ``check-system-userspace``: ``--datapath=userspace``
* ``check-system-tso``: ``--datapath=userspace --tso``
* ``check-afxdp``: ``--datapath=userspace --afxdp``
* ``check-dpdk``: ``--datapath=userspace --dpdk``
* ``check-dpdk-offloads``: ``--datapath=userspace --dpdk --offload``

There are two kinds of datapath tests: pytest-based tests in
``tests/system``, and the Autotest testsuite for the selected datapath, e.g.,
``tests/system-kmod-testsuite`` for ``check-kernel``.  Every test of both
kinds runs in network and mount namespaces of its own, so the tests don't
interfere with each other or with the rest of the system, and can run in
parallel.  All the features documented under `Unit Tests`_ are available for
the datapath tests.  For example::

    $ make check-kernel PYTESTFLAGS=-n8

The kernel modules needed for the tests are loaded for the duration of the
test run and unloaded afterwards, unless they were already loaded.  AF_XDP and
DPDK tests get a CPU of their own for the busy polling PMD threads (and one
more for testpmd in DPDK tests), so the number of such tests running at the
same time is limited by the number of CPUs.  The first CPU is left for
everything else, unless it is the only one.  The tests may take several
minutes to complete.

If pytest is not available, the Autotest testsuite runs directly, and the
options documented under `Running Autotest directly`_ are available via
``TESTSUITEFLAGS``.

Userspace datapath
+++++++++++++++++++

To invoke the datapath testsuite with the userspace datapath, run::

    $ make check-system-userspace

The results of the Autotest tests are in
``tests/system-userspace-testsuite.<worker>.dir``, the results of the
pytest-based tests are in ``tests/pytest.dir``.

Userspace datapath with DPDK
++++++++++++++++++++++++++++

To test :doc:`/intro/install/dpdk` (i.e., the build was configured with
``--with-dpdk``, the DPDK is installed), run the testsuite and generate
a report by using the ``check-dpdk`` target::

    # make check-dpdk

or if you are not a root, but a sudo user::

    $ sudo -E make check-dpdk

To see a list of all the available tests, run::

    # make check-dpdk PYTESTFLAGS='--collect-only -q'

These tests support a `DPDK supported NIC`_. The tests operate on a wider set of
environments, for instance, when a virtual port is used.
Moreover you need to have root privileges to load the required modules and to bind
a PCI device to the DPDK-compatible driver.

.. _DPDK supported NIC: https://core.dpdk.org/supported/#nics

The phy test will skip if no suitable PCI device is found.
It is possible to select which PCI device is used for this test by setting the
DPDK_PCI_ADDR environment variable, which is especially useful when testing
with a mlx5 device::

    # DPDK_PCI_ADDR=0000:82:00.0 make check-dpdk

All tests are skipped if no hugepages are configured. User must look into the DPDK
manual to figure out how to `Configure hugepages`_.

.. _Configure hugepages: https://doc.dpdk.org/guides-25.11/linux_gsg/sys_reqs.html

All the features documented under `Datapath testing`_ are available for the
DPDK testsuite.  DPDK tests run in parallel as well, but every test needs about
800 MB of hugepage memory (more if it uses testpmd), so the number of DPDK
tests running at the same time is limited by the number of hugepages in the
system.  Tests that use a physical device run one by one.  This requires
pytest-xdist 2.5 or newer and the ``--dist=loadgroup`` mode, which is used
by default for DPDK tests.

Userspace datapath with DPDK offload
++++++++++++++++++++++++++++++++++++

To invoke the userspace datapath tests with DPDK and its rte_flow offload,
the same prerequisites apply as above. In addition, six Virtual Function (VF)
interfaces must be preconfigured on a single Physical Function (PF) that
supports rte_flow hardware offload.

This is an example on how to set this up for an NVIDIA blade on port
``ens2f0np0``::

    OVS_PF_PCI=$(basename $(readlink /sys/class/net/ens2f0np0/device))
    echo 0 > /sys/bus/pci/devices/$OVS_PF_PCI/sriov_numvfs
    devlink dev eswitch set pci/$OVS_PF_PCI mode switchdev
    echo 6 > /sys/bus/pci/devices/$OVS_PF_PCI/sriov_numvfs

This PF's PCI ID needs to be passed with the OVS_PF_PCI variable.
To invoke the DPDK offloads testsuite with the userspace datapath, run::

    make check-dpdk-offloads OVS_PF_PCI=0000:17:00.0

DPDK offload tests use the physical devices of the system, so they run one by
one, in the network namespace of the system.

.. note::
   This has only been tested on NVIDIA blades due to the limited availability
   of other blades that support rte_flow.

Kernel datapath
+++++++++++++++

Make targets are also provided for testing the Linux kernel module. Note that
these tests operate by inserting modules into the running Linux kernel, so if
the tests are able to trigger a bug in the OVS kernel module or in the upstream
kernel then the kernel may panic.

To run the testsuite against the kernel module which is currently installed on
your system, run::

    $ make check-kernel

All the features documented under `Datapath testing`_ are available for the
kernel datapath testsuite.

.. note::
  Many of the kernel tests are dependent on the utilities present in the
  iproute2 package, especially the 'ip' command.  If there are many
  otherwise unexplained errors it may be necessary to update the iproute2
  package utilities on the system.  It is beyond the scope of this
  documentation to explain all that is necessary to build and install
  an updated iproute2 utilities package.  The package is available from
  the Linux kernel organization open source git repositories.

  https://git.kernel.org/pub/scm/network/iproute2/iproute2.git

It is also possible to run `retis`_ capture along with the tests of
`check-kernel` and `check-offloads` by adding ``--retis`` to ``PYTESTFLAGS``,
or by setting the `OVS_TEST_WITH_RETIS` environment variable to 'yes'.  This
can be useful for debugging the test cases.  For example, the following
command can be used to run the test 167 under `retis`::

    $ make check-kernel PYTESTFLAGS="--retis --keep-artifacts -k 'test_autotest[0167'"

After the test is completed, the following data will be available in the test
directory:

* `retis.err` - standard error stream of the `retis collect`.
* `retis.log` - standard output of the `retis collect`, contains all captured
  events in the order they appeared.
* `retis.data` - raw events collected by retis, `retis sort` or other commands
  can be used on this file for further analysis.
* `retis.sorted` - text file containing the output of `retis sort` executed on
  the `retis.data`, for convenience.

Requires retis version 1.5 or newer and enabling support for
:doc:`/topics/usdt-probes`.

retis sees packets of all the network namespaces of the system.  When tests
run in parallel, the capture of every test is limited to the network devices
of its own network namespace, the one with the OVS ports.  Packets inside the
other network namespaces of the test, e.g., ``at_ns0``, and OVS specific
events are not captured then, since retis can't tell which of the running
ovs-vswitchd processes belongs to the test.  Run the tests one at a time to
capture them.

.. _retis: https://github.com/retis-org/retis

.. _testing-writing-tests:

Writing pytest-based Tests
~~~~~~~~~~~~~~~~~~~~~~~~~~

New datapath tests should be written in Python with pytest, in
``tests/system/test_*.py``, instead of being added to the Autotest
testsuites.  Existing Autotest tests are being migrated as well.  For
example, the following test checks connectivity between two network
namespaces connected to an OVS bridge::

    from tests.system.lib.ping import check_ping


    def test_ping_between_two_ports(ovs):
        ovs.ofctl("add-flow br0 actions=normal")

        ns0 = ovs.netns("at_ns0")
        ns1 = ovs.netns("at_ns1")
        ovs.add_veth("p0", ns0, "br0", "10.1.1.1/24")
        ovs.add_veth("p1", ns1, "br0", "10.1.1.2/24")

        for size in (None, 1600, 3200):
            check_ping("10.1.1.2", ns=ns0, size=size)

The ``ovs`` fixture starts OVS with the datapath under test and bridge
``br0``, the same way ``OVS_TRAFFIC_VSWITCHD_START`` does.  After a successful
test, it checks the daemon logs for unexpected warnings and errors and stops
the daemons, like ``OVS_TRAFFIC_VSWITCHD_STOP``.  Messages that a test
expects in the logs can be allowed with a marker::

    @pytest.mark.log_allow(r"could not open network device p2")
    def test_something(ovs):
        ...

Every test runs in network and mount namespaces of its own, and in its own
directory, which is the current directory of the test and the ``OVS_RUNDIR``
of the ``ovs`` instance, so ``ovs-vsctl``, ``ovs-ofctl`` and other utilities
work without additional arguments.  Everything a test creates is cleaned up
when it ends, there is no need for an equivalent of ``on_exit``.

The library for tests is in ``tests/lib`` (common infrastructure) and in
``tests/system/lib`` (datapath tests).  The main building blocks, and the
Autotest macros they replace, are:

* ``run(cmd, rc=0, stdout=False, stderr=False, ns=None)`` from
  ``tests.lib.cmd`` replaces ``AT_CHECK`` and ``NS_CHECK_EXEC``.  A bare
  ``run("cmd")`` expects a zero exit code and empty stdout and stderr.
  Expected output can be given as a list of lines or as a string,
  ``stdout=True`` accepts any output.  ``ovs.run()``, ``ovs.vsctl()``,
  ``ovs.ofctl()`` and ``ovs.appctl()`` do the same for a particular OVS
  instance.

* ``ovs.add_flows()`` replaces ``AT_DATA`` of a flows file followed by
  ``ovs-ofctl add-flows``.  The rules are given in ``ovs-ofctl`` syntax, one
  per line, and should not be wrapped, since wrapped rules are hard to read.
  Long lines are allowed with ``# noqa: E501`` after the closing quotes.
  Packets, e.g., flows for ``ofproto/trace``, are different, they are easier
  to read wrapped on protocol boundaries::

      flow = ("in_port=p1,"
              "dl_src=50:54:00:00:00:05,dl_dst=50:54:00:00:00:07,dl_type=0x0800,"
              "nw_src=192.168.0.1,nw_dst=192.168.0.2,nw_proto=1,nw_tos=0,"
              "nw_ttl=128,nw_frag=no,"
              "icmp_type=8,icmp_code=0")

  Rules look like this::

      ovs.add_flows("br0", """
          priority=1,action=drop
          priority=10,arp,action=normal
          priority=100,in_port=1,icmp,action=ct(commit),2
      """)

* ``wait_until()``, ``wait_while()`` and ``wait_until_equal()`` from
  ``tests.lib.cmd`` replace ``OVS_WAIT_UNTIL``, ``OVS_WAIT_WHILE`` and
  ``OVS_WAIT_UNTIL_EQUAL``.

* ``ovs.netns()``, ``ovs.add_veth()``, ``ovs.add_internal()``,
  ``ovs.add_veth_bond()``, ``ovs.add_bridge()`` and ``ovs.add_ovs_tunnel()``
  replace ``ADD_NAMESPACES``, ``ADD_VETH``, ``ADD_INT``, ``ADD_VETH_BOND``,
  ``ADD_BR`` and ``ADD_OVS_TUNNEL``.  ``add_vlan()`` and
  ``add_native_tunnel()`` methods of a namespace replace ``ADD_VLAN`` and
  ``ADD_NATIVE_TUNNEL``.

* ``ovs.start_background()`` replaces ``NETNS_DAEMONIZE``, ``start_l7()`` and
  ``http_get()`` from ``tests.system.lib.l7`` replace ``OVS_START_L7`` and
  ``OVS_GET_HTTP``.

* ``check_ping()`` from ``tests.system.lib.ping`` replaces ping with
  ``FORMAT_PING``.  ``dump_conntrack()`` from ``tests.system.lib.conntrack``
  returns parsed conntrack entries, so tests can check the fields that matter
  instead of using ``FORMAT_CT``.  ``dump_flows()`` and ``dump_dp_flows()``
  from ``tests.system.lib.flows`` return parsed OpenFlow and datapath flows.

* The ``requires`` and ``min_kernel`` markers replace the ``CHECK_*`` and
  ``OVS_CHECK_*`` macros, e.g., ``@pytest.mark.requires("conntrack_alg")``.
  See ``tests/system/lib/features.py`` for the list of features.  Features
  that ovs-vswitchd detects on startup can be checked with
  ``ovs.require_log()``.

* ``ovs.create_node()`` creates another OVS instance in a network namespace
  of its own, for tests with multiple nodes.

* Tests that are specific to one datapath configuration, like the tests that
  are only in one of the Autotest testsuites, use requirements like
  ``@pytest.mark.requires("dpdk")``, ``"afxdp"``, ``"tso"``,
  ``"tc_offload"``, ``"kernel_datapath"`` or ``"userspace_datapath"``.  DPDK
  tests can use the ``testpmd`` fixture to run dpdk-testpmd.

Unit tests, which don't need root privileges, are in ``tests/unit``.  Their
``ovs`` fixture starts OVS with the dummy datapath and bridge ``br0``, like
``OVS_VSWITCHD_START``, for example::

    def test_resubmit(ovs):
        ovs.add_of_ports("br0", 1, *range(10, 22))
        ...

Tests of OVSDB clustering are in ``tests/ovsdb_cluster``, see ``RaftCluster``
in ``tests/lib/ovsdb.py``.  The tests of the test infrastructure itself are
in ``tests/unit`` as well.

.. _testing-static-analysis:

Static Code Analysis
~~~~~~~~~~~~~~~~~~~~

Static Analysis is a method of debugging Software by examining code rather than
actually executing it. This can be done through 'scan-build' commandline
utility which internally uses clang (or) gcc to compile the code and also
invokes a static analyzer to do the code analysis. At the end of the build, the
reports are aggregated in to a common folder and can later be analyzed using
'scan-view'.

Open vSwitch includes a Makefile target to trigger static code analysis::

    $ ./boot.sh
    $ ./configure CC=clang  # clang
    # or
    $ ./configure CC=gcc CFLAGS="-std=gnu99"  # gcc
    $ make clang-analyze

You should invoke scan-view to view analysis results. The last line of output
from ``clang-analyze`` will list the command (containing results directory)
that you should invoke to view the results on a browser.

ViNePerf
--------

The ViNePerf project, formerly known as VswitchPerf or vsperf, aims to
develop a vSwitch test framework that can be used to validate the
suitability of different vSwitch implementations in a telco deployment
environment. More information can be found on the `Anuket project wiki`_.

.. _Anuket project wiki: https://wiki.anuket.io/display/HOME/ViNePERF
