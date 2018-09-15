#!/usr/bin/python
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

from . import testutils
if __name__ == "__main__":
        testutils.setup_environment("../../../proto")
import pkg5unittest

import grp
import os
import pkg.fmri as fmri
import pkg.manifest as manifest
import pwd
import shutil
import stat
import tempfile
import unittest
from six.moves import range
from six.moves.urllib.error import HTTPError
from six.moves.urllib.request import urlopen, Request, pathname2url

from pkg import misc
from pkg.actions import fromstr
from pkg.digest import DEFAULT_HASH_FUNC
import pkg.portable as portable

class TestPkgsendBasics(pkg5unittest.SingleDepotTestCase):
        persistent_setup = False

        def setUp(self):
                # This test suite needs an actual depot.
                pkg5unittest.SingleDepotTestCase.setUp(self, start_depot=True)

        def __validate_bundle_dir_package(self, pfmri, expected):
                """Used to validate a package imported or generated using
                a DirectoryBundle.  Validation includes installing and
                verifying the specified package, as well as comparing
                the package manifest actions to the expected action data.
                Only dir, file, link, and hardlink actions are compared.

                'pfmri' is a package FMRI object for the package.

                'expected' is a string containing the raw action data to
                use to validate the package.  Only the attributes present
                on each action will be compared."""

                self.pkg("install {0}".format(pfmri))
                self.pkg("verify {0}".format(pfmri))

                m = manifest.Manifest()
                content = self.get_img_manifest(pfmri)
                m.set_content(content)

                # Now build action objects from expected data indexed by path.
                exp_actions = {}
                for entry in expected.splitlines():
                        a = fromstr(entry)

                        if a.attrs["path"] in exp_actions:
                                raise RuntimeError(a.attrs["path"])

                        exp_actions[a.attrs["path"]] = a

                # Number of actions should match number of expected entries.
                self.assertEqual(len(exp_actions), len(expected.splitlines()))

                # Number of expected actions should match number of actual.
                actual = [
                    a for a in m.gen_actions()
                    if a.name in ("dir", "file", "link", "hardlink")
                ]
                self.assertEqual(len(exp_actions), len(actual))

                # For each dir, file, link, or hardlink action, verify that the
                # attributes match expected.
                for a in actual:
                        exp = exp_actions[a.attrs["path"]]
                        for attr in exp.attrs:
                                self.assertEqual(exp.attrs[attr], a.attrs[attr])

                self.pkg("uninstall {0}".format(pfmri))

        def test_0_pkgsend_bad_opts(self):
                """Verify that non-existent or invalid option combinations
                cannot be specified."""

                durl = self.dc.get_depot_url()
                self.pkgsend(durl, "-@ open foo@1.0,5.11-0", exit=2)
                self.pkgsend(durl, "close -@", exit=2)

                # The -e and -n options are opposites and cannot be combined.
                self.pkgsend(durl, "open -en foo@1.0", exit=2)
                self.pkgsend(durl, "open -ne foo@1.0", exit=2)

                # A destination repository must be specified.
                self.pkgsend("", "close", exit=2)
                self.pkgsend("", "publish", exit=2)
                self.assertTrue("pkgsend publish:" in self.errout)

        def test_1_pkgsend_abandon(self):
                """Verify that an abandoned tranasaction is not published."""

                dhurl = self.dc.get_depot_url()
                dfurl = "file://{0}".format(self.dc.get_repodir())

                for url in (dhurl, dfurl):
                        for line in \
                            """open shouldnotexist@1.0,5.11-0
                            add dir mode=0755 owner=root group=bin path=/bin
                            close -A""".splitlines():
                                self.pkgsend(url, line)

                        if url == dfurl:
                                # Must restart pkg.depotd so it will pickup the
                                # changes to the catalog.
                                self.restart_depots()

                        # For now, the pkg(1) client only supports http, so use
                        # the http url always.
                        self.image_create(dhurl)
                        self.pkg("list -a shouldnotexist", exit=1)
                        self.image_destroy()

        def test_2_invalid_url(self):
                """Verify that an invalid repository URL will result in an
                error."""

                # Verify that specifying a malformed or incomplete URL fails
                # gracefully for every known scheme and a few bogus schemes.
                for scheme in ("bogus", "file", "http", "https", "null"):
                        # The first two cases should succeed for 'null'
                        self.pkgsend(scheme + "://", "open notarepo@1.0",
                            exit=scheme != "null")
                        self.pkgsend(scheme + ":", "open notarepo@1.0",
                            exit=scheme != "null")
                        self.pkgsend(scheme, "open notarepo@1.0", exit=1)

                # Create an empty directory to abuse as a repository.
                junk_repo = os.path.join(self.test_root, "junk-repo")
                os.makedirs(junk_repo, misc.PKG_DIR_MODE)

                # Point at a valid directory that does not contain a repository.
                dfurl = "file://" + junk_repo

                # Verify that specifying a non-existent directory for a file://
                # repository fails gracefully.
                self.pkgsend(os.path.join(dfurl, "nochance"),
                    "open nosuchdir@1.0", exit=1)

                # Verify that specifying a directory that is not a file://
                # repository fails gracefully.
                self.pkgsend(dfurl, "open notarepo@1.0", exit=1)

                # Point at a non-existent http(s) repository; port 1 is an
                # unassigned port that nothing should use.
                dhurl = "http://localhost:1"
                dshurl = "http://localhost:1"

                # Verify that specifying a non-existent (i.e. unable to connect
                # to) http:// repository fails gracefully.
                self.pkgsend(dhurl, "open nosuchdir@1.0", exit=1)
                self.pkgsend(dshurl, "open nosuchdir@1.0", exit=1)

        def test_3_bad_transaction(self):
                """Verify that invalid Transaction IDs are handled correctly."""

                dhurl = self.dc.get_depot_url()
                dfurl = "file://{0}".format(self.dc.get_repodir())

                os.environ["PKG_TRANS_ID"] = "foobarbaz"

                for url in (dfurl, dhurl):
                        self.pkgsend(url, "add file bin/ls path=/bin/ls",
                            exit=1)

        def test_4_bad_actions(self):
                """Verify that malformed or invalid actions are handled
                correctly.  This only checks a few cases as the pkg.action
                class itself should be handling the actual verification;
                the client just needs to handle the appropriate exceptions
                gracefully."""

                dhurl = self.dc.get_depot_url()
                dfurl = "file://{0}".format(self.dc.get_repodir())
                imaginary_file = os.path.join(self.test_root, "imaginary_file")

                # Must open transaction using HTTP url first so that transaction
                # will be seen by the depot server and when using file://.
                self.pkgsend(dhurl, "open foo@1.0")

                # Create a dummy file.
                self.make_misc_files("tmp/dummy1")

                for url in (dhurl, dfurl):
                        # Should fail because type attribute is missing.
                        self.pkgsend(url,
                            "add depend fmri=foo@1.0", exit=1)

                        # Should fail because type attribute is invalid.
                        self.pkgsend(url,
                            "add depend type=unknown fmri=foo@1.0", exit=1)

                        # Should fail because path attribute is missing.
                        self.pkgsend(url,
                            "add file bin/ls", exit=1)

                        # Should fail because mode attribute is missing.
                        self.pkgsend(url,
                            "add file tmp/dummy1 owner=root group=bin "
                            "path=/tmp/dummy1", exit=1)

                        # Should fail because mode attribute is invalid.
                        self.pkgsend(url,
                            """add file tmp/dummy1 owner=root group=bin """
                            """mode="" path=/tmp/dummy1""", exit=1)
                        self.pkgsend(url,
                            "add file tmp/dummy1 owner=root group=bin "
                            "mode=44755 path=/tmp/dummy1", exit=1)
                        self.pkgsend(url,
                            "add file tmp/dummy1 owner=root group=bin "
                            "mode=44 path=/tmp/dummy1", exit=1)
                        self.pkgsend(url,
                            """add file tmp/dummy1 owner=root group=bin """
                            """mode=???? path=/tmp/dummy1""", exit=1)

                        # Should fail because owner attribute is missing.
                        self.pkgsend(url,
                            "add file tmp/dummy1 group=bin "
                            "mode=0644 path=/tmp/dummy1", exit=1)

                        # Should fail because owner attribute is invalid.
                        self.pkgsend(url,
                            """add file tmp/dummy1 owner=" " group=bin """
                            """mode=0644 path=/tmp/dummy1""", exit=1)

                        # Should fail because group attribute is missing.
                        self.pkgsend(url,
                            "add file tmp/dummy1 owner=root "
                            "mode=0644 path=/tmp/dummy1", exit=1)

                        # Should fail because group attribute is invalid.
                        self.pkgsend(url,
                            """add file tmp/dummy1 owner=root group=" " """
                            """mode=0644 path=/tmp/dummy1""", exit=1)

                        # Should fail because path attribute is missing a value.
                        self.pkgsend(url,
                            "add file bin/ls path=", exit=1)

                        # Should fail because the file does not exist.
                        self.pkgsend(url,
                            "add file {0} path=/bin/ls".format(imaginary_file), exit=1)

                        # Should fail because path=/bin/ls will be interpreted
                        # as the filename and is not a valid file.
                        self.pkgsend(url,
                            "add file path=/bin/ls", exit=1)

                        # Should fail because the action is unknown.
                        self.pkgsend(url,
                            "add bogusaction", exit=1)

                        # Should fail because we never publish unknown actions.
                        self.pkgsend(url,
                             "add unknown path=foo", exit=1)

                # Simulate bad action data being sent by client via HTTP; this
                # should be rejected by the server.
                trx_id = os.environ["PKG_TRANS_ID"]
                headers = {
                    "X-IPKG-SETATTR0": "name=multiple_value",
                    "X-IPKG-SETATTR1": 'value=[__import__("sys").exit(99)]'
                }

                try:
                        url = "{0}/{1}/0/{2}".format(dhurl, "add", "/".join((trx_id,
                            "set")))
                        req = Request(url=url, headers=headers)
                        urlopen(req)
                except HTTPError as e:
                        err_txt = e.read()
                        # err_txt is bytes
                        self.assertTrue(b"The specified Action attribute "
                            b"value" in err_txt)
                        self.assertTrue(b"is not valid." in err_txt)
                else:
                        raise RuntimeError("Test failed!")

        def test_5_bad_open(self):
                """Verify that a bad open is handled properly.  This could be
                because of an invalid FMRI that was specified, or many other
                reasons."""

                dhurl = self.dc.get_depot_url()
                dfurl = "file://{0}".format(self.dc.get_repodir())

                for url in (dhurl, dfurl):
                        # Should fail because no fmri was specified.
                        self.pkgsend(url, "open", exit=2)

                        # Should fail because an invalid fmri was specified.
                        self.pkgsend(url, "open foo@1.a", exit=1)

                # Should fail because repository does not exist.
                self.pkgsend(dfurl + "junk", "open foo@1.a", exit=1)

        def test_6_help(self):
                """Verify that help works as expected."""

                self.pkgsend(command="-?")
                self.pkgsend(command="--help")

                self.pkgsend(command="-? bobcat")
                self.pkgsend(command="--help bobcat")

                # Specifying no commands should result in usage error.
                self.pkgsend(exit=2)

        def test_7_create_repo(self):
                """Verify that create-repository works as expected."""

                self.dc.stop()
                rpath = os.path.join(self.test_root, "example_repo")

                # ensure we fail when presented with a file://host/path/example_repo
                # which includes a hostname, bug 14022
                self.pkgsend("file:/{0}".format(rpath), "create-repository"
                    " --set-property publisher.prefix=test", exit=1)

                # check that we can create a repository using URIs with varying
                # number of '/' characters and verify the repo was created.
                for slashes in [ "", "//", "///", "////" ]:
                        if os.path.exists(rpath):
                                shutil.rmtree(rpath)
                        self.pkgsend("file:{0}{1}".format(slashes, rpath), "create-repository"
                            " --set-property publisher.prefix=test")

                        # Assert that create-repository creates as version 3
                        # repository for compatibility with older consumers.
                        for expected in ("catalog", "file", "index", "pkg",
                            "trans", "tmp", "cfg_cache"):
                                # A v3 repository must have all of the above.
                                assert os.path.exists(os.path.join(rpath,
                                    expected))

                        # Now verify that the repository was created by starting the
                        # depot server in readonly mode using the target repository.
                        # If it wasn't, restart_depots should fail with an exception
                        # since the depot process will exit with a non-zero return
                        # code.
                        self.dc.set_repodir(rpath)
                        self.dc.set_readonly()
                        self.dc.start()
                        self.dc.stop()

                # Now verify that creation of a repository is rejected for all
                # schemes except file://.
                self.pkgsend("http://invalid.test1", "create-repository", exit=1)
                self.pkgsend("https://invalid.test2", "create-repository", exit=1)

        def test_8_bug_7908(self):
                """Verify that when provided the name of a symbolic link to a
                file, that publishing will still work as expected."""

                # First create our dummy data file.
                fd, fpath = tempfile.mkstemp(dir=self.test_root)
                fp = os.fdopen(fd, "w")
                fp.write("foo")
                fp.close()

                # Then, create a link to it.
                lpath = os.path.join(self.test_root, "test_8_foo")
                os.symlink(fpath, lpath)

                # Next, publish it using both the real path and the linked path
                # but using different names.
                dhurl = self.dc.get_depot_url()
                self.pkgsend_bulk(dhurl,
                    """open testlinkedfile@1.0
                    add file {0} mode=0755 owner=root group=bin path=/tmp/f.foo
                    add file {1} mode=0755 owner=root group=bin path=/tmp/l.foo
                    close""".format(os.path.basename(fpath), os.path.basename(lpath)))

                # Finally, verify that both files were published.
                self.image_create(dhurl)
                self.pkg("contents -r -H -o action.raw -t file testlinkedfile |"
                   " grep 'f.foo.*pkg.size=3'")
                self.pkg("contents -r -H -o action.raw -t file testlinkedfile |"
                   " grep 'l.foo.*pkg.size=3'")
                self.image_destroy()

        def test_9_multiple_dirs(self):
                rootdir = self.test_root
                dir_1 = os.path.join(rootdir, "dir_1")
                dir_2 = os.path.join(rootdir, "dir_2")
                os.mkdir(dir_1)
                os.mkdir(dir_2)
                open(os.path.join(dir_1, "A"), "w").close()
                open(os.path.join(dir_2, "B"), "w").close()
                mfpath = os.path.join(rootdir, "manifest_test")
                with open(mfpath, "w") as mf:
                        mf.write("""file NOHASH mode=0755 owner=root group=bin path=/A
                            file NOHASH mode=0755 owner=root group=bin path=/B
                            set name=pkg.fmri value=testmultipledirs@1.0
                            """)

                dhurl = self.dc.get_depot_url()
                self.pkgsend(dhurl, """publish -d {0} -d {1} < {2}""".format(dir_1,
                    dir_2, mfpath))

                self.image_create(dhurl)
                self.pkg("install testmultipledirs")
                self.pkg("verify")
                self.image_destroy()

        def test_10_bundle_dir(self):
                """Verify that import and generate of a directory bundle works
                as expected."""

                rootdir = self.test_root
                src_dir1 = os.path.join(rootdir, "foo")
                src_dir2 = os.path.join(rootdir, "bar")

                # Build a file tree under each source directory to test
                # import and generate functionality.  Tree should look like:
                #   src-foo/
                #       file-foo
                #       link-foo -> file-foo
                #       hardlink-foo -> file-foo
                #       dir-foo/
                #           subfile-foo
                #           sublink-foo -> ../file-foo
                #           subhardlink-foo -> ../file-foo
                #           subfilelink-foo -> subfile-foo
                #           subfilehardlink-foo -> subfile-foo
                #           subdir-foo/
                #               subdirfile-foo
                #
                #  Where 'foo' is replaced with 'bar' for the second source dir.

                cwd = os.getcwd()
                for src_dir in (src_dir1, src_dir2):
                        # Final component used as part of name for all entries.
                        name = os.path.basename(src_dir)

                        # File at top level in source directory.
                        top_file = os.path.join(src_dir, "file-{0}".format(name))
                        self.make_misc_files(os.path.relpath(top_file, src_dir),
                            prefix=name, mode=0o644)

                        # Link at top level in source directory.
                        os.chdir(src_dir)
                        os.symlink(os.path.basename(top_file), "link-{0}".format(name))
                        os.chdir(cwd)

                        # Hard link at top level in source directory.
                        os.link(top_file, os.path.join(src_dir,
                            "hardlink-{0}".format(name)))

                        # Directory at top level in source directory.
                        top_dir = os.path.join(src_dir, "dir-{0}".format(name))
                        os.mkdir(top_dir, 0o755)

                        # File in top_dir.
                        top_dir_file = os.path.join(top_dir,
                            "subfile-{0}".format(name))
                        self.make_misc_files(os.path.relpath(top_dir_file,
                            src_dir), prefix=name, mode=0o444)

                        # Link in top_dir to file in parent dir.
                        os.chdir(top_dir)
                        os.symlink(os.path.relpath(top_file, top_dir),
                            "sublink-{0}".format(name))
                        os.chdir(cwd)

                        # Link in top_dir to file in top_dir.
                        os.chdir(top_dir)
                        os.symlink(os.path.basename(top_dir_file),
                            "subfilelink-{0}".format(name))
                        os.chdir(cwd)

                        # Hard link in top_dir to file in parent dir.
                        os.link(top_file, os.path.join(top_dir,
                            "subhardlink-{0}".format(name)))

                        # Hard link in top_dir to file in top_dir.
                        os.link(top_dir_file, os.path.join(top_dir,
                            "subfilehardlink-{0}".format(name)))

                        # Directory in top_dir.
                        sub_dir = os.path.join(top_dir, "subdir-{0}".format(name))
                        os.mkdir(sub_dir, 0o750)

                        # File in sub_dir.
                        sub_dir_file = os.path.join(sub_dir,
                            "subdirfile-{0}".format(name))
                        self.make_misc_files(os.path.relpath(sub_dir_file,
                            src_dir), prefix=name, mode=0o400)

                # Pre-generated result used for package validation.
                expected = """\
dir group=bin mode=0755 owner=root path=dir-foo
file 4b5e791c627772d731d6c1623228a9c147a7dc3a chash=57ac66d45c0c4adb6d3626bd711c6f09f10fd286 group=bin mode=0644 owner=root path=file-foo
link path=link-foo target=file-foo
hardlink path=hardlink-foo target=file-foo
dir group=bin mode=0750 owner=root path=dir-foo/subdir-foo
file a10c7e788532fd2e7ee7eb9682733dd4e3fbe9de chash=aa3025ca5df3f9f6560db438b1b748d8155c9763 group=bin mode=0444 owner=root path=dir-foo/subfile-foo
link path=dir-foo/sublink-foo target=../file-foo
link path=dir-foo/subfilelink-foo target=subfile-foo
hardlink path=dir-foo/subhardlink-foo target=../file-foo
hardlink path=dir-foo/subfilehardlink-foo target=subfile-foo
file 7e810bfd0fddc15334ae8f8c5720417c19d26d65 chash=d4e6a65e17cad442857eea1885b909b09e96f40e group=bin mode=0400 owner=root path=dir-foo/subdir-foo/subdirfile-foo
dir group=bin mode=0755 owner=root path=dir-bar
file 994c33bbd9d77c3a54a1130d07f87f9d57c91d53 chash=98b4c123eefd676a472924e004dc293ddd44f73a group=bin mode=0644 owner=root path=file-bar
link path=link-bar target=file-bar
hardlink path=hardlink-bar target=file-bar
dir group=bin mode=0750 owner=root path=dir-bar/subdir-bar
file 1e4760226a169690da06b592e8eedb6d79c1b3a0 chash=71d14067e564c3c52261918788f353e99d249a87 group=bin mode=0444 owner=root path=dir-bar/subfile-bar
link path=dir-bar/sublink-bar target=../file-bar
link path=dir-bar/subfilelink-bar target=subfile-bar
hardlink path=dir-bar/subhardlink-bar target=../file-bar
hardlink path=dir-bar/subfilehardlink-bar target=subfile-bar
file 6a1ae3def902f5612a43f0c0836fe05bc4f237cf chash=be9c91959ec782acb0f081bf4bf16677cb09125e group=bin mode=0400 owner=root path=dir-bar/subdir-bar/subdirfile-bar"""

                # Test with and without trailing slash on import path.
                # This cannot be done using pkgsend_bulk, which doesn't
                # support import.
                url = self.dc.get_depot_url()
                self.pkgsend(url, "open foo@1.0")
                self.pkgsend(url, "import {0}".format(src_dir1))
                self.pkgsend(url, "import {0}/".format(src_dir2))
                ret, sfmri = self.pkgsend(url, "close")
                foo_fmri = fmri.PkgFmri(sfmri)

                # Test with and without trailing slash on generate path.
                # This cannot be done using pkgsend_bulk, which doesn't
                # support generate.
                rc, out1 = self.pkgsend(url, "generate {0}".format(src_dir1))
                rc, out2 = self.pkgsend(url, "generate {0}/".format(src_dir2))

                # Test with non existing bundle
                non_existing_bundle = os.path.join(self.test_root,
                    "non_existing_bundle.tar")
                rc, out3 = self.pkgsend(url, "generate {0}".format(non_existing_bundle),
                    exit=1)

                # Test with unknown bundle
                unknown_bundle = self.make_misc_files("tmp/unknown_file")
                rc, out3 = self.pkgsend(url, "generate {0}".format(unknown_bundle),
                    exit=1)

                self.pkgsend(url, "open bar@1.0")
                mpath = self.make_misc_files({ "bar.mfst": out1 + out2 })[0]
                self.pkgsend(url, "include -d {0} -d {1} {2}".format(src_dir1,
                    src_dir2, mpath))
                ret, sfmri = self.pkgsend(url, "close")
                bar_fmri = fmri.PkgFmri(sfmri)

                self.image_create(url)

                # Perform actual validation; content should be identical
                # whether import or generate was used.
                for pfmri in (foo_fmri, bar_fmri):
                        self.__validate_bundle_dir_package(pfmri, expected)


        # A map used to create a SVR4 package, and check an installed pkg(5)
        # version of that package, created via 'pkgsend import'.  We map the
        # path name to
        # [ type, mode, user, group, digest ] initially setting the digest to None
        sysv_contents = {
            "foobar": [ "d", 0o715, "nobody", "nobody", None ],
            "foobar/bar": [ "f", 0o614, "root", "sys", None ],
            "foobar/baz": [ "f", 0o644, "daemon", "adm", None ],
            "foobar/symlink": [ "s", None, "daemon", "adm", None ],
            "foobar/hardlink": [ "l", 0o644, "daemon", "adm", None ],
            "copyright": [ "i", None, None, None, None ],
            # check that pkgsend doesn't generate an Action for "i" files
            "pkginfo": [ "i", None, None, None, None ],
            "myclass": [ "i", None, None, None, None ],
            "prototype": [ "i", None, None, None, None ],
            "postinstall": [ "i", None, None, None, None ],
            # pkgmap is not an "i" file, but we still want to
            # check that it is not installed in the image
            "pkgmap": [ "i", None, None, None, None ] }

        # Same, but for the non-relocatable package
        sysv_nonreloc_contents = {
            "etc": [ "d", 0o755, "root", "sys", None ],
            "etc/foo.conf": [ "f", 0o644, "root", "sys", None ],
            "SUNWfoo/bin": [ "d", 0o755, "root", "bin", None ],
            "SUNWfoo/bin/foo": [ "f", 0o755, "root", "bin", None ],
            "copyright": [ "i", None, None, None, None ],
            # check that pkgsend doesn't generate an Action for "i" files
            "pkginfo": [ "i", None, None, None, None ],
            # pkgmap is not an "i" file, but we still want to
            # check that it is not installed in the image
            "pkgmap": [ "i", None, None, None, None ] }

        # a prototype that uses classes and postinstall scripts, which
        # pkgsend should complain about
        sysv_classes_prototype = """i pkginfo
            i copyright
            i postinstall
            d none foobar 0715 nobody nobody
            f none foobar/bar 0614 root sys
            f myclass foobar/baz 0644 daemon adm
            s none foobar/symlink=baz
            l none foobar/hardlink=baz
            i myclass"""

        sysv_prototype = """i pkginfo
            i copyright
            d none foobar 0715 nobody nobody
            f none foobar/bar 0614 root sys
            f none foobar/baz 0644 daemon adm
            s none foobar/symlink=baz
            l none foobar/hardlink=baz"""

        sysv_nonreloc_prototype = """\
            i pkginfo
            i copyright
            d none /etc 0755 root sys
            f none /etc/foo.conf 0644 root sys
            d none SUNWfoo/bin 0755 root bin
            f none SUNWfoo/bin/foo 0755 root bin"""

        sysv_pkginfo = 'PKG="nopkg"\n'\
            'NAME="No package"\n'\
            'DESC="This is a sample package"\n'\
            'ARCH="all"\n'\
            'CLASSES="none myclass"\n'\
            'PKG_CONTENTS="bobcat"\n'\
            'CATEGORY="utility"\n'\
            'VENDOR="nobody"\n'\
            'PSTAMP="7thOct83"\n'\
            'ISTATES="S s 1 2 3"\n'\
            'RSTATES="S s 1 2 3"\n'\
            'BASEDIR="/"'

        sysv_pkginfo_2 = 'PKG="nopkgtwo"\n'\
            'NAME="No package"\n'\
            'DESC="This is another sample package"\n'\
            'ARCH="all"\n'\
            'CLASSES="none myclass"\n'\
            'PKG_CONTENTS="bobcat"\n'\
            'CATEGORY="utility"\n'\
            'VENDOR="nobody"\n'\
            'PSTAMP="7thOct83"\n'\
            'ISTATES="S s 1 2 3"\n'\
            'RSTATES="S s 1 2 3"\n'\
            'BASEDIR="/"'

        def create_sysv_package(self, rootdir, prototype_contents,
            contents_dict, pkginfo_contents=sysv_pkginfo):
                """Create a SVR4 package at a given location using some predefined
                contents and a given prototype."""
                pkgroot = os.path.join(rootdir, "sysvpkg")
                os.mkdir(pkgroot)

                # create files and directories in our proto area
                for entry in contents_dict:
                        ftype, mode  = contents_dict[entry][:2]
                        if ftype in "fi":
                                dirname = os.path.dirname(entry)
                                try:
                                        os.makedirs(os.path.join(pkgroot, dirname))
                                except OSError as err: # in case the dir exists already
                                        if err.errno != os.errno.EEXIST:
                                                raise
                                fpath = os.path.join(pkgroot, entry)
                                f = open(fpath, "w")
                                f.write("test" + entry)
                                f.close()
                                # compute a digest of the file we just created,
                                # which we can use when validating later.
                                contents_dict[entry][4] = \
                                    misc.get_data_digest(fpath,
                                    hash_func=DEFAULT_HASH_FUNC)[0]

                        elif ftype == "d":
                                try:
                                        os.makedirs(os.path.join(pkgroot, entry), mode)
                                except OSError as err:
                                        if err.errno != os.errno.EEXIST:
                                                raise

                pkginfopath = os.path.join(pkgroot, "pkginfo")
                pkginfo = open(pkginfopath, "w")
                pkginfo.write(pkginfo_contents)
                pkginfo.close()

                prototypepath = os.path.join(pkgroot, "prototype")
                prototype = open(prototypepath, "w")
                prototype.write(prototype_contents)
                prototype.close()

                self.cmdline_run("pkgmk -o -r {0} -d {1} -f {2}".format(
                         pkgroot, rootdir, prototypepath), coverage=False)

                shutil.rmtree(pkgroot)

        def __test_sysv_import(self, url, spath, contents):
                """Private helper function to test pkgsend import."""

                self.pkgsend(url, "open nopkg@1.0")
                self.pkgsend(url, "import {0}".format(spath))
                self.pkgsend(url, "close")

                self.image_create(url)
                self.pkg("install nopkg")
                self.validate_sysv_contents("nopkg", contents)
                self.pkg("verify")
                self.pkg("contents -m nopkg")
                self.image_destroy()

        def __test_sysv_gen_publish(self, rpath, spath, contents):
                """Private helper function to test pkgsend generate and
                publish for sysv packages."""

                mpath = os.path.join(self.test_root, "sysv.p5m")
                self.create_repo(rpath,
                    properties={ "publisher": { "prefix": "test" }})

                self.pkgsend(None, "generate {0} > {1}".format(spath, mpath))
                with open(mpath, "a+") as mf:
                        mf.write("set name=pkg.fmri value=nopkg@1.0\n")
                with open(mpath, "r") as mf:
                        self.debug(mf.read())
                self.pkgsend(rpath, "publish -b {0} {1}".format(spath, mpath))

                self.image_create("file://{0}".format(rpath))
                self.pkg("install nopkg")
                self.validate_sysv_contents("nopkg", contents)
                self.pkg("verify")
                self.image_destroy()

        def test_11_bundle_sysv_dir(self):
                """ A SVR4 directory-format package can be imported, its contents
                published to a repo and installed to an image."""
                self.create_sysv_package(self.test_root, self.sysv_prototype,
                    self.sysv_contents)

                # Test both HTTP and file-based access since there are subtle
                # differences in action publication.
                spath = os.path.join(self.test_root, "nopkg")
                self.__test_sysv_import(self.dc.get_depot_url(), spath,
                    self.sysv_contents)

                rpath = os.path.join(self.test_root, "test11-repo")
                self.create_repo(rpath,
                    properties={ "publisher": { "prefix": "test" } })
                self.__test_sysv_gen_publish(rpath, spath,
                    self.sysv_contents)

                # Test with trailing slash to verify that doesn't matter.
                shutil.rmtree(rpath)
                self.create_repo(rpath,
                    properties={ "publisher": { "prefix": "test" } })
                self.__test_sysv_gen_publish(rpath, spath + "/",
                    self.sysv_contents)

        def test_11_bundle_sysv_dir_nonrelocatable(self):
                """A SVr4 directory format package with non-relocatable elements
                can be imported, its contents published to a repo and installed
                to an image."""

                self.create_sysv_package(self.test_root,
                    self.sysv_nonreloc_prototype, self.sysv_nonreloc_contents)

                url = self.dc.get_depot_url()
                spath = os.path.join(self.test_root, "nopkg")
                self.__test_sysv_import(url, spath, self.sysv_nonreloc_contents)

                # This time, use 'generate' and 'publish' to do the import
                # directly to a new file repository.
                rpath = os.path.join(self.test_root, "test11-genrepo")
                self.__test_sysv_gen_publish(rpath, spath,
                    self.sysv_nonreloc_contents)

                # Test with trailing slash to verify that doesn't matter.
                shutil.rmtree(rpath)
                self.create_repo(rpath,
                    properties={ "publisher": { "prefix": "test" } })
                self.__test_sysv_gen_publish(rpath, spath + "/",
                    self.sysv_nonreloc_contents)

        def test_12_bundle_sysv_datastream(self):
                """ A SVR4 datastream package can be imported, its contents
                published to a repo and installed to an image."""
                self.create_sysv_package(self.test_root, self.sysv_prototype,
                    self.sysv_contents)
                self.cmdline_run("pkgtrans -s {0} {1} nopkg".format(self.test_root,
                        os.path.join(self.test_root, "nopkg.pkg")),
                        coverage=False)

                url = self.dc.get_depot_url()
                spath = os.path.join(self.test_root, "nopkg")
                self.__test_sysv_import(url, spath, self.sysv_contents)

                # This time, use 'generate' and 'publish' to do the import
                # directly to a new file repository.
                rpath = os.path.join(self.test_root, "test12-genrepo")
                self.__test_sysv_gen_publish(rpath, spath, self.sysv_contents)

        def validate_sysv_contents(self, pkgname, contents_dict):
                """ Check that the image contents correspond to the SVR4 package.
                The tests in t_pkginstall cover most of the below, however
                here we're interested in ensuring that pkgsend really did import
                and publish everything we expected from the sysv package.
                """

                # verify we have copyright text
                self.pkg("info --license {0}".format(pkgname))

                for entry in contents_dict:
                        name = os.path.join(self.img_path(), entry)
                        ftype, mode, user, group, digest = contents_dict[entry]

                        if ftype in "fl":
                                self.assertTrue(os.path.isfile(name))
                        elif ftype == "d":
                                self.assertTrue(os.path.isdir(name))
                        elif ftype == "s":
                                self.assertTrue(os.path.islink(name))
                        elif ftype == "i":
                                # we should not have installed these
                                self.assertFalse(os.path.exists(name))
                                continue

                        if digest:
                                # the hash_func used here just needs to
                                # correspond with the one used when creating
                                # the svr4 package - it does not consult the
                                # pkg(5) hash or chash attributes.
                                pkg5_digest, contents = misc.get_data_digest(
                                    name, return_content=True,
                                    hash_func=DEFAULT_HASH_FUNC)
                                self.assertEqual(digest, pkg5_digest,
                                    "{0}: {1} != {2}, '{3}'".format(name, digest,
                                    pkg5_digest, contents))

                        st = os.stat(os.path.join(self.img_path(), name))
                        if mode is not None:
                                portable.assert_mode(name, stat.S_IMODE(mode))
                        self.assertEqual(portable.get_user_by_name(user,
                            self.img_path(), use_file=True), st.st_uid)
                        self.assertEqual(portable.get_group_by_name(group,
                            self.img_path(), use_file=True), st.st_gid)

        def test_13_pkgsend_indexcontrol(self):
                """Verify that "pkgsend refresh-index" triggers indexing."""

                dhurl = self.dc.get_depot_url()
                dfurl = "file://{0}".format(pathname2url(self.dc.get_repodir()))

                fd, fpath = tempfile.mkstemp(dir=self.test_root)

                self.image_create(dhurl)

                self.dc.stop()
                self.dc.set_readonly()

                self.pkgsend(dfurl, "open file@1.0")
                self.pkgsend(dfurl, "add file {0} {1} path=/tmp/f.foo" \
                   .format(fpath, "mode=0755 owner=root group=bin"))

                # Verify that --no-index (even though it is now ignored) can be
                # specified and doesn't cause pkgsend failure.
                self.pkgsend(dfurl, "close --no-index")
                self.wait_repo(self.dc.get_repodir())

                self.dc.start()
                self.pkg("search file:::", exit=1)

                self.dc.stop()
                self.pkgsend(dfurl, "refresh-index")
                self.dc.start()
                self.pkg("search file:::")

                self.dc.stop()
                self.dc.set_readwrite()
                self.dc.start()

                self.pkgsend(dhurl, "open http@1.0")
                self.pkgsend(dhurl, "add file {0} {1} path=/tmp/f.foo" \
                   .format(fpath, "mode=0755 owner=root group=bin"))
                self.pkgsend(dhurl, "close")

                self.wait_repo(self.dc.get_repodir())
                self.pkg("search http:::", exit=1)

                self.pkgsend(dhurl, "refresh-index")

                self.pkg("search http:::")

                self.image_destroy()
                os.close(fd)
                os.unlink(fpath)

        def test_14_obsolete(self):
                """Obsolete and renamed packages can only have very specific
                content."""

                # Obsolete packages can't have contents
                badobs1 = """
                    open badobs@<ver>
                    add dir path=usr mode=0755 owner=root group=root
                    add set name=pkg.obsolete value=true
                    close
                """

                # Obsolete packages can't have contents (reordered)
                badobs2 = """
                    open badobs@<ver>
                    add set name=pkg.obsolete value=true
                    add dir path=usr mode=0755 owner=root group=root
                    close
                """

                # Renamed packages can't have contents
                badren1 = """
                    open badren@<ver>
                    add set name=pkg.renamed value=true
                    add dir path=usr mode=0755 owner=root group=root
                    add depend fmri=otherpkg type=require
                    close
                """

                # Renamed packages must have dependencies
                badren2 = """
                    open badren@<ver>
                    add set name=pkg.renamed value=true
                    close
                """

                # A package can't be marked both obsolete and renamed
                badrenobs1 = """
                    open badrenobs@<ver>
                    add set name=pkg.obsolete value=true
                    add set name=pkg.renamed value=true
                    close
                """

                # Obsolete packages can have metadata
                bob = """
                    open bobsyeruncle@<ver>
                    add set name=pkg.obsolete value=true
                    add set name=pkg.summary value="A test package"
                    close
                """

                # Package contents and line number where it should fail.
                pkgs = [
                    (badobs1, 3),
                    (badobs2, 3),
                    (badren1, 3),
                    (badren2, 3),
                    (badrenobs1, 3),
                    (bob, -1)
                ]
                dhurl = self.dc.get_depot_url()
                junk_repo = os.path.join(self.test_root, "obs-junkrepo")
                dfurl = "file://" + junk_repo
                self.pkgsend(dfurl,
                    "create-repository --set-property publisher.prefix=test")

                ver = 0
                for p, line in pkgs:
                        for url in (dhurl, dfurl):
                                # Try a bulk pkgsend first
                                exit = int(line >= 0)
                                # We publish fast enough that we can end up
                                # publishing the same package version twice
                                # within the same second, so force the version
                                # to be incremented.
                                p2 = p.replace("<ver>", str(ver))
                                try:
                                        self.pkgsend_bulk(url, p2, exit=exit)
                                except:
                                        self.debug("Expected exit code {0} "
                                            "while publishing {1}".format(exit,
                                            p2))
                                        raise

                                # Then do it line-by-line
                                for i, l in enumerate(p.splitlines()):
                                        if not l.strip():
                                                continue
                                        exit = int(i == line)
                                        l = l.replace("<ver>", str(ver + 1))
                                        self.pkgsend(url, l.strip(), exit=exit)
                                        if exit:
                                                self.pkgsend(url, "close -A")
                                                break
                                ver += 2

        def test_15_test_no_catalog_option(self):
                """Verify that --no-catalog works as expected.  Also exercise
                --fmri-in-manifest"""
                pkg_manifest = \
