#!/bin/bash
#
# Kernel test script for OVS.
# Can be used standalone for local testing/bisection
# or from GitHub Actions CI.
#
# Prerequisites (must be done before running this script):
#   - Build OVS:
#       ./boot.sh && ./configure && make -j$(nproc)
#   - Create Python venv:
#       python3 -m venv venv
#       ./venv/bin/pip install -r python/test_requirements.txt
#   - Install system dependencies:
#       build-essential flex bison libelf-dev libssl-dev dwarves
#       qemu-system-x86 automake libtool (etc.)
#   - Install virtme-ng (v1.41+ recommended for zombie reaping):
#       pip install virtme-ng
#
# Usage:
#   .ci/kernel-test.sh --kernel-dir <path> --ovs-dir <path> [options]
#
# Options:
#   --kernel-dir <path>       Path to kernel tree (required)
#   --ovs-dir <path>          Path to OVS tree (required)
#   --build-timeout <sec>     Kernel build timeout (default: 1800)
#   --test-timeout <sec>      Test timeout (default: 5400)
#   --no-kasan                Disable KASAN (useful for faster bisection)
#   --verbose                 Verbose kernel build output
#   --memory <size>            VM memory size (default: 8G)
#   --qemu <path>             Path to custom QEMU binary
#   --disable-microvm         Disable microvm mode
#
# Exit codes (compatible with git bisect run):
#   0   - tests passed
#   1   - tests failed (bisect: bad commit)
#   125 - build failure or timeout (bisect: skip)
#
# Bisection example:
#   # One-time setup
#   cd ovs
#   ./boot.sh && ./configure && make -j$(nproc)
#   python3 -m venv venv
#   ./venv/bin/pip install -r python/test_requirements.txt
#
#   # Run bisection
#   cd ../kernel
#   git bisect start HEAD <last-known-good>
#   git bisect run ../ovs/.ci/kernel-test.sh \
#       --kernel-dir . --ovs-dir ../ovs --no-kasan

set -e

# Defaults
build_timeout=1800
test_timeout=5400
kasan=true
verbose=""
memory="8G"
qemu_arg=""
microvm_arg=""
kernel_dir=""
ovs_dir=""

# Parse arguments
while [ $# -gt 0 ]; do
    case "$1" in
        --kernel-dir)
            kernel_dir="$2"
            shift 2
            ;;
        --ovs-dir)
            ovs_dir="$2"
            shift 2
            ;;
        --build-timeout)
            build_timeout="$2"
            shift 2
            ;;
        --test-timeout)
            test_timeout="$2"
            shift 2
            ;;
        --no-kasan)
            kasan=false
            shift
            ;;
        --verbose)
            verbose="-v"
            shift
            ;;
        --memory)
            memory="$2"
            shift 2
            ;;
        --qemu)
            qemu_arg="--qemu $2"
            shift 2
            ;;
        --disable-microvm)
            microvm_arg="--disable-microvm"
            shift
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

# Validate required arguments
if [ -z "$kernel_dir" ] || [ -z "$ovs_dir" ]; then
    echo "Usage: $0 --kernel-dir <path> --ovs-dir <path> [options]"
    exit 1
fi

# Resolve to absolute paths
kernel_dir=$(readlink -f "$kernel_dir")
ovs_dir=$(readlink -f "$ovs_dir")

# Validate paths
if [ ! -d "$kernel_dir" ]; then
    echo "Error: kernel directory not found: $kernel_dir"
    exit 125
fi

if [ ! -d "$ovs_dir" ]; then
    echo "Error: OVS directory not found: $ovs_dir"
    exit 1
fi

if [ ! -f "$ovs_dir/Makefile" ]; then
    echo "Error: OVS does not appear to be built (no Makefile)."
    echo "Run: cd $ovs_dir && ./boot.sh && ./configure && make -j\$(nproc)"
    exit 1
fi

if [ ! -d "$ovs_dir/venv" ]; then
    echo "Error: Python venv not found in $ovs_dir/venv"
    echo "Run: cd $ovs_dir && python3 -m venv venv"
    echo "     ./venv/bin/pip install -r python/test_requirements.txt"
    exit 1
fi

if ! nc --version 2>&1 | grep -qi nmap; then
    echo "Error: nc is not Nmap ncat."
    echo "Found: $(nc --version 2>&1 | head -1)"
    exit 1
fi

echo "=== Kernel test configuration ==="
echo "Kernel directory: $kernel_dir"
echo "OVS directory:    $ovs_dir"
echo "Build timeout:    ${build_timeout}s"
echo "Test timeout:     ${test_timeout}s"
echo "KASAN:            $kasan"
echo "Memory:           $memory"
echo "QEMU:             ${qemu_arg:-system default}"
echo "Microvm:          ${microvm_arg:-enabled}"
echo "================================="

