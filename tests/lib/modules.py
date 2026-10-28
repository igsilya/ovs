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

"""Kernel module management for system tests.

Kernel modules are global, so system tests running in parallel can't load
and unload them for every test, as the Autotest system tests do.  Instead,
modules are loaded once for the whole test session.
"""

import logging
import os
import subprocess

log = logging.getLogger("ovs.test")


def is_loaded(name):
    """Whether kernel module ``name`` is loaded or built into the kernel."""
    return os.path.isdir("/sys/module/" + name.replace("-", "_"))


class KernelModules:
    """Loads kernel modules and unloads the ones it loaded.

    Modules that were already loaded are left alone, so a system with OVS
    running is not disturbed.
    """

    def __init__(self):
        self._loaded = []

    def load(self, name, required=True):
        """Load kernel module ``name`` if it is not loaded yet.

        Returns:
            True if the module is available.

        Raises:
            RuntimeError: if ``required`` and the module can't be loaded.
        """
        if is_loaded(name):
            return True
        result = subprocess.run(["modprobe", name], stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT,
                                universal_newlines=True)
        if result.returncode != 0:
            msg = "Failed to load kernel module %s: %s" % (
                name, result.stdout.strip())
            if required:
                raise RuntimeError(msg)
            log.info(msg)
            return False
        log.info("Loaded kernel module %s.", name)
        self._loaded.append(name)
        return True

    def unload_all(self):
        """Unload the modules loaded by ``load()``, in reverse order."""
        while self._loaded:
            name = self._loaded.pop()
            result = subprocess.run(["modprobe", "-r", name],
                                    stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT,
                                    universal_newlines=True)
            if result.returncode != 0:
                log.warning("Failed to unload kernel module %s: %s",
                            name, result.stdout.strip())