"""set name=pkg.fmri value=foo@0.5.11,5.11-0.129
dir path=foo mode=0755 owner=root group=bin
dir path=foo/bar mode=0755 owner=root group=bin
"""
                self.dc.stop()
                rpath = self.dc.get_repodir()
                fpath = os.path.join(self.test_root, "manifest")
                f = open(fpath, "w")
                f.write(pkg_manifest)
                f.close()
                self.pkgsend("file://{0}".format(rpath),
                    "create-repository --set-property publisher.prefix=test")

                repo = self.dc.get_repo()
                cat_path = repo.catalog_1("catalog.attrs")
                mtime = os.stat(cat_path).st_mtime
                self.pkgsend("file://{0}".format(rpath), "publish --fmri-in-manifest "
                    "--no-catalog {0}".format(fpath))
                new_mtime = os.stat(cat_path).st_mtime
                # Check that modified times are the same before and after
                # publication.
                self.assertEqual(mtime, new_mtime)

                self.pkgsend("file://{0}".format(rpath), "open bar@1.0")
                self.pkgsend("file://{0}".format(rpath), "close --no-catalog")
                new_mtime = os.stat(cat_path).st_mtime
                # Check that modified times are the same before and after
                # publication
                self.assertEqual(mtime, new_mtime)

                # Now start depot and verify both packages are visible when
                # set to add content on startup.
                self.dc.set_add_content()
                self.dc.start()
                dhurl = self.dc.get_depot_url()
                self.dc.set_repodir(rpath)
                self.image_create(dhurl)
                self.pkg("list -a bar foo")
                self.image_destroy()

        def test_16_multiple_manifests(self):
                """Verify that when sending multiple manifests, the contents
                of all manifests are published."""

                # First create two dummy data files.
                test_files = ["dummy1", "dummy2"]
                self.make_misc_files(test_files)

                # create two manifests.
                for path in test_files:
                        manfpath = path + ".manifest"
                        self.make_misc_files({
                            manfpath:
                                "file {0} mode=0644 owner=root group=bin "
                                "path=/foo{1}".format(path, path)})

                # publish
                url = self.dc.get_depot_url()
                self.pkgsend(url, "open multiple_mf@1.0")
                manifests = " ".join([path + ".manifest" for path in test_files])
                self.pkgsend(url, "include " + manifests)
                self.pkgsend(url, "close")

                # Finally, verify that both files were published.
                self.image_create(url)
                for path in test_files:
                        self.pkg("contents -r -H -o action.raw -t file multiple_mf |"
                            " grep {0}".format(path))
                self.image_destroy()

        def test_17_include_errors(self):
                """Verify that pkgsend include handles error conditions
                gracefully."""

                url = self.dc.get_depot_url()

                # Start a transaction.
                self.pkgsend(url, "open foo@1.0")

                # Verify no such include file handled.
                self.pkgsend(url, "include nosuchfile", exit=1)

                # Verify files with invalid content handled.
                misc = self.make_misc_files({
                    "invalid": "!%^$%^@*&$ bobcat",
                    "empty": "",
                })
                self.pkgsend(url, "include {0}".format(" ".join(misc)), exit=1)

        def test_18_broken_sysv_dir(self):
                """ A SVR4 directory-format package containing class action
                scripts fails to be imported or is generated with errors"""
                rootdir = self.test_root
                self.create_sysv_package(rootdir, self.sysv_classes_prototype,
                    self.sysv_contents)
                url = self.dc.get_depot_url()

                self.pkgsend(url, "open nopkg@1.0")
                self.pkgsend(url, "import {0}".format(os.path.join(rootdir, "nopkg")),
                    exit=1)
                self.check_sysv_scripting(self.errout)

                self.pkgsend(url, "generate {0}".format(os.path.join(rootdir, "nopkg")),
                    exit=1)
                self.check_sysv_scripting(self.errout)
                self.check_sysv_parameters(self.output)

        def test_19_broken_sysv_datastream(self):
                """ A SVR4 datastream package containing class action scripts
                fails to be imported or is generated with errors"""
                rootdir = self.test_root
                self.create_sysv_package(rootdir, self.sysv_classes_prototype,
                    self.sysv_contents)
                self.cmdline_run("pkgtrans -s {0} {1} nopkg".format(rootdir,
                        os.path.join(rootdir, "nopkg.pkg")), coverage=False)

                url = self.dc.get_depot_url()

                def check_errors(err):
                        self.assertTrue('ERROR: class action script used in nopkg: foobar/baz belongs to "myclass" class' in err)
                        self.assertTrue("ERROR: script present in nopkg: myclass" in err)
                        self.assertTrue("ERROR: script present in nopkg: postinstall" in err)

                self.pkgsend(url, "open nopkg@1.0")
                self.pkgsend(url, "import {0}".format(os.path.join(rootdir, "nopkg.pkg")),
                    exit=1)
                self.check_sysv_scripting(self.errout)

                self.pkgsend(url, "generate {0}".format(os.path.join(rootdir,
                    "nopkg.pkg")), exit=1)
                self.check_sysv_scripting(self.errout)
                self.check_sysv_parameters(self.output)

        def check_sysv_scripting(self, err):
                """Verify we've reported any class action or install scripts"""
                self.assertTrue('ERROR: class action script used in nopkg: foobar/baz belongs to "myclass" class' in err)
                self.assertTrue("ERROR: script present in nopkg: myclass" in err)
                self.assertTrue("ERROR: script present in nopkg: postinstall" in err)

        def check_sysv_parameters(self, output):
                """Verify we've automatically converted some pkginfo parameters
                """
                self.assertTrue(
                    "set name=pkg.description value=\"This is a sample package\""
                    in output)
                self.assertTrue("set name=pkg.summary value=\"No package\""
                    in output)
                self.assertTrue("set name=pkg.send.convert.pkg-contents value=bobcat"
                    in output)
                # this pkginfo parameter should be ignored
                self.assertTrue("rstate" not in output)

        def test_20_multi_pkg_bundle(self):
                """Verify we return an error for a multi-package datastream."""

                rootdir = self.test_root
                self.create_sysv_package(rootdir, self.sysv_classes_prototype,
                    self.sysv_contents)
                self.create_sysv_package(rootdir, self.sysv_prototype,
                    self.sysv_contents, pkginfo_contents=self.sysv_pkginfo_2)
                url = self.dc.get_depot_url()

                self.cmdline_run("pkgtrans -s {0} {1} nopkg nopkgtwo".format(rootdir,
                    os.path.join(rootdir, "nopkg.pkg")), coverage=False)
                self.pkgsend(url, "generate {0}".format(os.path.join(rootdir,
                    "nopkg.pkg")), exit=1)
                self.assertTrue("Multi-package datastreams are not supported." in
                    self.errout)

        def test_21_uri_paths(self):
                """Verify that a repository path with characters that must be
                URI-encoded or that are can be created and used with pkgsend."""

                for name in ("a%3A%2Fb", "a:b"):
                        rpath = os.path.join(self.test_root, name)
                        self.pkgsend(rpath, "create-repository "
                            "--set-property publisher.prefix=test")

                        self.pkgsend(rpath, "open pkg://test/foo@1.0")
                        self.pkgsend(rpath, "close")

                        # This will fail if the repository wasn't created with
                        # the expected name.
                        shutil.rmtree(rpath)

        def __test_publish(self, dir_1, dir_2, mfpath):
                dhurl = self.dc.get_depot_url()
                # -s may be specified either as a global option or as a local
                # option for the publish subcommand.
                self.pkgsend("", "-s {0} publish -d {1} -d {2} < {3}".format(dhurl,
                    dir_1, dir_2, mfpath))

                self.image_create(dhurl)
                self.pkg("install testmultipledirs")
                self.pkg("list -vH testmultipledirs@1.0")
                self.assertTrue("testmultipledirs@1.0" in self.output)

                self.pkg("verify")
                self.image_destroy()

                self.pkgsend("", "publish -s {0} -d {1} -d {2} < {3}".format(dhurl,
                    dir_1, dir_2, mfpath))

                self.image_create(dhurl)
                self.pkg("install testmultipledirs")
                self.pkg("verify")
                self.image_destroy()

        def test_22_publish(self):
                """Verify that pkgsend publish works as expected."""

                rootdir = self.test_root
                dir_1 = os.path.join(rootdir, "dir_1")
                dir_2 = os.path.join(rootdir, "dir_2")
                os.mkdir(dir_1)
                os.mkdir(dir_2)
                open(os.path.join(dir_1, "A"), "w").close()
                open(os.path.join(dir_2, "B"), "w").close()
                mfpath = os.path.join(rootdir, "manifest_test")
                with open(mfpath, "w") as mf:
                        mf.write("""file NOHASH mode=0755 owner=root group=bin path=/A
                            file NOHASH mode=0755 owner=root group=bin path=/B
                            set name=pkg.fmri value=testmultipledirs@1.0,5.10
                            """)
                self.__test_publish(dir_1, dir_2, mfpath)

                # Verify that older logic for pkgsend publish works.
                self.dc.stop()
                self.dc.set_disable_ops(["manifest/1"])
                self.dc.start()
                self.__test_publish(dir_1, dir_2, mfpath)
                self.dc.unset_disable_ops()

        def test_23_pkgsend_no_version(self):
                """Verify that FMRI without version cannot be specified."""

                rootdir = self.test_root
                dir_1 = os.path.join(rootdir, "dir_1")
                os.mkdir(dir_1)
                open(os.path.join(dir_1, "A"), "w").close()
                mfpath = os.path.join(rootdir, "manifest_test")
                with open(mfpath, "w") as mf:
                        mf.write("""file NOHASH mode=0755 owner=root group=bin path=/A
                            set name=pkg.fmri value=testnoversion
                            """)

                dhurl = self.dc.get_depot_url()
                self.pkgsend("", "-s {0} publish -d {1} < {2}".format(dhurl,
                    dir_1, mfpath), exit=1)

        def test_24_pkgsend_publish_payloaded_link(self):
                """Verify that publishing a manifest with a link with a payload
                doesn't traceback."""

                mfpath = os.path.join(self.test_root, "foo.p5m")
                with open(mfpath, "w") as mf:
                        mf.write("""set name=pkg.fmri value=foo@1
link payload-pathname path=/usr/bin/foo target=bar""")
                self.pkgsend("", "-s {0} publish {1}".format(
                    self.dc.get_depot_url(), mfpath), exit=1)
                self.pkgsend("", "-s {0} publish {1}".format(
                    self.dc.get_repo_url(), mfpath), exit=1)
                with open(mfpath, "w") as mf:
                        mf.write("""set name=pkg.fmri value=foo@1
dir path=/usr/bin/foo target=bar hash=payload-pathname""")
                self.pkgsend("", "-s {0} publish {1}".format(
                    self.dc.get_depot_url(), mfpath), exit=1)
                self.pkgsend("", "-s {0} publish {1}".format(
                    self.dc.get_repo_url(), mfpath), exit=1)

        def test_25_pkgsend_publish_nohash_license(self):
                """Verify that publishing a manifest with hash attribute
                missing for license action doesn't traceback"""

                durl = self.dc.get_depot_url()
                # Should fail because hash attribute is missing.
                self.pkgsend_bulk(durl,
                    """open foo@1.0
                    add license license=copyright
                    close""", exit=1)

        def test_26_pkgsend_multihash(self):
                """Tests that when publishing packages with mutiple hashes,
                we only overwrite those hashes if we're in multi-hash mode
                and only if they match the hash attributes we know how to
                compute, other attributes are left alone."""

                self.base_26_pkgsend_multihash("sha256")

        def base_26_pkgsend_multihash(self, hash_alg):
                # we use a file:// URI rather than the repo URI so we don't have
                # to worry about starting the depot in SHA-2 mode. Other tests
                # in the test suite ensure SHA-2 publication is working over
                # HTTP.
                furi = self.dc.get_repo_url()
                mfpath = os.path.join(self.test_root, "pkgsend_multihash.mf")
                payload = self.make_misc_files(["pkgsend_multihash"])[0]

                with open(mfpath, "w") as mf:
                        mf.write("""
set name=pkg.fmri value=pkg:/multihash@1.0
file {0} path=/foo owner=root group=sys mode=0644 pkg.hash.{1}=spaghetti \
    pkg.hash.rot13=caesar
""".format(payload, hash_alg))
                self.pkgsend("", "-s {0} publish {1}".format(furi, mfpath))
                self.image_create(furi)
                self.pkg("contents -rm multihash")
                self.assertTrue("pkg.hash.{0}=spaghetti".format(
                    hash_alg) in self.output)

                self.pkgsend("", "-s {0} publish {1}".format(furi, mfpath),
                    debug_hash="sha1+{0}".format(hash_alg))
                self.pkg("refresh")

                self.pkg("contents -rm multihash")
                self.assertTrue("pkg.hash.{0}=spaghetti".format(hash_alg)
                    not in self.output)
                self.assertTrue("pkg.hash.rot13=caesar" in self.output)

        def test_27_ownership(self):
                """Test whether the ownership of the file will change if the
                ownership flag is set during the manifest generation."""

                rootdir = self.test_root
                src_dir = os.path.join(rootdir, "foo")
                url = self.dc.get_depot_url()

                # Build a file tree under each source directory to test
                # import and generate functionality.  Tree should look like:
                #   src-foo/
                #       file-foo
                #       dir-foo/
                #           subfile-foo
                #           subdir-foo/
                #               subdirfile-foo
                cwd = os.getcwd()
                # Final component used as part of name for all entries.
                name = os.path.basename(src_dir)

                # File at top level in source directory.
                top_file = os.path.join(src_dir, "file-{0}".format(name))
                self.make_misc_files(os.path.relpath(top_file, src_dir),
                    prefix=name, mode=0o644)

                top_dir = os.path.join(src_dir, "dir-{0}".format(name))
                os.mkdir(top_dir, 0o755)

                # File in top_dir.
                top_dir_file = os.path.join(top_dir,
                    "subfile-{0}".format(name))
                self.make_misc_files(os.path.relpath(top_dir_file,
                    src_dir), prefix=name, mode=0o444)

                # Directory in top_dir.
                sub_dir = os.path.join(top_dir, "subdir-{0}".format(name))
                os.mkdir(sub_dir, 0o750)

                # File in sub_dir.
                sub_dir_file = os.path.join(sub_dir,
                    "subdirfile-{0}".format(name))
                self.make_misc_files(os.path.relpath(sub_dir_file,
                    src_dir), prefix=name, mode=0o400)

                # Change ownership.
                owner_id, group_id =  pkg5unittest.get_su_wrap_user(uid_gid = True)
                for root, folders, files in os.walk(src_dir):
                        os.chown(root, owner_id, group_id)
                        for f in files:
                                os.chown(os.path.join(root,f), owner_id,
                                    group_id)

                rc, actual = self.pkgsend(url, "generate -u {0}".format(src_dir))

                # Pre-generated result used for package validation.
                owner = pwd.getpwuid(owner_id).pw_name
                group = grp.getgrgid(group_id).gr_name
                expected = """\
dir group={group} mode=0755 owner={owner} path=dir-foo
file file-foo group={group} mode=0644 owner={owner} path=file-foo
dir group={group} mode=0750 owner={owner} path=dir-foo/subdir-foo
file dir-foo/subfile-foo group={group} mode=0444 owner={owner} path=dir-foo/subfile-foo
file dir-foo/subdir-foo/subdirfile-foo group={group} mode=0400 owner={owner} \
path=dir-foo/subdir-foo/subdirfile-foo\n""".format(
                        owner=owner, group=group)

                self.assertEqualDiff(self.reduceSpaces(expected),
                    self.reduceSpaces(actual))

