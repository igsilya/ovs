#!/bin/bash
set -ex

mkdir -p /var/cache/pacman/pkg/
pacman -S --noconfirm --needed automake autoconf libtool make patch

# Use an MSVC linker and a Windows version of Python.  On GitHub, there
# is no python in msys setup by default, so no need to move it there.
mv $(which link) $(which link)_copy
[ -z "$GITHUB_ACTIONS" ] && mv $(which python3) $(which python3)_copy

cd /c/pthreads4w-code && nmake all install
