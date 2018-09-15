#!/usr/bin/python2.7
#
# CDDL HEADER START
#
# The contents of this file are subject to the terms of the
# Common Development and Distribution License (the "License").
# You may not use this file except in compliance with the License.
#
# You can obtain a copy of the license at usr/src/OPENSOLARIS.LICENSE
# or http://www.opensolaris.org/os/licensing.
# See the License for the specific language governing permissions
# and limitations under the License.
#
# When distributing Covered Code, include this CDDL HEADER in each
# file and include the License file at usr/src/OPENSOLARIS.LICENSE.
# If applicable, add the following below this CDDL HEADER, with the
# fields enclosed by brackets "[]" replaced with your own identifying
# information: Portions Copyright [yyyy] [name of copyright owner]
#
# CDDL HEADER END
#
# Copyright (c) 2008, 2015, Oracle and/or its affiliates. All rights reserved.
# Copyright (c) 2012, OmniTI Computer Consulting, Inc. All rights reserved.
#

from __future__ import print_function
import errno
import fnmatch
import os
import platform
import six
import stat
import sys
import shutil
import re
import subprocess
import tarfile
import tempfile
import py_compile
import hashlib
import time

from distutils.errors import DistutilsError, DistutilsFileError
from distutils.core import setup
from distutils.cmd import Command
from distutils.command.install import install as _install
from distutils.command.install_data import install_data as _install_data
from distutils.command.install_lib import install_lib as _install_lib
from distutils.command.build import build as _build
from distutils.command.build_ext import build_ext as _build_ext
from distutils.command.build_py import build_py as _build_py
from distutils.command.bdist import bdist as _bdist
from distutils.command.clean import clean as _clean
from distutils.dist import Distribution
from distutils import log

from distutils.sysconfig import get_python_inc
import distutils.dep_util as dep_util
import distutils.dir_util as dir_util
import distutils.file_util as file_util
import distutils.util as util
import distutils.ccompiler
from distutils.unixccompiler import UnixCCompiler

osname = platform.uname()[0].lower()
ostype = arch = 'unknown'
if osname == 'sunos':
        arch = platform.processor()
        ostype = "posix"
elif osname == 'linux':
        arch = "linux_" + platform.machine()
        ostype = "posix"
elif osname == 'windows':
        arch = osname
        ostype = "windows"
elif osname == 'darwin':
        arch = osname
        ostype = "posix"
elif osname == 'aix':
        arch = "aix"
        ostype = "posix"

pwd = os.path.normpath(sys.path[0])

# the version of pylint that we must have in order to run the pylint checks.
req_pylint_version = "1.4.3"

#
# Unbuffer stdout and stderr.  This helps to ensure that subprocess output
# is properly interleaved with output from this program.
#
# Can't have unbuffered text I/O in Python 3. This doesn't quite matter.
if six.PY2:
        sys.stdout = os.fdopen(sys.stdout.fileno(), "w", 0)
        sys.stderr = os.fdopen(sys.stderr.fileno(), "w", 0)

dist_dir = os.path.normpath(os.path.join(pwd, os.pardir, "proto", "dist_" + arch))
build_dir = os.path.normpath(os.path.join(pwd, os.pardir, "proto", "build_" + arch))
if "ROOT" in os.environ and os.environ["ROOT"] != "":
        root_dir = os.environ["ROOT"]
else:
        root_dir = os.path.normpath(os.path.join(pwd, os.pardir, "proto", "root_" + arch))
pkgs_dir = os.path.normpath(os.path.join(pwd, os.pardir, "packages", arch))
extern_dir = os.path.normpath(os.path.join(pwd, "extern"))
cffi_dir = os.path.normpath(os.path.join(pwd, "cffi_src"))

# Extract Python minor version.
py_version = '.'.join(platform.python_version_tuple()[:2])
assert py_version in ('2.7', '3.5')
py_install_dir = 'usr/lib/python' + py_version + '/vendor-packages'

py64_executable = None
#Python 3 is always 64 bit and located in /usr/bin.
if float(py_version) < 3 and osname == 'sunos':
        if arch == 'sparc':
                py64_executable = '/usr/bin/sparcv9/python' + py_version
        elif arch == 'i386':
                py64_executable = '/usr/bin/amd64/python' + py_version

scripts_dir = 'usr/bin'
lib_dir = 'usr/lib'
svc_method_dir = 'lib/svc/method'
svc_share_dir = 'lib/svc/share'

man1_dir = 'usr/share/man/man1'
man1m_dir = 'usr/share/man/man1m'
man5_dir = 'usr/share/man/man5'
man1_ja_JP_dir = 'usr/share/man/ja_JP.UTF-8/man1'
man1m_ja_JP_dir = 'usr/share/man/ja_JP.UTF-8/man1m'
man5_ja_JP_dir = 'usr/share/man/ja_JP.UTF-8/man5'
man1_zh_CN_dir = 'usr/share/man/zh_CN.UTF-8/man1'
man1m_zh_CN_dir = 'usr/share/man/zh_CN.UTF-8/man1m'
man5_zh_CN_dir = 'usr/share/man/zh_CN.UTF-8/man5'

ignored_deps_dir = 'usr/share/pkg/ignored_deps'
rad_dir = 'usr/share/lib/pkg'
resource_dir = 'usr/share/lib/pkg'
transform_dir = 'usr/share/pkg/transforms'
smf_app_dir = 'lib/svc/manifest/application/pkg'
execattrd_dir = 'etc/security/exec_attr.d'
authattrd_dir = 'etc/security/auth_attr.d'
userattrd_dir = 'etc/user_attr.d'
sysrepo_dir = 'etc/pkg/sysrepo'
sysrepo_logs_dir = 'var/log/pkg/sysrepo'
sysrepo_cache_dir = 'var/cache/pkg/sysrepo'
autostart_dir = 'etc/xdg/autostart'
desktop_dir = 'usr/share/applications'
gconf_dir = 'etc/gconf/schemas'
depot_dir = 'etc/pkg/depot'
depot_conf_dir = 'etc/pkg/depot/conf.d'
depot_logs_dir = 'var/log/pkg/depot'
depot_cache_dir = 'var/cache/pkg/depot'
locale_dir = 'usr/share/locale'
mirror_logs_dir = 'var/log/pkg/mirror'
mirror_cache_dir = 'var/cache/pkg/mirror'


# A list of source, destination tuples of modules which should be hardlinked
# together if the os supports it and otherwise copied.
hardlink_modules = []

