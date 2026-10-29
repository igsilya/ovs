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

"""Requirements of system tests, the CHECK_* and OVS_CHECK_* macros.

Tests declare requirements with markers::

    @pytest.mark.requires("conntrack_alg", "vxlan")
    @pytest.mark.min_kernel(5, 19)
    def test_something(ovs):
        ...

and the test is skipped if a requirement is not met for the datapath
configuration under test or on the system.  The checks run inside the
isolated network namespace of the test, before OVS is started.  Features
that ovs-vswitchd probes on startup are checked with
``SystemNode.require_log()`` instead.
"""

import os
import platform
import re
import shutil
import subprocess
from collections import namedtuple

DatapathConfig = namedtuple("DatapathConfig",
                            ["datapath", "offload", "tso", "afxdp", "dpdk"])


def datapath_config(config):
    """Return the ``DatapathConfig`` selected on the command line."""
    return DatapathConfig(config.getoption("datapath"),
                          config.getoption("offload"),
                          config.getoption("tso"),
                          config.getoption("afxdp"),
                          config.getoption("dpdk"))


def isolated(config):
    """Whether tests of ``DatapathConfig`` ``config`` run in isolated
    network namespaces.

    DPDK offload tests use VFs of a physical NIC, which are in the root
    network namespace, so they run there, one at a time.
    """
    return not (config.dpdk and config.offload)


def _sh(cmd):
    """Run a shell command, return (exit code, combined output)."""
    r = subprocess.run(cmd, shell=True, stdout=subprocess.PIPE,
                       stderr=subprocess.STDOUT, universal_newlines=True)
    return r.returncode, r.stdout


def firewall_running():
    """Whether firewalld is running, like OVS_CHECK_FIREWALL."""
    if shutil.which("systemctl") is None:
        return False
    return "running" in _sh("systemctl status firewalld")[1]


def _link_type_help(link_type, pattern):
    # 'ip link add foo type <type> help' only prints the usage.
    return re.search(pattern, _sh("ip link add foo type %s help"
                                  % link_type)[1]) is not None


def _tunnel(link_type, pattern):
    def check(config):
        if not _link_type_help(link_type, pattern):
            return "%s is not supported by iproute2/kernel" % link_type
        if firewall_running():
            return "firewalld is running"
        return None
    return check


def _skip_on(reason, **conditions):
    """Skip if all ``conditions`` match the datapath configuration."""
    def check(config):
        if all(getattr(config, k) == v for k, v in conditions.items()):
            return reason
        return None
    return check


def _only(reason, **conditions):
    """Skip unless all ``conditions`` match the datapath configuration."""
    def check(config):
        if not all(getattr(config, k) == v for k, v in conditions.items()):
            return reason
        return None
    return check


def _system_only(check, reason):
    """Run ``check`` for the kernel datapath, skip for userspace."""
    def wrapper(config):
        if config.datapath != "system":
            return reason
        return check(config)
    return wrapper


def _kernel_config(option):
    path = "/boot/config-" + platform.release()
    try:
        with open(path) as f:
            return re.search(r"^%s=y$" % option, f.read(), re.M) is not None
    except OSError:
        return False


def _conntrack_sctp(config):
    if config.datapath == "system" and not os.path.exists(
            "/proc/sys/net/netfilter/nf_conntrack_sctp_timeout_closed"):
        return "SCTP conntrack is not supported by the kernel"
    return None


def _conntrack_timeout(config):
    if config.datapath != "system":
        return None
    if config.offload:
        return "TC offload doesn't support conntrack timeout policies"
    if not _kernel_config("CONFIG_NF_CONNTRACK_TIMEOUT"):
        return "kernel doesn't support conntrack timeout policies"
    return None


def _bareudp(config):
    rc, _ = _sh("ip link add dev ovs_bareudp0 type bareudp dstport 6635 "
                "ethertype mpls_uc")
    if rc != 0:
        return "bareudp is not supported by the kernel"
    _sh("ip link del dev ovs_bareudp0")
    return None


def _external_ct(config):
    if shutil.which("nft"):
        rc, _ = _sh("nft -c -f - <<EOF\n"
                    "table ip raw {\n"
                    "    chain output-ovs-testsuite {\n"
                    "        type filter hook output priority raw;\n"
                    "        ct state new\n"
                    "    }\n"
                    "}\nEOF")
        return None if rc == 0 else "nft can't track packets outside OVS"
    if shutil.which("iptables"):
        rc, _ = _sh("iptables -t raw -I OUTPUT 1 -j CT")
        if rc != 0:
            return "iptables can't track packets outside OVS"
        _sh("iptables -t raw -D OUTPUT 1")
        return None
    return "neither nft nor iptables is available"


def _srv6(config):
    if config.datapath == "system":
        return "the kernel datapath doesn't support SRv6"
    rc, _ = _sh("ip -6 route add fc00::1/96 encap seg6 mode encap dev lo")
    if rc != 0:
        return "SRv6 is not supported by the kernel"
    _sh("ip -6 route del fc00::1/96")
    if firewall_running():
        return "firewalld is running"
    return None


def _tool(name):
    def check(config):
        if shutil.which(name) is None:
            return "'%s' is not available" % name
        return None
    return check


def _dpdk_offload(config):
    if not (config.datapath == "userspace" and config.dpdk
            and config.offload):
        return "DPDK offload specific test"
    return dpdk_offload_check()