class TestPkgsendHardlinks(pkg5unittest.CliTestCase):

        def test_bundle_dir_hardlinks(self):
                """Verify that hardlink targeting works correctly."""

                rootdir = os.path.join(self.test_root, "bundletest")

                def diffmf(src, dst):
                        added, changed, removed = src.difference(dst)

                        # Strip all attributes from file actions other than path
                        for aa in added + changed + removed:
                                for a in aa:
                                        if a and a.name in ("file", "dir"):
                                                a.attrs = {
                                                    "path": a.attrs["path"]
                                                }

                        # Re-do the difference to eliminate actions, if the
                        # above changed anything:
                        added, changed, removed = src.difference(dst)

                        res = []
                        for a1, a2 in added:
                                res.append("+ {0}".format(a2))
                        for a1, a2 in changed:
                                res.append("- {0}".format(a1))
                                res.append("+ {0}".format(a2))
                        for a1, a2 in removed:
                                res.append("- {0}".format(a1))

                        return "\n".join(res)

                def dirlist(dir):
                        l = [dir]
                        while dir:
                                dir = os.path.dirname(dir)
                                l.append(dir)
                        return l

                def do_test(*pathnames):
                        self.debug("=" * 70)
                        self.debug("Testing: {0}".format(pathnames,))
                        for i in range(len(pathnames)):
                                l = list(pathnames)
                                p = l.pop(i)
                                do_test_one(p, l)

                def do_test_one(target, links):
                        self.debug("-" * 70)
                        self.debug("Testing: {0} {1}".format(target, links))
                        tpath = self.make_misc_files(target, rootdir)[0]
                        expected_mf = "file {0} path={1}\n".format(target, target)
                        dirs = set()

                        # Iterate over the links, creating them and adding them
                        # to the expected manifest.
                        for link in links:
                                lpath = os.path.join(rootdir, link)
                                ldir = os.path.dirname(lpath)
                                if not os.path.exists(ldir):
                                        os.makedirs(ldir)
                                os.link(tpath, lpath)
                                expected_mf += "hardlink path={0} target={1}\n".format(
                                    link, os.path.relpath(tpath, ldir))
                                # Add the directories implied by the link
                                dirs.update(dirlist(os.path.dirname(link)))

                        # Add the directories implied by the target
                        dirs.update(dirlist(os.path.dirname(target)))
                        dirs.discard(""); dirs.discard(".")
                        for d in dirs:
                                expected_mf += "dir path={0}\n".format(d)

                        self.debug("EXPECTED:\n" + expected_mf + 40 * "=")

                        # Generate the manifest
                        targetargs = "".join(("--target {0} ".format(t) for t in
                            [target]))
                        rc, out = self.pkgsend(command="generate " +
                            targetargs + rootdir)

                        # Create manifest objects
                        genmf = manifest.Manifest()
                        genmf.set_content(out)
                        cmpmf = manifest.Manifest()
                        cmpmf.set_content(expected_mf)

                        # Run the differ
                        diffs = diffmf(genmf, cmpmf)

                        # Print and fail if there are any diffs
                        if diffs:
                                self.debug(diffs)
                                self.fail("YOU FAIL")

                        # Remove the tree before starting over
                        shutil.rmtree(rootdir)

                # Target and link in the same directory
                do_test("f1", "f2")

                # Target and link in the same directory, one level down
                do_test("d1/f1", "d1/f2")

                # Target and link in different directories, at the same level
                do_test("d1/f1", "d2/f2")

                # Target and link at different levels
                do_test("d1/f1", "f2")

                # Just the reverse
                do_test("f1", "d1/f2")

                # Target and link at different levels, one level lower
                do_test("d1/f1", "d2/d3/f2")

                # Target and link at different levels, two levels apart
                do_test("d1/f1", "d2/d3/d4/f2")

                # Two links in the same directory as the target
                do_test("f1", "f2", "f3")
                do_test("d1/f1", "d1/f2", "f3")
                do_test("d1/f1", "d1/f2", "d2/f3")