scripts_sunos = {
        scripts_dir: [
                ['client.py', 'pkg'],
                ['pkgdep.py', 'pkgdepend'],
                ['pkgrepo.py', 'pkgrepo'],
                ['util/publish/pkgdiff.py', 'pkgdiff'],
                ['util/publish/pkgfmt.py', 'pkgfmt'],
                ['util/publish/pkglint.py', 'pkglint'],
                ['util/publish/pkgmerge.py', 'pkgmerge'],
                ['util/publish/pkgmogrify.py', 'pkgmogrify'],
                ['util/publish/pkgsurf.py', 'pkgsurf'],
                ['publish.py', 'pkgsend'],
                ['pull.py', 'pkgrecv'],
                ['sign.py', 'pkgsign'],
                ],
        lib_dir: [
                ['depot.py', 'pkg.depotd'],
                ['sysrepo.py', 'pkg.sysrepo'],
                ['depot-config.py', "pkg.depot-config"]
                ],
        svc_method_dir: [
                ['svc/svc-pkg-depot', 'svc-pkg-depot'],
                ['svc/svc-pkg-mdns', 'svc-pkg-mdns'],
                ['svc/svc-pkg-mirror', 'svc-pkg-mirror'],
                ['svc/svc-pkg-repositories-setup',
                    'svc-pkg-repositories-setup'],
                ['svc/svc-pkg-server', 'svc-pkg-server'],
                ['svc/svc-pkg-sysrepo', 'svc-pkg-sysrepo'],
                ],
        svc_share_dir: [
                ['svc/pkg5_include.sh', 'pkg5_include.sh'],
                ],
        rad_dir: [
                ["rad-invoke.py", "rad-invoke"],
                ],
        }

scripts_windows = {
        scripts_dir: [
                ['client.py', 'client.py'],
                ['pkgrepo.py', 'pkgrepo.py'],
                ['publish.py', 'publish.py'],
                ['pull.py', 'pull.py'],
                ['scripts/pkg.bat', 'pkg.bat'],
                ['scripts/pkgsend.bat', 'pkgsend.bat'],
                ['scripts/pkgrecv.bat', 'pkgrecv.bat'],
                ],
        lib_dir: [
                ['depot.py', 'depot.py'],
                ['scripts/pkg.depotd.bat', 'pkg.depotd.bat'],
                ],
        }

scripts_other_unix = {
        scripts_dir: [
                ['client.py', 'client.py'],
                ['pkgdep.py', 'pkgdep'],
                ['util/publish/pkgdiff.py', 'pkgdiff'],
                ['util/publish/pkgfmt.py', 'pkgfmt'],
                ['util/publish/pkgmogrify.py', 'pkgmogrify'],
                ['pull.py', 'pull.py'],
                ['publish.py', 'publish.py'],
                ['scripts/pkg.sh', 'pkg'],
                ['scripts/pkgsend.sh', 'pkgsend'],
                ['scripts/pkgrecv.sh', 'pkgrecv'],
                ],
        lib_dir: [
                ['depot.py', 'depot.py'],
                ['scripts/pkg.depotd.sh', 'pkg.depotd'],
                ],
        rad_dir: [
                ["rad-invoke.py", "rad-invoke"],
                ],
        }

# indexed by 'osname'
scripts = {
        "sunos": scripts_sunos,
        "linux": scripts_other_unix,
        "windows": scripts_windows,
        "darwin": scripts_other_unix,
        "aix" : scripts_other_unix,
        "unknown": scripts_sunos,
        }

man1_files = [
        'man/pkg.1',
        'man/pkgdepend.1',
        'man/pkgdiff.1',
        'man/pkgfmt.1',
        'man/pkglint.1',
        'man/pkgmerge.1',
        'man/pkgmogrify.1',
        'man/pkgsend.1',
        'man/pkgsign.1',
        'man/pkgsurf.1',
        'man/pkgrecv.1',
        'man/pkgrepo.1',
        ]
man1m_files = [
        'man/pkg.depotd.1m',
        'man/pkg.depot-config.1m',
        'man/pkg.sysrepo.1m'
        ]
man5_files = [
        'man/pkg.5'
        ]

man1_ja_files = [
        'man/ja_JP/pkg.1',
        'man/ja_JP/pkgdepend.1',
        'man/ja_JP/pkgdiff.1',
        'man/ja_JP/pkgfmt.1',
        'man/ja_JP/pkglint.1',
        'man/ja_JP/pkgmerge.1',
        'man/ja_JP/pkgmogrify.1',
        'man/ja_JP/pkgsend.1',
        'man/ja_JP/pkgsign.1',
        'man/ja_JP/pkgrecv.1',
        'man/ja_JP/pkgrepo.1',
        ]
man1m_ja_files = [
        'man/ja_JP/pkg.depotd.1m',
        'man/ja_JP/pkg.sysrepo.1m'
        ]
man5_ja_files = [
        'man/ja_JP/pkg.5'
        ]

man1_zh_CN_files = [
        'man/zh_CN/pkg.1',
        'man/zh_CN/pkgdepend.1',
        'man/zh_CN/pkgdiff.1',
        'man/zh_CN/pkgfmt.1',
        'man/zh_CN/pkglint.1',
        'man/zh_CN/pkgmerge.1',
        'man/zh_CN/pkgmogrify.1',
        'man/zh_CN/pkgsend.1',
        'man/zh_CN/pkgsign.1',
        'man/zh_CN/pkgrecv.1',
        'man/zh_CN/pkgrepo.1',
        ]
man1m_zh_CN_files = [
        'man/zh_CN/pkg.depotd.1m',
        'man/zh_CN/pkg.sysrepo.1m'
        ]
man5_zh_CN_files = [
        'man/zh_CN/pkg.5'
        ]

packages = [
        'pkg',
        'pkg.actions',
        'pkg.bundle',
        'pkg.client',
        'pkg.client.linkedimage',
        'pkg.client.transport',
        'pkg.file_layout',
        'pkg.flavor',
        'pkg.lint',
        'pkg.portable',
        'pkg.publish',
        'pkg.server'
        ]

pylint_targets = [
        'pkg.altroot',
        'pkg.client.__init__',
        'pkg.client.api',
        'pkg.client.linkedimage',
        'pkg.client.pkg_solver',
        'pkg.client.pkgdefs',
        'pkg.client.pkgremote',
        'pkg.client.plandesc',
        'pkg.client.printengine',
        'pkg.client.progress',
        'pkg.misc',
        'pkg.pipeutils',
        ]

web_files = []
for entry in os.walk("web"):
        web_dir, dirs, files = entry
        if not files:
                continue
        web_files.append((os.path.join(resource_dir, web_dir), [
            os.path.join(web_dir, f) for f in files
            if f != "Makefile"
            ]))
        # install same set of files in "en/" in "__LOCALE__/ as well"
        # for localizable file package (regarding themes, install
        # theme "oracle.com" only)
        if os.path.basename(web_dir) == "en" and \
            os.path.dirname(web_dir) in ("web", "web/_themes/oracle.com"):
                web_files.append((os.path.join(resource_dir,
                    os.path.dirname(web_dir), "__LOCALE__"), [
                        os.path.join(web_dir, f) for f in files
                        if f != "Makefile"
                    ]))

smf_app_files = [
        'svc/pkg-depot.xml',
        'svc/pkg-mdns.xml',
        'svc/pkg-mirror.xml',
        'svc/pkg-repositories-setup.xml',
        'svc/pkg-server.xml',
        'svc/pkg-system-repository.xml',
        'svc/zoneproxy-client.xml',
        'svc/zoneproxyd.xml'
        ]
resource_files = [
        'util/opensolaris.org.sections',
        'util/pkglintrc',
        ]
transform_files = [
        'util/publish/transforms/developer',
        'util/publish/transforms/documentation',
        'util/publish/transforms/locale',
        'util/publish/transforms/smf-manifests'
        ]