def dpdk_offload_check():
    """Like OVS_DPDK_OFFLOAD_PRE_CHECK: OVS_PF_PCI must be the PCI address of
    a physical function with at least 6 VFs that have representors.
    Returns a reason to skip or None.
    """
    from tests.system.lib.ovs import vf_netdev, vf_representor

    pf = os.environ.get("OVS_PF_PCI", "")
    if not re.match(r"^[0-9a-fA-F]{4}:[0-9a-fA-F]{2}:[0-9a-fA-F]{2}\.[0-7]$",
                    pf):
        return "OVS_PF_PCI is not set to the PCI address of a NIC"
    for i in range(6):
        if vf_netdev(pf, i) is None or vf_representor(pf, i) is None:
            return "%s needs at least 6 VFs with representors" % pf
    return None


def _xt(config):
    if shutil.which("iptables") is None and shutil.which("nft") is None:
        return "neither iptables nor nft is available"
    return None


def _not_github_actions(config):
    if os.environ.get("GITHUB_ACTIONS") == "true":
        return "doesn't work in GitHub Actions"
    return None


FEATURES = {
    # Tests of one datapath configuration, like the tests that are only in
    # one of the Autotest system testsuites.
    "kernel_datapath": _only("kernel datapath specific test",
                             datapath="system", offload=False),
    "tc_offload": _only("TC offload specific test",
                        datapath="system", offload=True),
    "userspace_datapath": _only("userspace datapath specific test",
                                datapath="userspace", tso=False,
                                afxdp=False, dpdk=False),
    "tso": _only("userspace TSO specific test", datapath="userspace",
                 tso=True),
    "afxdp": _only("AF_XDP specific test", datapath="userspace",
                   afxdp=True),
    "dpdk": _only("DPDK specific test", datapath="userspace", dpdk=True,
                  offload=False),
    "dpdk_offload": _dpdk_offload,
    # Conntrack (CHECK_CONNTRACK_*).
    "conntrack": lambda config: None,
    "conntrack_nat": lambda config: None,
    "conntrack_zeroip_snat": lambda config: None,
    "conntrack_alg": _skip_on("TC offload doesn't support ALGs",
                              datapath="system", offload=True),
    "conntrack_local_stack": _skip_on(
        "userspace conntrack can't track packets from the local stack",
        datapath="userspace"),
    "conntrack_frag_overlap": _skip_on(
        "the kernel doesn't check overlapping fragments", datapath="system"),
    "conntrack_snat_icmp_id": _skip_on(
        "unique ICMP ID allocation for SNAT is userspace only",
        datapath="system"),
    "conntrack_sctp": _conntrack_sctp,
    "conntrack_timeout": _conntrack_timeout,
    "conntrack_dump_expectations": _skip_on(
        "the kernel datapath can't dump expectations", datapath="system"),
    "ct_dpif_maxconns": _skip_on(
        "the kernel datapath doesn't support ct-set/get-maxconns",
        datapath="system"),
    "ct_dpif_nconns": _skip_on(
        "the kernel datapath doesn't support ct-get-nconns",
        datapath="system"),
    "l3l4_conntrack_reasm": _skip_on("kernel specific regression test",
                                     datapath="userspace"),
    "external_ct": _system_only(_external_ct,
                                "userspace doesn't support external CT"),
    # Offloads.
    "no_tc_offload": _skip_on("not supported with TC offload",
                              datapath="system", offload=True),
    "no_dpdk_offload": _skip_on("not supported with DPDK offload",
                                datapath="userspace", dpdk=True,
                                offload=True),
    # Tunnels and other devices (OVS_CHECK_*).
    "vxlan": _tunnel("vxlan", r"dstport"),
    "vxlan_udp6zerocsum": _tunnel("vxlan", r"udp6zerocsum"),
    "vxlan_gpe": _tunnel("vxlan", r"gpe"),
    "gre": _tunnel("gretap", r"gretap"),
    "gre_l3": _tunnel("gre", r"gre "),
    "erspan": _tunnel("erspan", r"erspan"),
    "geneve": _tunnel("geneve", r"geneve"),
    "geneve_udp6zerocsum": _tunnel("geneve", r"udp6zerocsum"),
    "bareudp": _system_only(_bareudp,
                            "userspace doesn't support bareudp"),
    "srv6": _srv6,
    "iproute_encap": lambda config: (
        None if "encap" in _sh("ip route help")[1]
        else "'ip route' doesn't support encap"),
    # Tools.
    "nc": _tool("nc"),
    "tc": _tool("tc"),
    "tcpdump": _tool("tcpdump"),
    "testpmd": _tool("dpdk-testpmd"),
    "xt": _xt,
    "not_github_actions": _not_github_actions,
}


def kernel_version():
    """Return the (major, minor) version of the running kernel."""
    m = re.match(r"(\d+)\.(\d+)", platform.release())
    return (int(m.group(1)), int(m.group(2))) if m else (0, 0)


def check_requirements(item, config):
    """Return a reason to skip test ``item``, or None.

    Args:
        item: pytest test item.
        config: ``DatapathConfig`` under test.
    """
    for marker in item.iter_markers("requires"):
        for name in marker.args:
            if name not in FEATURES:
                raise ValueError("Unknown requirement '%s'" % name)
            reason = FEATURES[name](config)
            if reason:
                return reason
    for marker in item.iter_markers("min_kernel"):
        if config.datapath != "system":
            return "kernel version requirement for the kernel datapath"
        if kernel_version() < tuple(marker.args):
            return "requires kernel %d.%d or newer" % tuple(marker.args)
    return None