class TestPkgsendHTTPS(pkg5unittest.HTTPSTestClass):

        misc_files = ["tmp/empty", "tmp/verboten"]

        def setUp(self):
                pub = "test"

                pkg5unittest.HTTPSTestClass.setUp(self, [pub],
                    start_depots=True)

                self.url = self.ac.url + "/{0}".format(pub)
                self.make_misc_files(self.misc_files)
                #set permissions of tmp/verboten to make it non-readable
                self.verboten = os.path.join(self.test_root, "tmp/verboten")
                os.system("chmod 600 {0}".format(self.verboten))

        def test_01_basics(self):
                """Test that publishing to an SSL-secured repo works"""

                self.ac.start()

                rootdir = self.test_root
                dir_1 = os.path.join(rootdir, "dir_1")
                os.mkdir(dir_1)
                open(os.path.join(dir_1, "A"), "w").close()
                open(os.path.join(dir_1, "B"), "w").close()
                mfpath = os.path.join(rootdir, "manifest_test")
                with open(mfpath, "w") as mf:
                        mf.write("""file NOHASH mode=0755 owner=root group=bin path=/A
                            file NOHASH mode=0755 owner=root group=bin path=/B
                            set name=pkg.fmri value=httpstest@1.0,5.10
                            """)

                arg_dict = {
                    "cert": os.path.join(self.cs_dir, self.get_cli_cert("test")),
                    "key": os.path.join(self.keys_dir, self.get_cli_key("test")),
                    "url": self.url,
                    "dir": dir_1,
                    "mani": mfpath,
                    "empty": os.path.join(self.test_root, "tmp/empty"),
                    "noexist": os.path.join(self.test_root, "octopus"),
                    "verboten": self.verboten,

                }

                # We need an image for seed_ta_dir() to work.
                # TODO: there might be a cleaner way of doing this
                self.image_create()
                # Add the trust anchor needed to verify the server's identity.
                self.seed_ta_dir("ta7")

                # Try to publish a simple package to SSL-secured repo
                self.pkgsend(self.url, "publish --key {key} --cert {cert} "
                    "-d {dir} {mani}".format(**arg_dict))

                # Try to publish a simple package to SSL-secured repo without
                # prvoviding certs (should fail).
                self.pkgsend(self.url, "publish -d {dir} {mani}".format(**arg_dict),
                    exit=1)

                # Make sure we don't traceback when credential files are invalid
                # Certificate option missing
                self.pkgsend(self.url, "publish --key {key} "
                    "-d {dir} {mani}".format(**arg_dict), exit=1)

                # Key option missing
                self.pkgsend(self.url, "publish --cert {cert} "
                    "-d {dir} {mani}".format(**arg_dict), exit=1)

                # Certificate not found
                self.pkgsend(self.url, "publish --key {key} "
                    "--cert {noexist} -d {dir} {mani}".format(**arg_dict), exit=1)

                # Key not found
                self.pkgsend(self.url, "publish --key {noexist} "
                    "--cert {cert} -d {dir} {mani}".format(**arg_dict), exit=1)

                # Certificate is empty file
                self.pkgsend(self.url, "publish --key {key} --cert {empty} "
                    "-d {dir} {mani}".format(**arg_dict), exit=1)

                # Key is empty file
                self.pkgsend(self.url, "publish --key {empty} "
                    "--cert {cert} -d {dir} {mani}".format(**arg_dict), exit=1)

                # No permissions to read certificate
                self.pkgsend(self.url, "publish --key {key} "
                    "--cert {verboten} -d {dir} {mani}".format(**arg_dict),
                    su_wrap=True, exit=1)

                # No permissions to read key
                self.pkgsend(self.url, "publish --key {verboten} "
                    "--cert {cert} -d {dir} {mani}".format(**arg_dict),
                    su_wrap=True, exit=1)


if __name__ == "__main__":
        unittest.main()

# Vim hints
# vim:ts=8:sw=8:et:fdm=marker