sysrepo_files = [
        'util/apache2/sysrepo/sysrepo_p5p.py',
        'util/apache2/sysrepo/sysrepo_httpd.conf.mako',
        'util/apache2/sysrepo/sysrepo_publisher_response.mako',
        ]
sysrepo_log_stubs = [
        'util/apache2/sysrepo/logs/access_log',
        'util/apache2/sysrepo/logs/error_log',
        'util/apache2/sysrepo/logs/rewrite.log',
        ]
depot_files = [
        'util/apache2/depot/depot.conf.mako',
        'util/apache2/depot/depot_httpd.conf.mako',
        'util/apache2/depot/depot_index.py',
        'util/apache2/depot/depot_httpd_ssl_protocol.conf',
        ]
depot_log_stubs = [
        'util/apache2/depot/logs/access_log',
        'util/apache2/depot/logs/error_log',
        'util/apache2/depot/logs/rewrite.log',
        ]
ignored_deps_files = []

# The apache-based depot includes an shtml file we add to the resource dir
web_files.append((os.path.join(resource_dir, "web"),
    ["util/apache2/depot/repos.shtml"]))
execattrd_files = [
        'util/misc/exec_attr.d/package:pkg',
]
authattrd_files = ['util/misc/auth_attr.d/package:pkg']
userattrd_files = ['util/misc/user_attr.d/package:pkg']
pkg_locales = \
    'ar ca cs de es fr he hu id it ja ko nl pl pt_BR ru sk sv zh_CN zh_HK zh_TW'.split()

sysattr_srcs = [
        'cffi_src/_sysattr.c'
        ]
syscallat_srcs = [
        'cffi_src/_syscallat.c'
        ]
pspawn_srcs = [
        'cffi_src/_pspawn.c'
        ]
elf_srcs = [
        'modules/elf.c',
        'modules/elfextract.c',
        'modules/liblist.c',
        ]
arch_srcs = [
        'cffi_src/_arch.c'
        ]
_actions_srcs = [
        'modules/actions/_actions.c'
        ]
_actcomm_srcs = [
        'modules/actions/_common.c'
        ]
_varcet_srcs = [
        'modules/_varcet.c'
        ]
solver_srcs = [
        'modules/solver/solver.c',
        'modules/solver/py_solver.c'
        ]
solver_link_args = ["-lm", "-lc"]
if osname == 'sunos':
        solver_link_args = ["-ztext"] + solver_link_args

# Runs lint on the extension module source code
class pylint_func(Command):
        description = "Runs pylint tools over IPS python source code"
        user_options = []

        def initialize_options(self):
                pass

        def finalize_options(self):
                pass

        # Make string shell-friendly
        @staticmethod
        def escape(astring):
                return astring.replace(' ', '\\ ')

        def run(self, quiet=False, py3k=False):

                def supported_pylint_ver(version):
                        """Compare the installed version against the version
                        we require to build with, returning False if the version
                        is too old. It's tempting to use pkg.version.Version
                        here, but since that's a build artifact, we'll do it
                        the long way."""
                        inst_pylint_ver = version.split(".")
                        req_pylint_ver = req_pylint_version.split(".")

                        # if the lists are of different lengths, we just
                        # compare with the precision we have.
                        vers_comp = zip(inst_pylint_ver, req_pylint_ver)
                        for inst, req in vers_comp:
                                try:
                                        if int(inst) < int(req):
                                                return False
                                        elif int(inst) > int(req):
                                                return True
                                except ValueError:
                                        # if we somehow get non-numeric version
                                        # components, we ignore them.
                                        continue
                        return True

                # it's fine to default to the required version - the build will
                # break if the installed version is incompatible and $PYLINT_VER
                # didn't get set, somehow.
                pylint_ver_str = os.environ.get("PYLINT_VER",
                    req_pylint_version)
                if pylint_ver_str == "":
                        pylint_ver_str = req_pylint_version

                if os.environ.get("PKG_SKIP_PYLINT"):
                        log.warn("WARNING: skipping pylint checks: "
                            "$PKG_SKIP_PYLINT was set")
                        return
                elif not pylint_ver_str or \
                    not supported_pylint_ver(pylint_ver_str):
                        log.warn("WARNING: skipping pylint checks: the "
                            "installed version {0} is older than version {1}".format(
                            pylint_ver_str, req_pylint_version))
                        return

                proto = os.path.join(root_dir, py_install_dir)
                sys.path.insert(0, proto)


                # Insert tests directory onto sys.path so any custom checkers
                # can be found.
                sys.path.insert(0, os.path.join(pwd, 'tests'))
                # assumes pylint is accessible on the sys.path
                from pylint import lint

                #
                # Unfortunately, pylint seems pretty fragile and will crash if
                # we try to run it over all the current pkg source.  Hence for
                # now we only run it over a subset of the source.  As source
                # files are made pylint clean they should be added to the
                # pylint_targets list.
                #
                if not py3k:
                        args = []
                        if quiet:
                                args += ['--reports=no']
                        args += ['--rcfile={0}'.format(os.path.join(
                            pwd, 'tests', 'pylintrc'))]
                        args += pylint_targets
                        lint.Run(args)
                else:
                        #
                        # In Python 3 porting mode, all checkers will be
                        # disabled and only messages emitted by the porting
                        # checker will be displayed. Therefore we need to run
                        # this checker separately.
                        #
                        args = []
                        if quiet:
                                args += ['--reports=no']
                        args += ['--rcfile={0}'.format(os.path.join(
                            pwd, 'tests', 'pylintrc_py3k'))]
                        # We check all Python files in the gate.
                        for root, dirs, files in os.walk(pwd):
                                for f in files:
                                    if f.endswith(".py"):
                                            args += [os.path.join(root, f)]
                        lint.Run(args)


class pylint_func_quiet(pylint_func):

        def run(self, quiet=False):
                pylint_func.run(self, quiet=True)

class pylint_func_py3k(pylint_func):
        def run(self, quiet=False, py3k=False):
                pylint_func.run(self, py3k=True)

include_dirs = [ 'modules' ]
lint_flags = [ '-u', '-axms', '-erroff=E_NAME_DEF_NOT_USED2' ]