# --- Build kernel ---
cd "$kernel_dir"
rm -f .config .config.old

# Collect config fragments.
# Kernel selftest net config shard first (picks up new kernel dependencies),
# then OVS config last (wins on conflicts).
config_args=""
for shard in tools/testing/selftests/net/config; do
    if [ -f "$kernel_dir/$shard" ]; then
        config_args="$config_args --config $kernel_dir/$shard"
    fi
done
config_args="$config_args --config $ovs_dir/.ci/ovs.config"

if [ "$kasan" = false ]; then
    config_args="$config_args --configitem CONFIG_KASAN=n"
fi

echo ""
echo "=== Building kernel ==="
set -o pipefail
timeout --foreground "$build_timeout" \
    vng --build $verbose $config_args $qemu_arg 2>&1 \
    | tee "$kernel_dir/build.log"
build_res=${PIPESTATUS[0]}
set +o pipefail
if [ $build_res -ne 0 ]; then
    echo "Kernel build failed (exit code: $build_res)"
    exit 125
fi
echo "=== Kernel build complete ==="

# --- Build perf from kernel source ---
echo ""
echo "=== Building perf ==="
make -C "$kernel_dir/tools/perf" -j"$(nproc)" V=0
if [ $? -ne 0 ]; then
    echo "perf build failed"
    exit 125
fi
echo "=== perf build complete ==="

# --- Create VM test script ---
cat > "$kernel_dir/vm-test.sh" << 'VMEOF'
#!/bin/bash
set -e
set -o pipefail

kd="$1"
od="$2"

cleanup() {
    dmesg -l err,crit,alert,emerg -T \
        | tee "$kd/dmesg-errors.log"
    dmesg -T > "$kd/dmesg.log"
}
trap cleanup EXIT

echo "--- VM: kernel $(uname -r) ---"

# Fix dangling resolv.conf symlink.  The symlink target
# (e.g., /run/systemd/resolve/stub-resolv.conf) doesn't
# exist inside the VM because /run is a fresh tmpfs.
if [ -L /etc/resolv.conf ] && [ ! -e /etc/resolv.conf ]; then
    target=$(realpath -m /etc/resolv.conf 2>/dev/null)
    if [ -n "$target" ]; then
        mkdir -p "$(dirname "$target")"
        echo "nameserver 8.8.8.8" > "$target"
    fi
fi

export PATH="$kd/tools/perf:$PATH"
source "$od/venv/bin/activate"

echo "--- Running in-tree OVS selftests ---"
pushd tools/testing/selftests/net/openvswitch/
./openvswitch.sh -p < /dev/null 2>&1 | tee "$kd/selftest.log"
popd

echo "--- Running OVS check-kernel ---"
cd "$od"
make check-kernel RECHECK=yes
VMEOF
chmod +x "$kernel_dir/vm-test.sh"

# --- Run tests inside VM ---
echo ""
echo "=== Running tests in VM ==="

set +e
timeout --foreground "$test_timeout" \
    vng --run "$kernel_dir" \
        $qemu_arg $microvm_arg \
        --memory "$memory" --rw -- \
        "$kernel_dir/vm-test.sh" "$kernel_dir" "$ovs_dir"
res=$?
set -e

# --- Clean up kernel tree (--rw modifies it) ---
cd "$kernel_dir"
git reset --hard 2>/dev/null || true

# --- Handle results ---
if [ $res -eq 124 ]; then
    echo ""
    echo "=== TIMED OUT ==="
    # Kill any leftover qemu/virtme processes
    pkill -f virtme-ng 2>/dev/null || true
    exit 125
fi

if [ $res -ne 0 ]; then
    echo ""
    echo "=== Test failures ==="
    if [ -d "$ovs_dir/tests/system-kmod-testsuite.dir" ]; then
        grep -rE '^tcp |=======' \
            "$ovs_dir/tests/system-kmod-testsuite.dir/" \
            | cut -d':' -f 2 || true
    fi
fi

# --- Decode dmesg stack traces ---
errors="$kernel_dir/dmesg-errors.log"
decoded="$kernel_dir/dmesg-errors-decoded.log"
if [ -f "$kernel_dir/vmlinux" ] && \
   [ -f "$kernel_dir/scripts/decode_stacktrace.sh" ] && \
   [ -s "$errors" ]; then
    "$kernel_dir/scripts/decode_stacktrace.sh" \
        "$kernel_dir/vmlinux" \
        < "$errors" > "$decoded" 2>/dev/null
fi

# --- Check for OVS-related kernel errors ---
check="$decoded"
[ -f "$check" ] || check="$errors"
if [ $res -eq 0 ] && [ -f "$check" ] && \
   grep -qi 'openvswitch' "$check"; then
    echo ""
    echo "=== OVS kernel errors detected ==="
    grep -i 'openvswitch' "$check"
    res=1
fi

exit $res