# Runs lint on the extension module source code
class clint_func(Command):
        description = "Runs lint tools over IPS C extension source code"
        user_options = []

        def initialize_options(self):
                pass

        def finalize_options(self):
                pass

        # Make string shell-friendly
        @staticmethod
        def escape(astring):
                return astring.replace(' ', '\\ ')

        def run(self):
                if "LINT" in os.environ and os.environ["LINT"] != "":
                        lint = [os.environ["LINT"]]
                else:
                        lint = ['lint']
                if osname == 'sunos' or osname == "linux":
                        archcmd = lint + lint_flags + \
                            ['-D_FILE_OFFSET_BITS=64'] + \
                            ["{0}{1}".format("-I", k) for k in include_dirs] + \
                            ['-I' + self.escape(get_python_inc())] + \
                            arch_srcs
                        elfcmd = lint + lint_flags + \
                            ["{0}{1}".format("-I", k) for k in include_dirs] + \
                            ['-I' + self.escape(get_python_inc())] + \
                            ["{0}{1}".format("-l", k) for k in elf_libraries] + \
                            elf_srcs
                        _actionscmd = lint + lint_flags + \
                            ["{0}{1}".format("-I", k) for k in include_dirs] + \
                            ['-I' + self.escape(get_python_inc())] + \
                            _actions_srcs
                        _actcommcmd = lint + lint_flags + \
                            ["{0}{1}".format("-I", k) for k in include_dirs] + \
                            ['-I' + self.escape(get_python_inc())] + \
                            _actcomm_srcs
                        _varcetcmd = lint + lint_flags + \
                            ["{0}{1}".format("-I", k) for k in include_dirs] + \
                            ['-I' + self.escape(get_python_inc())] + \
                            _varcet_srcs
                        pspawncmd = lint + lint_flags + \
                            ['-D_FILE_OFFSET_BITS=64'] + \
                            ["{0}{1}".format("-I", k) for k in include_dirs] + \
                            ['-I' + self.escape(get_python_inc())] + \
                            pspawn_srcs
                        syscallatcmd = lint + lint_flags + \
                            ['-D_FILE_OFFSET_BITS=64'] + \
                            ["{0}{1}".format("-I", k) for k in include_dirs] + \
                            ['-I' + self.escape(get_python_inc())] + \
                            syscallat_srcs
                        sysattrcmd = lint + lint_flags + \
                            ['-D_FILE_OFFSET_BITS=64'] + \
                            ["{0}{1}".format("-I", k) for k in include_dirs] + \
                            ['-I' + self.escape(get_python_inc())] + \
                            ["{0}{1}".format("-l", k) for k in sysattr_libraries] + \
                            sysattr_srcs

                        print(" ".join(archcmd))
                        os.system(" ".join(archcmd))
                        print(" ".join(elfcmd))
                        os.system(" ".join(elfcmd))
                        print(" ".join(_actionscmd))
                        os.system(" ".join(_actionscmd))
                        print(" ".join(_actcommcmd))
                        os.system(" ".join(_actcommcmd))
                        print(" ".join(_varcetcmd))
                        os.system(" ".join(_varcetcmd))
                        print(" ".join(pspawncmd))
                        os.system(" ".join(pspawncmd))
                        print(" ".join(syscallatcmd))
                        os.system(" ".join(syscallatcmd))
                        print(" ".join(sysattrcmd))
                        os.system(" ".join(sysattrcmd))


# Runs both C and Python lint
class lint_func(Command):
        description = "Runs C and Python lint checkers"
        user_options = []

        def initialize_options(self):
                pass

        def finalize_options(self):
                pass

        # Make string shell-friendly
        @staticmethod
        def escape(astring):
                return astring.replace(' ', '\\ ')

        def run(self):
                clint_func(Distribution()).run()
                pylint_func(Distribution()).run()

class install_func(_install):
        def initialize_options(self):
                _install.initialize_options(self)

                # PRIVATE_BUILD set in the environment tells us to put the build
                # directory into the .pyc files, rather than the final
                # installation directory.
                private_build = os.getenv("PRIVATE_BUILD", None)

                if private_build is None:
                        self.install_lib = py_install_dir
                        self.install_data = os.path.sep
                        self.root = root_dir
                else:
                        self.install_lib = os.path.join(root_dir, py_install_dir)
                        self.install_data = root_dir

                # This is used when installing scripts, below, but it isn't a
                # standard distutils variable.
                self.root_dir = root_dir

        def run(self):
                """At the end of the install function, we need to rename some
                files because distutils provides no way to rename files as they
                are placed in their install locations.
                """

                _install.run(self)
                for o_src, o_dest in hardlink_modules:
                        for e in [".py", ".pyc"]:
                                src = util.change_root(self.root_dir, o_src + e)
                                dest = util.change_root(
                                    self.root_dir, o_dest + e)
                                if ostype == "posix":
                                        if os.path.exists(dest) and \
                                            os.stat(src)[stat.ST_INO] != \
                                            os.stat(dest)[stat.ST_INO]:
                                                os.remove(dest)
                                        file_util.copy_file(src, dest,
                                            link="hard", update=1)
                                else:
                                        file_util.copy_file(src, dest, update=1)

                # XXX Uncomment it when we need to deliver python 3.x version
                # of modules.
                # Don't install the scripts for python 3.5
                if py_version == '3.5':
                        return
                for d, files in six.iteritems(scripts[osname]):
                        for (srcname, dstname) in files:
                                dst_dir = util.change_root(self.root_dir, d)
                                dst_path = util.change_root(self.root_dir,
                                       os.path.join(d, dstname))
                                dir_util.mkpath(dst_dir, verbose=True)
                                file_util.copy_file(srcname, dst_path,
                                    update=True)
                                # make scripts executable
                                os.chmod(dst_path,
                                    os.stat(dst_path).st_mode
                                    | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

class install_lib_func(_install_lib):
        """Remove the target files prior to the standard install_lib procedure
        if the build_py module has determined that they've actually changed.
        This may be needed when a module's timestamp goes backwards in time, if
        a working-directory change is reverted, or an older changeset is checked
        out.
        """

        def install(self):
                build_py = self.get_finalized_command("build_py")
                prefix_len = len(self.build_dir) + 1
                for p in build_py.copied:
                        id_p = os.path.join(self.install_dir, p[prefix_len:])
                        rm_f(id_p)
                        if self.compile:
                                rm_f(id_p + "c")
                        if self.optimize > 0:
                                rm_f(id_p + "o")
                return _install_lib.install(self)

class install_data_func(_install_data):
        """Enhance the standard install_data subcommand to take not only a list
        of filenames, but a list of source and destination filename tuples, for
        the cases where a filename needs to be renamed between the two
        locations."""

        def run(self):
                self.mkpath(self.install_dir)
                for f in self.data_files:
                        dir, files = f
                        dir = util.convert_path(dir)
                        if not os.path.isabs(dir):
                                dir = os.path.join(self.install_dir, dir)
                        elif self.root:
                                dir = change_root(self.root, dir)
                        self.mkpath(dir)

                        if not files:
                                self.outfiles.append(dir)
                        else:
                                for file in files:
                                        if isinstance(file, six.string_types):
                                                infile = file
                                                outfile = os.path.join(dir,
                                                    os.path.basename(file))
                                        else:
                                                infile, outfile = file
                                        infile = util.convert_path(infile)
                                        outfile = util.convert_path(outfile)
                                        if os.path.sep not in outfile:
                                                outfile = os.path.join(dir,
                                                    outfile)
                                        self.copy_file(infile, outfile)
                                        self.outfiles.append(outfile)

def run_cmd(args, swdir, updenv=None, ignerr=False, savestderr=None):
                if updenv:
                        # use temp environment modified with the given dict
                        env = os.environ.copy()
                        env.update(updenv)
                else:
                        # just use environment of this (parent) process as is
                        env = os.environ
                if ignerr:
                        # send stderr to devnull
                        stderr = open(os.devnull)
                elif savestderr:
                        stderr = savestderr
                else:
                        # just use stderr of this (parent) process
                        stderr = None
                ret = subprocess.Popen(args, cwd=swdir, env=env,
                    stderr=stderr).wait()
                if ret != 0:
                        if stderr:
                            stderr.close()
                        print("install failed and returned {0:d}.".format(ret),
                            file=sys.stderr)
                        print("Command was: {0}".format(" ".join(args)),
                            file=sys.stderr)

                        sys.exit(1)
                if stderr:
                        stderr.close()

def _copy_file_contents(src, dst, buffer_size=16*1024):
        """A clone of distutils.file_util._copy_file_contents() that modifies
        python files as they are installed."""

        # Look for shebang line to replace with arch-specific Python executable.
        shebang_re = re.compile('^#!.*python[0-9]\.[0-9]')
        first_buf = True

        with open(src, "rb") as sfp:
                try:
                        os.unlink(dst)
                except EnvironmentError as e:
                        if e.errno != errno.ENOENT:
                                raise DistutilsFileError("could not delete "
                                    "'{0}': {1}".format(dst, e))

                with open(dst, "wb") as dfp:
                        while True:
                                buf = sfp.read(buffer_size)
                                if not buf:
                                        break
                                if src.endswith(".py"):
                                        if not first_buf or not py64_executable:
                                                dfp.write(buf)
                                                continue

                                        fl = buf[:buf.find(os.linesep) + 1]
                                        sb_match = shebang_re.search(fl)
                                        if sb_match:
                                                buf = shebang_re.sub(
                                                    "#!" + py64_executable,
                                                    buf)
                                dfp.write(buf)
                                first_buf = False

# Make file_util use our version of _copy_file_contents
file_util._copy_file_contents = _copy_file_contents

def intltool_update_maintain():
        """Check if scope of localization looks up-to-date or possibly not,
        by comparing file set described in po/POTFILES.{in,skip} and
        actual source files (e.g. .py) detected.
        """
        rm_f("po/missing")
        rm_f("po/notexist")

        args = [
            "/usr/bin/intltool-update", "--maintain"
        ]
        print(" ".join(args))
        podir = os.path.join(os.getcwd(), "po")
        run_cmd(args, podir, updenv={"LC_ALL": "C"}, ignerr=True)

        if os.path.exists("po/missing"):
            print("New file(s) with translatable strings detected:",
                file=sys.stderr)
            missing = open("po/missing", "r")
            print("--------", file=sys.stderr)
            for fn in missing:
                print("{0}".format(fn.strip()), file=sys.stderr)
            print("--------", file=sys.stderr)
            missing.close()
            print("""\
Please evaluate whether any of the above file(s) needs localization.
If so, please add its name to po/POTFILES.in.  If not (e.g., it's not
delivered), please add its name to po/POTFILES.skip.
Please be sure to maintain alphabetical ordering in both files.""", file=sys.stderr)
            sys.exit(1)

        if os.path.exists("po/notexist"):
            print("""\
The following files are listed in po/POTFILES.in, but no longer exist
in the workspace:""", file=sys.stderr)
            notexist = open("po/notexist", "r")
            print("--------", file=sys.stderr)
            for fn in notexist:
                print("{0}".format(fn.strip()), file=sys.stderr)
            print("--------", file=sys.stderr)

            notexist.close()
            print("Please remove the file names from po/POTFILES.in",
                file=sys.stderr)
            sys.exit(1)

def intltool_update_pot():
        """Generate pkg.pot by extracting localizable strings from source
        files (e.g. .py)
        """
        rm_f("po/pkg.pot")

        args = [
            "/usr/bin/intltool-update", "--pot"
        ]
        print(" ".join(args))
        podir = os.path.join(os.getcwd(), "po")
        run_cmd(args, podir,
            updenv={"LC_ALL": "C", "XGETTEXT": "/usr/gnu/bin/xgettext"})

        if not os.path.exists("po/pkg.pot"):
            print("Failed in generating pkg.pot.", file=sys.stderr)
            sys.exit(1)

def intltool_merge(src, dst):
        if not dep_util.newer(src, dst):
                return

        args = [
            "/usr/bin/intltool-merge", "-d", "-u",
            "-c", "po/.intltool-merge-cache", "po", src, dst
        ]
        print(" ".join(args))
        run_cmd(args, os.getcwd(), updenv={"LC_ALL": "C"})

def i18n_check():
        """Checks for common i18n messaging bugs in the source."""

        src_files = []
        # A list of the i18n errors we check for in the code
        common_i18n_errors = [
            # This checks that messages with multiple parameters are always
            # written using "{name}" format, rather than just "{0}"
            "format string with unnamed arguments cannot be properly localized"
        ]

        for line in open("po/POTFILES.in", "r").readlines():
                if line.startswith("["):
                        continue
                if line.startswith("#"):
                        continue
                src_files.append(line.rstrip())

        args = [
            "/usr/gnu/bin/xgettext", "--from-code=UTF-8", "-o", "/dev/null"]
        args += src_files

        xgettext_output_path = tempfile.mkstemp()[1]
        xgettext_output = open(xgettext_output_path, "w")
        run_cmd(args, os.getcwd(), updenv={"LC_ALL": "C"},
            savestderr=xgettext_output)

        found_errs = False
        i18n_errs = open("po/i18n_errs.txt", "w")
        for line in open(xgettext_output_path, "r").readlines():
                for err in common_i18n_errors:
                        if err in line:
                                i18n_errs.write(line)
                                found_errs = True
        i18n_errs.close()
        if found_errs:
                print("""\
The following i18n errors were detected and should be corrected:
(this list is saved in po/i18n_errs.txt)
""", file=sys.stderr)
                for line in open("po/i18n_errs.txt", "r"):
                        print(line.rstrip(), file=sys.stderr)
                sys.exit(1)
        os.remove(xgettext_output_path)

def msgfmt(src, dst):
        if not dep_util.newer(src, dst):
                return

        args = ["/usr/bin/msgfmt", "-o", dst, src]
        print(" ".join(args))
        run_cmd(args, os.getcwd())

def localizablexml(src, dst):
        """create XML help for localization, where French part of legalnotice
        is stripped off
        """
        if not dep_util.newer(src, dst):
                return

        fsrc = open(src, "r")
        fdst = open(dst, "w")

        # indicates currently in French part of legalnotice
        in_fr = False

        for l in fsrc:
            if in_fr: # in French part
                if l.startswith('</legalnotice>'):
                    # reached end of legalnotice
                    print(l, file=fdst)
                    in_fr = False
            elif l.startswith('<para lang="fr"/>') or \
                    l.startswith('<para lang="fr"></para>'):
                in_fr = True
            else:
                # not in French part
                print(l, file=fdst)

        fsrc.close()
        fdst.close()

def xml2po_gen(src, dst):
        """Input is English XML file. Output is pkg_help.pot, message
        source for next translation update.
        """
        if not dep_util.newer(src, dst):
                return

        args = ["/usr/bin/xml2po", "-o", dst, src]
        print(" ".join(args))
        run_cmd(args, os.getcwd())

def xml2po_merge(src, dst, mofile):
        """Input is English XML file and <lang>.po file (which contains
        translations). Output is translated XML file.
        """
        msgfmt(mofile[:-3] + ".po", mofile)

        monewer = dep_util.newer(mofile, dst)
        srcnewer = dep_util.newer(src, dst)

        if not srcnewer and not monewer:
                return

        args = ["/usr/bin/xml2po", "-t", mofile, "-o", dst, src]
        print(" ".join(args))
        run_cmd(args, os.getcwd())

class installfile(Command):
        user_options = [
            ("file=", "f", "source file to copy"),
            ("dest=", "d", "destination directory"),
            ("mode=", "m", "file mode"),
        ]

        description = "Modifying file copy"

        def initialize_options(self):
                self.file = None
                self.dest = None
                self.mode = None

        def finalize_options(self):
                if self.mode is None:
                        self.mode = 0o644
                elif isinstance(self.mode, six.string_types):
                        try:
                                self.mode = int(self.mode, 8)
                        except ValueError:
                                self.mode = 0o644

        def run(self):
                dest_file = os.path.join(self.dest, os.path.basename(self.file))
                ret = self.copy_file(self.file, dest_file)

                os.chmod(dest_file, self.mode)
                os.utime(dest_file, None)

                return ret

class build_func(_build):
        sub_commands = _build.sub_commands + [('build_data', None)]

        def initialize_options(self):
                _build.initialize_options(self)
                self.build_base = build_dir

def get_git_version():
        try:
                p = subprocess.Popen(
                    ['git', 'show', '--format=%h', '--no-patch'],
                    stdout = subprocess.PIPE)
                return p.communicate()[0].strip()
        except OSError:
                print("ERROR: unable to obtain git commit hash",
                    file=sys.stderr)
                return "unknown"

def syntax_check(filename):
        """ Run python's compiler over the file, and discard the results.
            Arrange to generate an exception if the file does not compile.
            This is needed because distutil's own use of pycompile (in the
            distutils.utils module) is broken, and doesn't stop on error. """
        try:
                tmpfd, tmp_file = tempfile.mkstemp()
                py_compile.compile(filename, tmp_file, doraise=True)
        except py_compile.PyCompileError as e:
                res = ""
                for err in e.exc_value:
                        if isinstance(err, six.string_types):
                                res += err + "\n"
                                continue

                        # Assume it's a tuple of (filename, lineno, col, code)
                        fname, line, col, code = err
                        res += "line {0:d}, column {1}, in {2}:\n{3}".format(
                            line, col or "unknown", fname, code)

                raise DistutilsError(res)

# On Solaris, ld inserts the full argument to the -o option into the symbol
# table.  This means that the resulting object will be different depending on
# the path at which the workspace lives, and not just on the interesting content
# of the object.
#
# In order to work around that bug (7076871), we create a new compiler class
# that looks at the argument indicating the output file, chdirs to its
# directory, and runs the real link with the output file set to just the base
# name of the file.
#
# Unfortunately, distutils isn't too customizable in this regard, so we have to
# twiddle with a couple of the names in the distutils.ccompiler namespace: we
# have to add a new entry to the compiler_class dict, and we have to override
# the new_compiler() function to point to our own.  Luckily, our copy of
# new_compiler() gets to be very simple, since we always know what we want to
# return.
class MyUnixCCompiler(UnixCCompiler):

        def link(self, *args, **kwargs):

                output_filename = args[2]
                output_dir = kwargs.get('output_dir')
                cwd = os.getcwd()

                assert(not output_dir)
                output_dir = os.path.join(cwd, os.path.dirname(output_filename))
                output_filename = os.path.basename(output_filename)
                nargs = args[:2] + (output_filename,) + args[3:]
                if not os.path.exists(output_dir):
                        os.mkdir(output_dir, 0o755)
                os.chdir(output_dir)

                UnixCCompiler.link(self, *nargs, **kwargs)

                os.chdir(cwd)

distutils.ccompiler.compiler_class['myunix'] = (
    'unixccompiler', 'MyUnixCCompiler',
    'standard Unix-style compiler with a link stage modified for Solaris'
)

def my_new_compiler(plat=None, compiler=None, verbose=0, dry_run=0, force=0):
        return MyUnixCCompiler(None, dry_run, force)

if osname == 'sunos':
        distutils.ccompiler.new_compiler = my_new_compiler

class build_ext_func(_build_ext):

        def initialize_options(self):
                _build_ext.initialize_options(self)
                self.build64 = False

                if osname == 'sunos':
                        self.compiler = 'myunix'

        def build_extension(self, ext):
                # Build 32-bit
                self.build_temp = str(self.build_temp)
                _build_ext.build_extension(self, ext)
                if not ext.build_64:
                        return

                # Set up for 64-bit
                old_build_temp = self.build_temp
                d, f = os.path.split(self.build_temp)

                # store our 64-bit extensions elsewhere
                self.build_temp = str(d + "/temp64.{0}".format(
                    os.path.basename(self.build_temp).replace("temp.", "")))
                ext.extra_compile_args += ["-m64"]
                ext.extra_link_args += ["-m64"]
                self.build64 = True

                # Build 64-bit
                _build_ext.build_extension(self, ext)

                # Reset to 32-bit
                self.build_temp = str(old_build_temp)
                ext.extra_compile_args.remove("-m64")
                ext.extra_link_args.remove("-m64")
                self.build64 = False

        def get_ext_fullpath(self, ext_name):
                path = _build_ext.get_ext_fullpath(self, ext_name)
                if not self.build64:
                        return path

                dpath, fpath = os.path.split(path)
                if py_version < '3.0':
                        return os.path.join(dpath, "64", fpath)
                return os.path.join(dpath, fpath)


class build_py_func(_build_py):

        def __init__(self, dist):
                ret = _build_py.__init__(self, dist)

                self.copied = []

                # Gather the timestamps of the .py files in the gate, so we can
                # force the mtimes of the built and delivered copies to be
                # consistent across builds, causing their corresponding .pyc
                # files to be unchanged unless the .py file content changed.

                self.timestamps = {}

                pydates = "pydates"

                if os.path.isdir(os.path.join(pwd, "../.git")):
                    pydates = "pydates.git"

                p = subprocess.Popen(
                    os.path.join(pwd, pydates),
                    stdout=subprocess.PIPE)

                for line in p.stdout:
                        stamp, path = line.split()
                        stamp = float(stamp)
                        self.timestamps[path] = stamp

                if p.wait() != 0:
                        print("ERROR: unable to gather .py timestamps",
                            file=sys.stderr)
                        sys.exit(1)

                # Before building extensions, we need to generate .c files
                # for the C extension modules by running the CFFI build
                # script files.
                for path in os.listdir(cffi_dir):
                        if not path.startswith("build_"):
                                continue
                        path = os.path.join(cffi_dir, path)
                        # make scripts executable
                        os.chmod(path,
                            os.stat(path).st_mode
                            | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

                        # run the scripts
                        p = subprocess.Popen(
                            [sys.executable, path])

                return ret

        # override the build_module method to do VERSION substitution on
        # pkg/__init__.py
        def build_module (self, module, module_file, package):

                if module == "__init__" and package == "pkg":
                        versionre = '(?m)^VERSION[^"]*"([^"]*)"'
                        # Grab the previously-built version out of the build
                        # tree.
                        try:
                                ocontent = \
                                    open(self.get_module_outfile(self.build_lib,
                                        [package], module)).read()
                                ov = re.search(versionre, ocontent).group(1)
                        except (IOError, AttributeError):
                                ov = None
                        v = get_git_version()
                        vstr = 'VERSION = "{0}"'.format(v)
                        # If the versions haven't changed, there's no need to
                        # recompile.
                        if v == ov:
                                return

                        with open(module_file) as f:
                                mcontent = f.read()
                                mcontent = re.sub(versionre, vstr, mcontent)
                                tmpfd, tmp_file = tempfile.mkstemp()
                                with open(tmp_file, "w") as wf:
                                        wf.write(mcontent)
                        print("doing version substitution: ", v)
                        rv = _build_py.build_module(self, module, tmp_file, str(package))
                        os.unlink(tmp_file)
                        return rv

                # Will raise a DistutilsError on failure.
                syntax_check(module_file)

                return _build_py.build_module(self, module, module_file, str(package))

        def copy_file(self, infile, outfile, preserve_mode=1, preserve_times=1,
            link=None, level=1):

                # If the timestamp on the source file (coming from mercurial if
                # unchanged, or from the filesystem if changed) doesn't match
                # the filesystem timestamp on the destination, then force the
                # copy to make sure the right data is in place.

                try:
                        dst_mtime = os.stat(outfile).st_mtime
                except OSError as e:
                        if e.errno != errno.ENOENT:
                                raise
                        dst_mtime = time.time()

                # The timestamp for __init__.py is the timestamp for the
                # workspace itself.
                if outfile.endswith("/pkg/__init__.py"):
                        src_mtime = self.timestamps[b"."]
                else:
                        src_mtime = self.timestamps.get(
                            os.path.join("src", infile), self.timestamps[b"."])

                # Force a copy of the file if the source timestamp is different
                # from that of the destination, not just if it's newer.  This
                # allows timestamps in the working directory to regress (for
                # instance, following the reversion of a change).
                if dst_mtime != src_mtime:
                        f = self.force
                        self.force = True
                        dst, copied = _build_py.copy_file(self, infile, outfile,
                            preserve_mode, preserve_times, link, level)
                        self.force = f
                else:
                        dst, copied = outfile, 0

                # If we copied the file, then we need to go and readjust the
                # timestamp on the file to match what we have in our database.
                # Save the filename aside for our version of install_lib.
                if copied and dst.endswith(".py"):
                        os.utime(dst, (src_mtime, src_mtime))
                        self.copied.append(dst)

                return dst, copied

def manpage_input_dir(path):
        """Convert a manpage output path to the directory where its source lives."""

        patharr = path.split("/")
        if len(patharr) == 4:
                loc = ""
        elif len(patharr) == 5:
                loc = patharr[-3].split(".")[0]
        else:
                raise RuntimeError("bad manpage path")
        return os.path.join(patharr[0], loc).rstrip("/")

def xml2roff(files):
        """Convert XML manpages to ROFF for delivery.

        The input should be a list of the output file paths.  The corresponding
        inputs will be generated from this.  We do it in this way so that we can
        share the paths with the install code.

        All paths should have a common manpath root.  In particular, pages
        belonging to different localizations should be run through this function
        separately.
        """

        input_dir = manpage_input_dir(files[0])
        do_files = [
            os.path.join(input_dir, os.path.basename(f))
            for f in files
            if dep_util.newer(os.path.join(input_dir, os.path.basename(f)), f)
        ]
        if do_files:
                # Get the output dir by removing the filename and the manX
                # directory
                output_dir = os.path.join(*files[0].split("/")[:-2])
                args = ["/usr/share/xml/xsolbook/python/xml2roff.py", "-o", output_dir]
                args += do_files
                print(" ".join(args))
                run_cmd(args, os.getcwd())

class build_data_func(Command):
        description = "build data files whose source isn't in deliverable form"
        user_options = []

        # As a subclass of distutils.cmd.Command, these methods are required to
        # be implemented.
        def initialize_options(self):
                pass

        def finalize_options(self):
                pass

        def run(self):
                # Anything that gets created here should get deleted in
                # clean_func.run() below.
                i18n_check()

                for l in pkg_locales:
                        msgfmt("po/{0}.po".format(l), "po/{0}.mo".format(l))

                # generate pkg.pot for next translation
                intltool_update_maintain()
                intltool_update_pot()

                #xml2roff(man1_files + man1m_files + man5_files)
                #xml2roff(man1_ja_files + man1m_ja_files + man5_ja_files)
                #xml2roff(man1_zh_CN_files + man1m_zh_CN_files + man5_zh_CN_files)

def rm_f(filepath):
        """Remove a file without caring whether it exists."""

        try:
                os.unlink(filepath)
        except OSError as e:
                if e.errno != errno.ENOENT:
                        raise

class clean_func(_clean):
        def initialize_options(self):
                _clean.initialize_options(self)
                self.build_base = build_dir

        def run(self):
                _clean.run(self)

                rm_f("po/.intltool-merge-cache")

                for l in pkg_locales:
                        rm_f("po/{0}.mo".format(l))

                rm_f("po/pkg.pot")

                rm_f("po/i18n_errs.txt")

                #shutil.rmtree(MANPAGE_OUTPUT_ROOT, True)

class clobber_func(Command):
        user_options = []
        description = "Deletes any and all files created by setup"

        def initialize_options(self):
                pass
        def finalize_options(self):
                pass
        def run(self):
                # nuke everything
                print("deleting " + dist_dir)
                shutil.rmtree(dist_dir, True)
                print("deleting " + build_dir)
                shutil.rmtree(build_dir, True)
                print("deleting " + root_dir)
                shutil.rmtree(root_dir, True)
                print("deleting " + pkgs_dir)
                shutil.rmtree(pkgs_dir, True)
                print("deleting " + extern_dir)
                shutil.rmtree(extern_dir, True)
                # These files generated by the CFFI build scripts are useless
                # at this point, therefore clean them up.
                print("deleting temporary files generated by CFFI")
                for path in os.listdir(cffi_dir):
                        if not path.startswith("_"):
                                continue
                        path = os.path.join(cffi_dir, path)
                        rm_f(path)

class test_func(Command):
        # NOTE: these options need to be in sync with tests/run.py and the
        # list of options stored in initialize_options below. The first entry
        # in each tuple must be the exact name of a member variable.
        user_options = [
            ("archivedir=", 'a', "archive failed tests <dir>"),
            ("baselinefile=", 'b', "baseline file <file>"),
            ("coverage", "c", "collect code coverage data"),
            ("genbaseline", 'g', "generate test baseline"),
            ("only=", "o", "only <regex>"),
            ("parseable", 'p', "parseable output"),
            ("port=", "z", "lowest port to start a depot on"),
            ("timing", "t", "timing file <file>"),
            ("verbosemode", 'v', "run tests in verbose mode"),
            ("stoponerr", 'x', "stop when a baseline mismatch occurs"),
            ("debugoutput", 'd', "emit debugging output"),
            ("showonexpectedfail", 'f',
                "show all failure info, even for expected fails"),
            ("startattest=", 's', "start at indicated test"),
            ("jobs=", 'j', "number of parallel processes to use"),
            ("quiet", "q", "use the dots as the output format"),
            ("livesystem", 'l', "run tests on live system"),
        ]
        description = "Runs unit and functional tests"

        def initialize_options(self):
                self.only = ""
                self.baselinefile = ""
                self.verbosemode = 0
                self.parseable = 0
                self.genbaseline = 0
                self.timing = 0
                self.coverage = 0
                self.stoponerr = 0
                self.debugoutput = 0
                self.showonexpectedfail = 0
                self.startattest = ""
                self.archivedir = ""
                self.port = 12001
                self.jobs = 1
                self.quiet = False
                self.livesystem = False

        def finalize_options(self):
                pass

        def run(self):

                os.putenv('PYEXE', sys.executable)
                os.chdir(os.path.join(pwd, "tests"))

                # Reconstruct the cmdline and send that to run.py
                cmd = [sys.executable, "run.py"]
                args = ""
                if "test" in sys.argv:
                        args = sys.argv[sys.argv.index("test")+1:]
                        cmd.extend(args)
                subprocess.call(cmd)

class dist_func(_bdist):
        def initialize_options(self):
                _bdist.initialize_options(self)
                self.dist_dir = dist_dir

class Extension(distutils.core.Extension):
        # This class wraps the distutils Extension class, allowing us to set
        # build_64 in the object constructor instead of being forced to add it
        # after the object has been created.
        def __init__(self, name, sources, build_64=False, **kwargs):
                # 'name' and the item in 'sources' must be a string literal
                sources = [str(s) for s in sources]
                distutils.core.Extension.__init__(self, str(name), sources, **kwargs)
                self.build_64 = build_64

# These are set to real values based on the platform, down below
compile_args = None
if osname in ("sunos", "linux", "darwin"):
        compile_args = [ "-O3" ]
if osname == "sunos":
        link_args = []
else:
        link_args = []

ext_modules = [
        Extension(
                'actions._actions',
                _actions_srcs,
                include_dirs = include_dirs,
                extra_compile_args = compile_args,
                extra_link_args = link_args,
                build_64 = True
                ),
        Extension(
                'actions._common',
                _actcomm_srcs,
                include_dirs = include_dirs,
                extra_compile_args = compile_args,
                extra_link_args = link_args,
                build_64 = True
                ),
        Extension(
                '_varcet',
                _varcet_srcs,
                include_dirs = include_dirs,
                extra_compile_args = compile_args,
                extra_link_args = link_args,
                build_64 = True
                ),
        Extension(
                'solver',
                solver_srcs,
                include_dirs = include_dirs + ["."],
                extra_compile_args = compile_args,
                extra_link_args = link_args + solver_link_args,
                define_macros = [('_FILE_OFFSET_BITS', '64')],
                build_64 = True
                ),
        ]
elf_libraries = None
sysattr_libraries = None
data_files = web_files
cmdclasses = {
        'install': install_func,
        'install_data': install_data_func,
        'install_lib': install_lib_func,
        'build': build_func,
        'build_data': build_data_func,
        'build_ext': build_ext_func,
        'build_py': build_py_func,
        'bdist': dist_func,
        'lint': lint_func,
        'clint': clint_func,
        'pylint': pylint_func,
        'pylint_quiet': pylint_func_quiet,
        'pylint_py3k': pylint_func_py3k,
        'clean': clean_func,
        'clobber': clobber_func,
        'test': test_func,
        'installfile': installfile,
        }

# all builds of IPS should have manpages
data_files += [
        (man1_dir, man1_files),
        (man1m_dir, man1m_files),
        (man5_dir, man5_files),
        (man1_ja_JP_dir, man1_ja_files),
        (man1m_ja_JP_dir, man1m_ja_files),
        (man5_ja_JP_dir, man5_ja_files),
        (man1_zh_CN_dir, man1_zh_CN_files),
        (man1m_zh_CN_dir, man1m_zh_CN_files),
        (man5_zh_CN_dir, man5_zh_CN_files),
        (resource_dir, resource_files),
        ]
# add transforms
data_files += [
        (transform_dir, transform_files)
        ]
# add ignored deps
data_files += [
        (ignored_deps_dir, ignored_deps_files)
        ]
if osname == 'sunos':
        # Solaris-specific extensions are added here
        data_files += [
                (smf_app_dir, smf_app_files),
                (execattrd_dir, execattrd_files),
                (authattrd_dir, authattrd_files),
                (userattrd_dir, userattrd_files),
                (sysrepo_dir, sysrepo_files),
                (sysrepo_logs_dir, sysrepo_log_stubs),
                (sysrepo_cache_dir, {}),
                (depot_dir, depot_files),
                (depot_conf_dir, {}),
                (depot_logs_dir, depot_log_stubs),
                (depot_cache_dir, {}),
                (mirror_cache_dir, {}),
                (mirror_logs_dir, {}),
                ]
        # install localizable .xml and its .pot file to put into localizable file package
        data_files += [
            (os.path.join(locale_dir, locale, 'LC_MESSAGES'),
                [('po/{0}.mo'.format(locale), 'pkg.mo')])
            for locale in pkg_locales
        ]
        # install English .pot file to put into localizable file package
        data_files += [
            (os.path.join(locale_dir, '__LOCALE__', 'LC_MESSAGES'),
                [('po/pkg.pot', 'pkg.pot')])
        ]

if osname == 'sunos' or osname == "linux":
        # Unix platforms which the elf extension has been ported to
        # are specified here, so they are built automatically
        elf_libraries = ['elf']
        ext_modules += [
                Extension(
                        'elf',
                        elf_srcs,
                        include_dirs = include_dirs,
                        libraries = elf_libraries,
                        extra_compile_args = compile_args,
                        extra_link_args = link_args,
                        build_64 = True
                        ),
                ]

        # Solaris has built-in md library and Solaris-specific arch extension
        # All others use OpenSSL and cross-platform arch module
        if osname == 'sunos':
            elf_libraries += [ 'md' ]
            sysattr_libraries = [ 'nvpair' ]
            ext_modules += [
                    Extension(
                            '_arch',
                            arch_srcs,
                            include_dirs = include_dirs,
                            extra_compile_args = compile_args,
                            extra_link_args = link_args,
                            define_macros = [('_FILE_OFFSET_BITS', '64')],
			    build_64 = True
                            ),
                    Extension(
                            '_pspawn',
                            pspawn_srcs,
                            include_dirs = include_dirs,
                            extra_compile_args = compile_args,
                            extra_link_args = link_args,
                            define_macros = [('_FILE_OFFSET_BITS', '64')],
			    build_64 = True
                            ),
                    Extension(
                            '_syscallat',
                            syscallat_srcs,
                            include_dirs = include_dirs,
                            extra_compile_args = compile_args,
                            extra_link_args = link_args,
                            define_macros = [('_FILE_OFFSET_BITS', '64')],
                            build_64 = True
                            ),
                    Extension(
                            '_sysattr',
                            sysattr_srcs,
                            include_dirs = include_dirs,
                            libraries = sysattr_libraries,
                            extra_compile_args = compile_args,
                            extra_link_args = link_args,
                            define_macros = [('_FILE_OFFSET_BITS', '64')],
                            build_64 = True
                            ),
                    ]
        else:
            elf_libraries += [ 'ssl' ]

setup(cmdclass = cmdclasses,
    name = 'pkg',
    version = '0.1',
    package_dir = {'pkg':'modules'},
    packages = packages,
    data_files = data_files,
    ext_package = 'pkg',
    ext_modules = ext_modules,
    classifiers = [
        'Programming Language :: Python :: 2',
        'Programming Language :: Python :: 2.7',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.5',
    ]
)

# Vim hints
# vim:ts=8:sw=8:et:fdm=marker
