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

#
# Copyright (c) 2008, 2016, Oracle and/or its affiliates. All rights reserved.
#

from __future__ import print_function
from . import testutils
if __name__ == "__main__":
        testutils.setup_environment("../../../proto")
import pkg5unittest

import copy
import hashlib
import os
import shutil
import six
import sys
import unittest
from six.moves.urllib.error import HTTPError
from six.moves.urllib.request import urlopen

import pkg.catalog as catalog
import pkg.client.pkgdefs as pkgdefs
import pkg.fmri as fmri
import pkg.indexer as indexer
import pkg.portable as portable

class TestPkgSearchBasics(pkg5unittest.SingleDepotTestCase):

        example_pkg10 = """
            open example_pkg@1.0,5.11-0
            add dir mode=0755 owner=root group=bin path=/bin
            add dir mode=0755 owner=root group=bin path=/bin/example_dir
            add dir mode=0755 owner=root group=bin path=/usr/lib/python2.7/vendor-packages/OpenSSL
            add file tmp/example_file mode=0555 owner=root group=bin path=/bin/example_path
            add set name=com.sun.service.incorporated_changes value="6556919 6627937"
            add set name=com.sun.service.random_test value=42 value=79
            add set name=com.sun.service.bug_ids value="4641790 4725245 4817791 4851433 4897491 4913776 6178339 6556919 6627937"
            add set name=com.sun.service.keywords value="sort null -n -m -t sort 0x86 separator"
            add set name=com.sun.service.info_url value=http://service.opensolaris.com/xml/pkg/SUNWcsu@0.5.11,5.11-1:20080514I120000Z
            add set description='FOOO bAr O OO OOO'
            add set name='weirdness' value='] [ * ?'
            close """

        example_pkg11 = """
            open example_pkg@1.1,5.11-0
            add dir mode=0755 owner=root group=bin path=/bin
            add file tmp/example_file mode=0555 owner=root group=bin path=/bin/example_path11
            close """

        incorp_pkg10 = """
            open incorp_pkg@1.0,5.11-0
            add depend fmri=example_pkg@1.0,5.11-0 type=incorporate
            close """

        nover_incorp_pkg10 = """
            open nover_incorp_pkg@1.0,5.11-0
            add depend fmri=incorp_pkg type=incorporate
            close """

        dup_lines_pkg10 = """
            open dup_lines@1.0,5.11-0
            add set name=com.sun.service.incorporated_changes value="aa abc a a"
            add set name=com.sun.service.bug_ids value="z x y a abc bb"
            add set name=com.sun.service.keywords value="z a abc"
            close """

        fat_pkg10 = """
open fat@1.0,5.11-0
add set name=variant.arch value=sparc value=i386
add set name=description value="i386 variant" variant.arch=i386
add set name=description value="sparc variant" variant.arch=sparc
close """

        bogus_pkg10 = """
set name=pkg.fmri value=pkg:/bogus_pkg@1.0,5.11-0:20090326T233451Z
set name=description value=""validation with simple chains of constraints ""
set name=pkg.description value="pseudo-hashes as arrays tied to a "type" (list of fields)"
depend fmri=XML-Atom-Entry
set name=com.sun.service.incorporated_changes value="6556919 6627937"
"""
        bogus_fmri = fmri.PkgFmri("bogus_pkg@1.0,5.11-0:20090326T233451Z")

        empty_attr_pkg10 = """
open empty@1.0,5.11-0
add set name=pkg.fmri value=pkg:/empty@1.0 attr1=''
add set name=empty_set value=''
add depend fmri=example_pkg@1.0 type=optional attr2=''
add file tmp/group attr3='' mode=0555 owner=root group=bin path=etc/group
add file tmp/passwd attr3='' mode=0555 owner=root group=bin path=etc/passwd
add file tmp/shadow attr3='' mode=0555 owner=root group=bin path=etc/shadow
add dir mode=0755 attr4='' owner=root group=bin path=/empty_dir
add group groupname=foo gid=87 attr5=''
add user username=fozzie group=foo uid=123 attr6=''
add link target=bin/example_path path=link attr7=''
close
"""

        empty_attr_pkg10_templ = """
open empty{ver}@1.0,5.11-0
add set name=pkg.fmri value=pkg:/empty{ver}@1.0 attr1=''
add set name=empty_set value=''
add depend fmri=example_pkg@1.0 type=optional attr2=''
add file tmp/group attr3='' mode=0555 owner=root group=bin path=etc/group{ver}
add file tmp/passwd attr3='' mode=0555 owner=root group=bin path=etc/passwd{ver}
add file tmp/shadow attr3='' mode=0555 owner=root group=bin path=etc/shadow{ver}
add dir mode=0755 attr4='' owner=root group=bin path=/empty_dir
add group groupname=foo{ver} gid={ver} attr5=''
add user username=fozzie{ver} group=foo uid={ver} attr6=''
add link target=bin/example_path path=link attr7=''
close
"""

        headers = "INDEX ACTION VALUE PACKAGE\n"
        pkg_headers = "PACKAGE PUBLISHER\n"

        res_remote_path = set([
            headers,
            "basename   file      bin/example_path          pkg:/example_pkg@1.0-0\n"
        ])

        res_remote_case_sensitive = set([
            headers,
            "pkg.fmri        set        test/example_pkg pkg:/example_pkg@1.0-0\n"
        ])

        res_remote_bin = set([
            headers,
            "path       dir       bin                       pkg:/example_pkg@1.0-0\n"
        ])

        res_remote_openssl = set([
            headers,
            "basename   dir       usr/lib/python2.7/vendor-packages/OpenSSL pkg:/example_pkg@1.0-0\n"
        ])

        res_remote_bug_id = set([
            headers,
            "com.sun.service.bug_ids set       4641790 4725245 4817791 4851433 4897491 4913776 6178339 6556919 6627937                   pkg:/example_pkg@1.0-0\n"

        ])

        res_remote_inc_changes = set([
            headers,
            "com.sun.service.incorporated_changes set       6556919 6627937                   pkg:/example_pkg@1.0-0\n",
            "com.sun.service.bug_ids set       4641790 4725245 4817791 4851433 4897491 4913776 6178339 6556919 6627937                   pkg:/example_pkg@1.0-0\n"

        ])

        res_remote_random_test = set([
            headers,
            "com.sun.service.random_test set       42                        pkg:/example_pkg@1.0-0\n"
        ])

        res_remote_random_test_79 = set([
            headers,
            "com.sun.service.random_test set       79                        pkg:/example_pkg@1.0-0\n"
        ])

        res_remote_keywords = set([
            headers,
            "com.sun.service.keywords set       sort null -n -m -t sort 0x86 separator                 pkg:/example_pkg@1.0-0\n"
        ])

        res_remote_wildcard = set([
            headers,
            "basename   file      bin/example_path          pkg:/example_pkg@1.0-0\n",
            "basename   dir       bin/example_dir           pkg:/example_pkg@1.0-0\n",
            "pkg.fmri   set       test/example_pkg          pkg:/example_pkg@1.0-0\n"
        ])

        res_remote_glob = set([
            headers,
            "basename   file      bin/example_path          pkg:/example_pkg@1.0-0\n",
            "basename   dir       bin/example_dir           pkg:/example_pkg@1.0-0\n",
            "path       file      bin/example_path          pkg:/example_pkg@1.0-0\n",
            "path       dir       bin/example_dir           pkg:/example_pkg@1.0-0\n",
            "pkg.fmri   set       test/example_pkg          pkg:/example_pkg@1.0-0\n"
        ])

        res_remote_foo = set([
            headers,
            "description set       FOOO bAr O OO OOO                      pkg:/example_pkg@1.0-0\n"
        ])

        res_local_pkg = set([
            headers,
            "pkg.fmri       set        test/example_pkg              pkg:/example_pkg@1.0-0\n"
        ])

        res_local_path = copy.copy(res_remote_path)

        res_local_bin = copy.copy(res_remote_bin)

        res_local_bug_id = copy.copy(res_remote_bug_id)

        res_local_inc_changes = copy.copy(res_remote_inc_changes)

        res_local_random_test = copy.copy(res_remote_random_test)
        res_local_random_test_79 = copy.copy(res_remote_random_test_79)

        res_local_keywords = copy.copy(res_remote_keywords)

        res_local_wildcard = copy.copy(res_remote_wildcard)

        res_local_glob = copy.copy(res_remote_glob)

        res_local_foo = copy.copy(res_remote_foo)

        res_local_openssl = copy.copy(res_remote_openssl)

        # Results expected for degraded local search
        degraded_warning = set(["To improve, run 'pkg rebuild-index'.\n",
            'Search capabilities and performance are degraded.\n'])

        res_local_degraded_pkg = res_local_pkg.union(degraded_warning)

        res_local_degraded_path = res_local_path.union(degraded_warning)

        res_local_degraded_bin = res_local_bin.union(degraded_warning)

        res_local_degraded_bug_id = res_local_bug_id.union(degraded_warning)

        res_local_degraded_inc_changes = res_local_inc_changes.union(degraded_warning)

        res_local_degraded_random_test = res_local_random_test.union(degraded_warning)

        res_local_degraded_keywords = res_local_keywords.union(degraded_warning)

        res_local_degraded_openssl = res_local_openssl.union(degraded_warning)

        res_bogus_name_result = set([
            headers,
            'pkg.fmri       set       bogus_pkg                 pkg:/bogus_pkg@1.0-0\n'
        ])

        res_bogus_number_result = set([
            headers,
            'com.sun.service.incorporated_changes set       6556919 6627937                   pkg:/bogus_pkg@1.0-0\n'
        ])

        misc_files = {
            "tmp/example_file": "magic",
            "tmp/passwd": """\
root:x:0:0::/root:/usr/bin/bash
daemon:x:1:1::/:
bin:x:2:2::/usr/bin:
sys:x:3:3::/:
adm:x:4:4:Admin:/var/adm:
""",
            "tmp/group": """\
root::0:
other::1:root
bin::2:root,daemon
sys::3:root,bin,adm
adm::4:root,daemon
""",
            "tmp/shadow": """\
root:9EIfTNBp9elws:13817::::::
daemon:NP:6445::::::
bin:NP:6445::::::
sys:NP:6445::::::
adm:NP:6445::::::
""",
            }


        res_local_pkg_ret_pkg = set([
            pkg_headers,
            "pkg:/example_pkg@1.0-0\n"
        ])

        res_remote_pkg_ret_pkg = set([
            pkg_headers,
            "pkg:/example_pkg@1.0-0 test\n"
        ])

        res_remote_file = set([
            'path       file      bin/example_path          pkg:/example_pkg@1.0-0\n',
            'b40981aab75932c5b2f555f50769d878e44913d7 file      bin/example_path          pkg:/example_pkg@1.0-0\n',
            'hash                                     file   bin/example_path pkg:/example_pkg@1.0-0\n'
        ]) | res_remote_path


        res_remote_url = set([
             headers,
             'com.sun.service.info_url set       http://service.opensolaris.com/xml/pkg/SUNWcsu@0.5.11,5.11-1:20080514I120000Z pkg:/example_pkg@1.0-0\n'
        ])

        res_remote_path_extra = set([
             headers,
             'path       file      bin/example_path          pkg:/example_pkg@1.0-0\n',
             'basename   file      bin/example_path          pkg:/example_pkg@1.0-0\n',
             'b40981aab75932c5b2f555f50769d878e44913d7 file      bin/example_path          pkg:/example_pkg@1.0-0\n',
             'hash                                     file   bin/example_path pkg:/example_pkg@1.0-0\n'
        ])

        o_headers = \
            "ACTION.NAME ACTION.KEY PKG.NAME " \
            "PKG.SHORTFMRI SEARCH.MATCH " \
            "SEARCH.MATCH_TYPE MODE OWNER GROUP " \
            "ACTION.RAW PKG.PUBLISHER\n"

        o_results_no_pub = \
            "file bin/example_path example_pkg " \
            "pkg:/example_pkg@1.0-0 bin/example_path " \
            "basename 0555 root bin " \
            "file b40981aab75932c5b2f555f50769d878e44913d7 chash=6a4299897fca0c4d0d18870da29a0dc7ae23b79c group=bin mode=0555 owner=root path=bin/example_path pkg.csize=25 pkg.size=5\n"

        o_results = o_results_no_pub.rstrip() + " test\n"

        res_o_options_remote = set([o_headers, o_results])

        res_o_options_local = set([o_headers, o_results_no_pub])

        pkg_headers = "PKG.NAME PKG.SHORTFMRI PKG.PUBLISHER MODE"
        pkg_results_no_pub = "example_pkg pkg:/example_pkg@1.0-0"
        pkg_results = pkg_results_no_pub + " test"

        res_pkg_options_remote = set([pkg_headers, pkg_results])
        res_pkg_options_local = set([pkg_headers, pkg_results_no_pub])

        # Creating a query string in which the number of terms is > 100
        large_query = "a b c d e f g h i j k l m n o p q r s t u v w x y z" \
                      "a b c d e f g h i j k l m n o p q r s t u v w x y z" \
                      "a b c d e f g h i j k l m n o p q r s t u v w x y z" \
                      "a b c d e f g h i j k l m n o p q r s t u v w x y z" \
                      "a b c d e f g h i j k l m n o p q r s t u v w x y z" \
                      "a b c d e f g h i j k l m n o p q r s t u v w x y z"

        def setUp(self):
                # This test needs an actual depot for now.
                pkg5unittest.SingleDepotTestCase.setUp(self, start_depot=True)
                self.make_misc_files(self.misc_files)
                self.init_mem_setting = None

        def _check(self, proposed_answer, correct_answer):
                if correct_answer == proposed_answer:
                        return True
                if len(proposed_answer) == len(correct_answer) and \
                    sorted([p.strip().split() for p in proposed_answer]) == \
                    sorted([c.strip().split() for c in correct_answer]):
                        return True
                self.debug("Proposed Answer: " + str(proposed_answer))
                self.debug("Correct Answer : " + str(correct_answer))
                if isinstance(correct_answer, set) and \
                    isinstance(proposed_answer, set):
                        print("Missing: " + str(correct_answer - proposed_answer),
                            file=sys.stderr)
                        print("Extra  : " + str(proposed_answer - correct_answer),
                            file=sys.stderr)
                self.assertTrue(correct_answer == proposed_answer)

        def _search_op(self, remote, token, test_value, case_sensitive=False,
            return_actions=True, exit=0, su_wrap=False, prune_versions=True,
            headers=True):
                outfile = os.path.join(self.test_root, "res")
                if remote:
                        token = "-r " + token
                else:
                        token = "-l " + token
                if case_sensitive:
                        token = "-I " + token
                if return_actions:
                        token = "-a " + token
                else:
                        token = "-p " + token
                if not prune_versions:
                        token = "-f " + token
                if not headers:
                        token = "-H " + token
                self.pkg("search " + token + " > " + outfile, exit=exit)
                res_list = (open(outfile, "r")).readlines()
                self._check(set(res_list), test_value)

        def _run_remote_tests(self):
                # This should be possible now that the server automatically adds
                # FMRIs to manifests (during publication).
                self.pkg("search -a -r example_pkg")

                self._search_op(True, "example_path", self.res_remote_path)
                self._search_op(True, "':set:pkg.fmri:exAMple_pkg'",
                    self.res_remote_case_sensitive, case_sensitive=False)
                self._search_op(True, "'(example_path)'", self.res_remote_path)
                self._search_op(True, "'<exam*:::>'",
                    self.res_remote_pkg_ret_pkg)
                self._search_op(True, "'::com.sun.service.info_url:'",
                    self.res_remote_url)
                self._search_op(True, "':::e* AND *path'", self.res_remote_path)
                self._search_op(True, "'e* AND *path'", self.res_remote_path)
                self._search_op(True, "'<e*>'", self.res_remote_pkg_ret_pkg)
                self._search_op(True, "'<e*> AND <e*>'",
                    self.res_remote_pkg_ret_pkg)
                self._search_op(True, "'<e*> OR <e*>'",
                    self.res_remote_pkg_ret_pkg)
                self._search_op(True, "'<exam:::>'",
                    self.res_remote_pkg_ret_pkg)
                self._search_op(True, "'exam:::e*path'", self.res_remote_path)
                self._search_op(True, "'exam:::e*path AND e*:::'",
                    self.res_remote_path)
                self._search_op(True, "'e*::: AND exam:::*path'",
                    self.res_remote_path_extra)
                self._search_op(True, "'example*'", self.res_remote_wildcard)
                self._search_op(True, "/bin", self.res_remote_bin)
                self._search_op(True, "4851433", self.res_remote_bug_id)
                self._search_op(True, "'<4851433> AND <4725245>'",
                    self.res_remote_pkg_ret_pkg)
                self._search_op(True, "4851433 AND 4725245",
                    self.res_remote_bug_id)
                self._search_op(True, "4851433 AND 4725245 OR example_path",
                    self.res_remote_bug_id)
                self._search_op(True, "'4851433 AND (4725245 OR example_path)'",
                    self.res_remote_bug_id)
                self._search_op(True, "'(4851433 AND 4725245) OR example_path'",
                    self.res_remote_bug_id | self.res_remote_path)
                self._search_op(True, "4851433 OR 4725245",
                    self.res_remote_bug_id | self.res_remote_bug_id)
                self._search_op(True, "6556919", self.res_remote_inc_changes)
                self._search_op(True, "'6556?19'", self.res_remote_inc_changes)
                self._search_op(True, "42", self.res_remote_random_test)
                self._search_op(True, "79", self.res_remote_random_test_79)
                self._search_op(True, "separator", self.res_remote_keywords)
                self._search_op(True, "'\"sort 0x86\"'",
                    self.res_remote_keywords)
                self._search_op(True, "'*example*'", self.res_remote_glob)
                self._search_op(True, "fooo", self.res_remote_foo)
                self._search_op(True, "'fo*'", self.res_remote_foo)
                self._search_op(True, "bar", self.res_remote_foo)
                self._search_op(True, "openssl", self.res_remote_openssl)
                self._search_op(True, "OPENSSL", self.res_remote_openssl)
                self._search_op(True, "OpEnSsL", self.res_remote_openssl)
                self._search_op(True, "'OpEnS*'", self.res_remote_openssl)

                # Verify that search will work for an unprivileged user even if
                # the download directory doesn't exist.
                img = self.get_img_api_obj().img
                cache_dirs = [
                    path
                    for path, readonly, pub, layout in img.get_cachedirs()
                ]
                for path in cache_dirs:
                        shutil.rmtree(path, ignore_errors=True)
                        self.assertFalse(os.path.exists(path))
                self._search_op(True, "'fo*'", self.res_remote_foo,
                    su_wrap=True)

                # These tests are included because a specific bug
                # was found during development. This prevents regression back
                # to that bug. Exit status of 1 is expected because the
                # token isn't in the packages.
                self.pkg("search -a -r a_non_existent_token", exit=1)
                self.pkg("search -a -r a_non_existent_token", exit=1)

                self.pkg("search -a -r '42 AND 4641790'", exit=1)
                self.pkg("search -a -r '<e*> AND e*'", exit=1)
                self.pkg("search -a -r 'e* AND <e*>'", exit=1)
                self.pkg("search -a -r '<e*> OR e*'", exit=1)
                self.pkg("search -a -r 'e* OR <e*>'", exit=1)
                self._search_op(True, "pkg:/example_path", self.res_remote_path)
                self.pkg("search -a -r -I ':set:pkg.fmri:exAMple_pkg'", exit=1)
                self.assertTrue(self.errout == "" )

                self.pkg("search -a -r {0}".format(self.large_query), exit=1)
                self.assertTrue(self.errout != "")

        def _run_local_tests(self):
                outfile = os.path.join(self.test_root, "res")

                # This finds something because the client side
                # manifest has had the name of the package inserted
                # into it.

                self._search_op(False, "example_pkg", self.res_local_pkg)
                self._search_op(False, "'(example_pkg)'", self.res_local_pkg)
                self._search_op(False, "'<exam*:::>'",
                    self.res_local_pkg_ret_pkg)
                self._search_op(False, "'::com.sun.service.info_url:'",
                    self.res_remote_url)
                self._search_op(False, "':::e* AND *path'",
                    self.res_remote_path)
                self._search_op(False, "'e* AND *path'", self.res_local_path)
                self._search_op(False, "'<e*>'", self.res_local_pkg_ret_pkg)
                self._search_op(False, "'<e*> AND <e*>'",
                    self.res_local_pkg_ret_pkg)
                self._search_op(False, "'<e*> OR <e*>'",
                    self.res_local_pkg_ret_pkg)
                self._search_op(False, "'<exam:::>'",
                    self.res_local_pkg_ret_pkg)
                self._search_op(False, "'exam:::e*path'", self.res_remote_path)
                self._search_op(False, "'exam:::e*path AND e:::'",
                    self.res_remote_path)
                self._search_op(False, "'e::: AND exam:::e*path'",
                    self.res_remote_path_extra)
                self._search_op(False, "'example*'", self.res_local_wildcard)
                self._search_op(False, "/bin", self.res_local_bin)
                self._search_op(False, "4851433", self.res_local_bug_id)
                self._search_op(False, "'<4851433> AND <4725245>'",
                    self.res_local_pkg_ret_pkg)
                self._search_op(False, "4851433 AND 4725245",
                    self.res_remote_bug_id)
                self._search_op(False, "4851433 AND 4725245 OR example_path",
                    self.res_remote_bug_id)
                self._search_op(False,
                    "'4851433 AND (4725245 OR example_path)'",
                    self.res_remote_bug_id)
                self._search_op(False,
                    "'(4851433 AND 4725245) OR example_path'",
                    self.res_remote_bug_id | self.res_local_path)
                self._search_op(False, "4851433 OR 4725245",
                    self.res_remote_bug_id | self.res_remote_bug_id)
                self._search_op(False, "6556919", self.res_local_inc_changes)
                self._search_op(False, "'65569??'", self.res_local_inc_changes)
                self._search_op(False, "42", self.res_local_random_test)
                self._search_op(False, "79", self.res_local_random_test_79)
                self._search_op(False, "separator", self.res_local_keywords)
                self._search_op(False, "'\"sort 0x86\"'",
                    self.res_remote_keywords)
                self._search_op(False, "'*example*'", self.res_local_glob)
                self._search_op(False, "fooo", self.res_local_foo)
                self._search_op(False, "'fo*'", self.res_local_foo)
                self._search_op(False, "bar", self.res_local_foo)
                self._search_op(False, "openssl", self.res_local_openssl)
                self._search_op(False, "OPENSSL", self.res_local_openssl)
                self._search_op(False, "OpEnSsL", self.res_local_openssl)
                self._search_op(False, "'OpEnS*'", self.res_local_openssl)

                # These tests are included because a specific bug
                # was found during development. These tests prevent regression
                # back to that bug. Exit status of 1 is expected because the
                # token isn't in the packages.
                self.pkg("search -a -l a_non_existent_token", exit=1)
                self.pkg("search -a -l a_non_existent_token", exit=1)
                self.pkg("search -a -l '42 AND 4641790'", exit=1)
                self.pkg("search -a -l '<e*> AND e*'", exit=1)
                self.pkg("search -a -l 'e* AND <e*>'", exit=1)
                self.pkg("search -a -l '<e*> OR e*'", exit=1)
                self.pkg("search -a -l 'e* OR <e*>'", exit=1)
                self._search_op(False, "pkg:/example_path", self.res_local_path)

                self.pkg("search -a -l {0}".format(self.large_query), exit=1)
                self.assertTrue(self.errout != "")

        def _run_local_empty_tests(self):
                self.pkg("search -a -l example_pkg", exit=1)
                self.pkg("search -a -l example_path", exit=1)
                self.pkg("search -a -l 'example*'", exit=1)
                self.pkg("search -a -l /bin", exit=1)

        def _run_remote_empty_tests(self):
                self.pkg("search -a -r example_pkg", exit=1)
                self.pkg("search -a -r example_path", exit=1)
                self.pkg("search -a -r 'example*'", exit=1)
                self.pkg("search -a -r /bin", exit=1)
                self.pkg("search -a -r '*unique*'", exit=1)

        def _get_index_dirs(self):
                index_dir = self.get_img_api_obj().img.index_dir
                index_dir_tmp = os.path.join(index_dir, "TMP")
                return index_dir, index_dir_tmp

        def pkgsend_bulk(self, durl, pkg):
                # Ensure indexing is performed for every published package.
                plist = pkg5unittest.SingleDepotTestCase.pkgsend_bulk(self,
                    durl, pkg, refresh_index=True)
                self.wait_repo(self.dc.get_repodir())
                return plist

        def test_pkg_search_cli(self):
                """Test search cli options."""

                durl = self.dc.get_depot_url()
                self.pkgsend_bulk(durl, self.example_pkg10)
                self.image_create(durl)

                self.pkg("search", exit=2)

                # Bug 1541
                self.pkg("search -s {0} bin".format("httP" + durl[4:]))
                self.pkg("search -s ftp://pkg.opensolaris.org:88 bge", exit=1)

                # Testing interaction of -o and -p options
                self.pkgsend_bulk(durl, self.example_pkg10)
                self.pkg("search -o action.name -p pkg", exit=2)
                self.pkg("search -o action.name -a '<pkg>'", exit=1)
                self.pkg("search -o action.name -a '<example_path>'", exit=2)
                self.pkg("search -o action.key -p pkg", exit=2)
                self.pkg("search -o action.key -a '<pkg>'", exit=1)
                self.pkg("search -o action.key -a '<example_path>'", exit=2)
                self.pkg("search -o search.match -p pkg", exit=2)
                self.pkg("search -o search.match -a '<pkg>'", exit=1)
                self.pkg("search -o search.match -a '<example_path>'", exit=2)
                self.pkg("search -o search.match_type -p pkg", exit=2)
                self.pkg("search -o search.match_type -a '<pkg>'", exit=1)
                self.pkg("search -o search.match_type -a '<example_path>'",
                    exit=2)
                self.pkg("search -o action.foo -a pkg", exit=2)

        def test_remote(self):
                """Test remote search."""
                # Need to retain to check that default search does remote, not
                # local search, and that -r and -s work as expected
                durl = self.dc.get_depot_url()
                self.pkgsend_bulk(durl, self.example_pkg10)

                self.image_create(durl)
                self._run_remote_tests()
                self._search_op(True, "':file::'", self.res_remote_file)
                self.pkg("search '*'")
                self.pkg("search -r '*'")
                self.pkg("search -s {0} '*'".format(durl))
                self.pkg("search -l '*'", exit=1)

        def test_local_0(self):
                """Install one package, and run the search suite."""
                # Need to retain that -l works as expected
                durl = self.dc.get_depot_url()
                self.pkgsend_bulk(durl, self.example_pkg10)

                self.image_create(durl)

                self.pkg("install example_pkg")

                self._run_local_tests()

        def test_bug_1873(self):
                """Test to see if malformed actions cause tracebacks during
                indexing for client or server."""
                # Can't be moved to api search since this is to test for
                # tracebacks
                durl = self.dc.get_depot_url()
                depotpath = self.dc.get_repodir()
                server_manifest_path = os.path.join(depotpath, "publisher",
                    "test", "pkg", self.bogus_fmri.get_dir_path())
                os.makedirs(os.path.dirname(server_manifest_path))
                tmp_ind_dir = os.path.join(depotpath, "index", "TMP")

                fh = open(server_manifest_path, "w")
                fh.write(self.bogus_pkg10)
                fh.close()

                self.image_create(durl)
                self.dc.stop()
                self.dc.set_rebuild()
                self.dc.start()

                # Should return nothing, as the server can't build catalog
                # data for the package since the manifest is unparseable.
                self._search_op(True, "'*bogus*'", set(), exit=1)
                self._search_op(True, "6627937", set(), exit=1)

                # Should fail since the bogus_pkg isn't even in the catalog.
                self.pkg("install bogus_pkg", exit=1)

                client_manifest_file = self.get_img_manifest_path(
                    self.bogus_fmri)
                os.makedirs(os.path.dirname(client_manifest_file))

                fh = open(client_manifest_file, "w")
                fh.write(self.bogus_pkg10)
                fh.close()

                # Load the 'installed' catalog and add an entry for the
                # new package version.
                img = self.get_img_api_obj().img
                istate_dir = os.path.join(img._statedir, "installed")
                cat = catalog.Catalog(meta_root=istate_dir)
                mdata = { "states": [pkgdefs.PKG_STATE_INSTALLED] }
                bfmri = self.bogus_fmri.copy()
                bfmri.set_publisher("test")
                cat.add_package(bfmri, metadata=mdata)
                cat.save()

                self.pkg("rebuild-index")
                self._search_op(False, "'*bogus*'",
                    set(self.res_bogus_name_result))
                self._search_op(False, "6627937",
                    set(self.res_bogus_number_result))

        def test_bug_6177(self):
                """Test that by default search restricts the results to the
                incorporated packages and that the -f option works as
                expected."""

                durl = self.dc.get_depot_url()
                self.pkgsend_bulk(durl, (self.example_pkg10, self.example_pkg11,
                    self.incorp_pkg10))

                self.image_create(durl)

                res_both_actions = set([
                    self.headers,
                    "path       dir    bin   pkg:/example_pkg@1.0-0\n",
                    "path       dir    bin   pkg:/example_pkg@1.1-0\n"
                ])

                res_10_action = set([
                    self.headers,
                    "path       dir    bin   pkg:/example_pkg@1.0-0\n"
                ])


                res_11_action = set([
                    self.headers,
                    "path       dir    bin   pkg:/example_pkg@1.1-0\n"
                ])

                self.pkg("install incorp_pkg")
                self._search_op(True, '/bin', res_10_action)
                self._search_op(True, '/bin', res_both_actions,
                    prune_versions=False)

                self.pkg("uninstall incorp_pkg")
                self.pkg("install example_pkg")
                self._search_op(True, '/bin', res_11_action)
                self._search_op(True, '/bin', res_both_actions,
                    prune_versions=False)

        def test_fmri_output(self):
                """Test that the build_release is dropped from version string
                of pkg FMRIS for the special case '-o pkg.fmri'."""

                durl = self.dc.get_depot_url()
                plist = self.pkgsend_bulk(durl, self.incorp_pkg10)

                self.image_create(durl)
                self.pkg("search -Ho pkg.fmri incorp_pkg")
                self.assertTrue(fmri.PkgFmri(plist[0]).get_fmri(
                    include_build=False, anarchy=True) in self.output)

        def test_versionless_incorp(self):
                """Test that versionless incorporates are ignored by search when
                restricting results to incorporated packages (see bug 7149895).
                """

                durl = self.dc.get_depot_url()
                self.pkgsend_bulk(durl, (self.incorp_pkg10,
                    self.nover_incorp_pkg10))

                self.image_create(durl)

                res = set([
                    self.headers,
                    "pkg.fmri    set    test/incorp_pkg pkg:/incorp_pkg@1.0-0\n",
                    "incorporate depend incorp_pkg      pkg:/nover_incorp_pkg@1.0-0\n",
                ])

                self.pkg("install incorp_pkg nover_incorp_pkg")
                self._search_op(True, 'incorp_pkg', res)

                self.pkg("uninstall nover_incorp_pkg")
                self._search_op(True, 'incorp_pkg', res)

        def test_bug_7835(self):
                """Check that installing a package in a non-empty image
                without an index doesn't build an index."""
                # This test can't be moved to t_api_search until bug 8497 has
                # been resolved.
                durl = self.dc.get_depot_url()
                self.pkgsend_bulk(durl, (self.fat_pkg10, self.example_pkg10))

                self.image_create(durl)

                self.pkg("install fat")

                id, tid = self._get_index_dirs()
                self.assertTrue(len(os.listdir(id)) > 0)
                shutil.rmtree(id)
                os.makedirs(id)
                self.pkg("install example_pkg")
                self.assertTrue(len(os.listdir(id)) == 0)
                self.pkg("uninstall fat")
                self.assertTrue(len(os.listdir(id)) == 0)
                self._run_local_tests()
                self.pkgsend_bulk(durl, self.example_pkg10)
                self.pkg("refresh")
                self.pkg("update")
                self.assertTrue(len(os.listdir(id)) == 0)

        def test_bug_8098(self):
                """Check that parse errors don't cause tracebacks in the client
                or the server."""

                durl = self.dc.get_depot_url()
                self.pkgsend_bulk(durl, self.example_pkg10)

                self.image_create(durl)

                self.pkg("install example_pkg")

                self.pkg("search -l 'Intel(R)'", exit=1)
                self.pkg("search -l 'foo AND <bar>'", exit=1)
                self.pkg("search -r 'Intel(R)'", exit=1)
                self.pkg("search -r 'foo AND <bar>'", exit=1)

                urlopen("{0}/en/search.shtml?token=foo+AND+<bar>&"
                    "action=Search".format(durl))
                urlopen("{0}/en/search.shtml?token=Intel(R)&"
                    "action=Search".format(durl))

                pkg5unittest.eval_assert_raises(HTTPError,
                    lambda x: x.code == 400, urlopen,
                    "{0}/search/1/False_2_None_None_Intel%28R%29".format(durl))
                pkg5unittest.eval_assert_raises(HTTPError,
                    lambda x: x.code == 400, urlopen,
                    "{0}/search/1/False_2_None_None_foo%20%3Cbar%3E".format(durl))

        def test_bug_10515(self):
                """Check that -o and -H options work as expected."""

                durl = self.dc.get_depot_url()
                self.pkgsend_bulk(durl, self.example_pkg10)

                self.image_create(durl)

                o_options = "action.name,action.key,pkg.name,pkg.shortfmri," \
                    "search.match,search.match_type,mode,owner,group," \
                    "action.raw,pkg.publisher"

                pkg_options = "-o pkg.name -o pkg.shortfmri -o pkg.publisher " \
                    "-o mode"

                self._search_op(True, "-o {0} example_path".format(o_options),
                    self.res_o_options_remote)
                self._search_op(True, "-H -o {0} example_path".format(o_options),
                    [self.o_results])
                self._search_op(True, "-s {0} -o {1} example_path".format(
                    durl, o_options), self.res_o_options_remote)

                self._search_op(True, "{0} -p example_path".format(pkg_options),
                    self.res_pkg_options_remote)
                self._search_op(True, "{0} '<example_path>'".format(pkg_options),
                    self.res_pkg_options_remote)

                self.pkg("install example_pkg")
                self._search_op(False, "-o {0} example_path".format(o_options),
                    self.res_o_options_local)
                self._search_op(False, "-H -o {0} example_path".format(o_options),
                    [self.o_results_no_pub])

                self._search_op(False, "{0} -p example_path".format(pkg_options),
                    self.res_pkg_options_local)
                self._search_op(False, "{0} '<example_path>'".format(pkg_options),
                    self.res_pkg_options_local)

                id, tid = self._get_index_dirs()
                shutil.rmtree(id)
                self._search_op(False, "-o {0} example_path".format(o_options),
                    self.res_o_options_local)
                self._search_op(False, "-H -o {0} example_path".format(o_options),
                    [self.o_results_no_pub])

        def test_bug_12271_14088(self):
                """Check that consecutive duplicate lines are removed and
                that having a single option to -o still prints the header."""

                # This test assumes that search is basically working and focuses
                # on testing whether consecutive duplicate lines have been
                # correctly removed.  For the first three queries, two lines are
                # expected.  The first line is the headers and the second is
                # a line for the matching package.  Without consecutive
                # duplicate line removal, far more than two lines would be
                # seen.  The final query has four lines of output.  The headers
                # are the first line and the package name followed by
                # com.sun.service.incorporated_changes, com.sun.service.bug_ids,
                # or com.sun.service.keywords.

                # The final query depends on search returning the results in
                # a consistent ordering so that all the like lines get merged
                # together.  If this changes in the future, because of parallel
                # indexing or parallel searching for example, it's possible
                # this test will need to be removed or reexamined.

                durl = self.dc.get_depot_url()
                self.pkgsend_bulk(durl, self.dup_lines_pkg10)

                self.image_create(durl)

                self.pkg("search -a 'dup_lines:set:pkg.fmri:'")
                self.assertEqual(len(self.output.splitlines()), 2)

                self.pkg("search -a -o pkg.shortfmri 'a'")
                self.assertEqual(len(self.output.splitlines()), 2)

                self.pkg("install dup_lines")

                self.pkg("search -a -l 'dup_lines:set:pkg.fmri:'")
                self.assertEqual(len(self.output.splitlines()), 2)

                self.pkg("search -l -a -o pkg.shortfmri,action.key 'a'")
                self.assertEqual(len(self.output.splitlines()), 4)

        def __run_empty_attrs_searches(self, remote):
                expected = set(["basename\tfile\tetc/group\tpkg:/empty@1.0\n"])
                self._search_op(remote=remote, token="group",
                    test_value=expected, headers=False)

                expected = set(["pkg.fmri\tset\ttest/empty\t"
                    "pkg:/empty@1.0"])
                self._search_op(remote=remote, token="empty",
                    test_value=expected, headers=False)

                expected = set(["name\tuser\tfozzie\tpkg:/empty@1.0"])
                self._search_op(remote=remote, token="fozzie",
                    test_value=expected, headers=False)

                expected = set(["name\tgroup\tfoo\tpkg:/empty@1.0"])
                self._search_op(remote=remote, token="foo",
                    test_value=expected, headers=False)

                expected = set(["path\tlink\tlink\tpkg:/empty@1.0"])
                self._search_op(remote=remote, token="/link",
                    test_value=expected, headers=False)

                expected = set(["path\tdir\tempty_dir\tpkg:/empty@1.0"])
                self._search_op(remote=remote, token="/empty_dir",
                    test_value=expected, headers=False)

                expected = set(["optional\tdepend\texample_pkg@1.0\t"
                    "pkg:/empty@1.0"])
                self._search_op(remote=remote, token="example_pkg",
                    test_value=expected, headers=False)

        def test_empty_attrs_new(self):
                """Check that attributes that can have empty values don't break
                indexing or search when they're added to an empty index."""

                rurl = self.dc.get_repo_url()
                durl = self.dc.get_depot_url()
                self.pkgsend_bulk(rurl, self.empty_attr_pkg10)

                self.image_create(durl)

                self.__run_empty_attrs_searches(remote=True)
                self.pkg("install empty")
                self.__run_empty_attrs_searches(remote=False)

        def test_empty_attrs_additional(self):
                """Check that attributes that can have empty values don't break
                indexing or search when they're being added to an existing
                index."""

                rurl = self.dc.get_repo_url()
                durl = self.dc.get_depot_url()
                self.pkgsend_bulk(rurl, self.fat_pkg10)
                self.pkgsend_bulk(rurl, self.empty_attr_pkg10)

                self.image_create(durl)

                self.__run_empty_attrs_searches(remote=True)
                self.pkg("install fat")
                self.pkg("install empty")
                self.__run_empty_attrs_searches(remote=False)
                for i in range(0, indexer.MAX_FAST_INDEXED_PKGS + 1):
                        self.pkgsend_bulk(durl, self.empty_attr_pkg10_templ.format(
                            ver=i))
                self.pkg("install 'empty*'")
                self.pkg("search 'empty*'")

        def test_missing_manifest(self):
                """Check that missing manifests don't cause a traceback when
                indexing or searching."""

                rurl = self.dc.get_repo_url()
                plist = self.pkgsend_bulk(rurl, self.example_pkg10)
                api_obj = self.image_create(rurl)
                self._api_install(api_obj, ["example_pkg"])
                client_manifest_file = self.get_img_manifest_path(
                    fmri.PkgFmri(plist[0]))
                portable.remove(client_manifest_file)
                # Test search with a missing manifest.
                self.pkg("search -l /bin", exit=1)
                # Test rebuilding the index with a missing manifest.
                self.pkg("rebuild-index")

        def test_15807844(self):
                """ Check that pkg search for temporary sources is successful
                when there no publishers configured in the image."""

                rurl = self.dc.get_repo_url()
                self.pkgsend_bulk(rurl, self.example_pkg10)
                self.image_create()
                expected = \
                "INDEX ACTION VALUE PACKAGE\n" \
                "basename file bin/example_path pkg:/example_pkg@1.0-0\n"
                self.pkg("search -s {0} example_path".format(self.rurl))
                actual = self.reduceSpaces(self.output)
                expected = self.reduceSpaces(expected)
                self.assertEqualDiff(expected, actual)
                self.pkg("search example_path", exit=1)


class TestSearchMultiPublisher(pkg5unittest.ManyDepotTestCase):

        same_pub1 = """
            open same_pub1@1.1,5.11-0
            add dir mode=0755 owner=root group=bin path=/bin
            add file tmp/samepub_file1 mode=0555 owner=root group=bin path=/bin/samepub_file1
            close """

        same_pub2 = """
            open same_pub2@1.1,5.11-0
            add dir mode=0755 owner=root group=bin path=/bin
            add file tmp/samepub_file2 mode=0555 owner=root group=bin path=/bin/samepub_file2
            close """

        example_pkg11 = """
            open pkg://test1/example_pkg@1.2,5.11-0
            add dir mode=0755 owner=root group=bin path=/bin
            add file tmp/example_file mode=0555 owner=root group=bin path=/bin/example_path12
            close """

        incorp_pkg11 = """
            open pkg://test1/incorp_pkg@1.2,5.11-0
            add depend fmri=pkg://test1/example_pkg@1.2,5.11-0 type=incorporate
            close """

        example_pkg12 = """
            open pkg://test2/example_pkg@1.2,5.11-0
            add dir mode=0755 owner=root group=bin path=/bin
            add file tmp/example_file mode=0555 owner=root group=bin path=/bin/example_path12
            close """

        incorp_pkg12 = """
            open pkg://test2/incorp_pkg@1.3,5.11-0
            add depend fmri=pkg://test2/example_pkg@1.2,5.11-0 type=incorporate
            close """

        misc_files = {
            "tmp/samepub_file1": "magic",
            "tmp/samepub_file2": "magic",
            "tmp/example_file": "magic",
        }

        def setUp(self):
                pkg5unittest.ManyDepotTestCase.setUp(self, ["samepub",
                    "samepub"], start_depots=True)
                self.make_misc_files(self.misc_files)
                self.durl1 = self.dcs[1].get_depot_url()
                self.pkgsend_bulk(self.durl1, self.same_pub1, refresh_index=True)
                self.durl2 = self.dcs[2].get_depot_url()
                self.rurl2 = self.dcs[2].get_repo_url()

        def test_7140657(self):
                """ Check that pkg search with -s works as intended when there are
                two repositories with same publisher name configured."""

                self.pkgsend_bulk(self.durl1, self.same_pub1, refresh_index=True)
                self.pkgsend_bulk(self.durl2, self.same_pub2, refresh_index=True)
                self.image_create(self.durl1, prefix="samepub")
                self.pkg("set-publisher -g {0} samepub".format(self.durl2))
                self.pkg("search -s {0} samepub_file1".format(self.durl1))

                result_same_pub = \
                "INDEX ACTION VALUE PACKAGE\n" \
                "basename file bin/samepub_file1 pkg:/same_pub1@1.1-0\n"

                actual = self.reduceSpaces(self.output)
                expected = self.reduceSpaces(result_same_pub)
                self.assertEqualDiff(expected, actual)
                self.pkg("search -s {0} samepub_file1".format(self.durl2), exit=1)

        def test_16190165(self):
                """ Check that pkg search works fine with structured queries
                    and the scheme name "pkg://" in the query """

                self.pkgsend_bulk(self.durl1, self.example_pkg11, refresh_index=True)
                self.pkgsend_bulk(self.durl2, self.example_pkg12, refresh_index=True)
                self.pkgsend_bulk(self.durl1, self.incorp_pkg11, refresh_index=True)
                self.pkgsend_bulk(self.durl2, self.incorp_pkg12, refresh_index=True)
                self.image_create(self.durl1, prefix="test1")
                self.pkg("set-publisher -g {0} test2".format(self.durl2))

                expected_out1 = \
                "incorporate\tdepend\tpkg://test1/example_pkg@1.2,5.11-0\tpkg:/incorp_pkg@1.2-0\n" \
                "incorporate\tdepend\tpkg://test2/example_pkg@1.2,5.11-0\tpkg:/incorp_pkg@1.3-0\n"

                self.pkg("search -H :depend:incorporate:example_pkg",
                     exit=0)
                actual = self.reduceSpaces(self.output)
                expected = self.reduceSpaces(expected_out1)
                # Output order is unstable in Python 3, we just assert the
                # results are the same.
                for l in actual:
                        assert l in expected

                expected_out2 = \
                "pkg.fmri\tset\ttest1/example_pkg\tpkg:/example_pkg@1.2-0\n" \
                "incorporate\tdepend\tpkg://test1/example_pkg@1.2,5.11-0\tpkg:/incorp_pkg@1.2-0\n" \
                "pkg.fmri\tset\ttest2/example_pkg\tpkg:/example_pkg@1.2-0\n" \
                "incorporate\tdepend\tpkg://test2/example_pkg@1.2,5.11-0\tpkg:/incorp_pkg@1.3-0\n"

                self.pkg("search -H pkg://test1/example_pkg",exit=0)
                actual = self.reduceSpaces(self.output)
                expected = self.reduceSpaces(expected_out2)
                for l in actual:
                        assert l in expected

                self.pkg("search -H pkg:/example_pkg",exit=0)
                actual = self.reduceSpaces(self.output)
                expected = self.reduceSpaces(expected_out2)
                for l in actual:
                        assert l in expected

        def test_search_multi_hash_1(self):
                """Check that when searching a repository with multiple
                hashes, all hash attributes are indexed and we can search
                against all hash attributes.

                This test depends on pkg.digest having DebugValue settings
                that add sha256 hashes to the set of hashes we append to
                actions at publication time."""
                self.base_search_multi_hash("sha256", hashlib.sha256)

        def base_search_multi_hash(self, hash_alg, hash_fun):
                # our 2nd depot gets the package published with multiple hash
                # attributes, but served from a single-hash-aware depot
                # (the fact that it's single-hash-aware should make no
                # difference to the content it serves so long as the index was
                # generated while we were aware of multiple hashes.
                self.pkgsend_bulk(self.rurl2, self.same_pub2,
                    refresh_index=True, debug_hash="sha1+{0}".format(hash_alg))
                self.image_create(self.durl2, prefix="samepub")

                # manually calculate the hashes, in case of bugs in
                # pkg.misc.get_data_digest
                sha1_hash = hashlib.sha1(b"magic").hexdigest()
                sha2_hash = hash_fun(b"magic").hexdigest()

                self.pkg("search {0}".format(sha1_hash))
                self.pkg("search {0}".format(sha2_hash))

                # Check that we're matching on the correct index.
                # For sha1 hashes, our the 'index' returned is actually the
                # hash itself - that seems unusual, but it's the way the
                # index was built. We also emit a 2nd search result that shows
                # 'hash', in order to be consistent with the way we print
                # the pkg.hash.sha* attribute when dealing with other hashes.
                self.pkg("search -H -o search.match_type {0}".format(sha1_hash))
                self.assertEqualDiff(
                    self.reduceSpaces(self.output), "{0}\nhash\n".format(sha1_hash))

                self.pkg("search -H -o search.match_type {0}".format(sha2_hash))
                self.assertEqualDiff(
                    self.reduceSpaces(self.output), "pkg.hash.{0}\n".format(hash_alg))

                # check that both searches match the same action
                self.pkg("search -o action.raw {0}".format(sha1_hash))
                sha1_action = self.reduceSpaces(self.output)

                self.pkg("search -o action.raw {0}".format(sha2_hash))
                sha2_action = self.reduceSpaces(self.output)
                self.assertEqualDiff(sha1_action, sha2_action)

                # check that the same searches in the non-multihash-aware
                # repository only return a result for the sha-1 hash
                # (which checks that we're only setting multiple hashes
                # on actions when hash=sha1+sha256 or hash=sha1+sha512_256
                # is set)
                self.pkg("search -s {0} {1}".format(self.durl1, sha1_hash))
                self.pkg("search -s {0} {1}".format(self.durl1, sha2_hash), exit=1)

        def test_search_indices(self):
                """Ensure that search indices are generated properly when
                a new hash is enabled."""

                # Publish a package which only contains SHA-1 hashes.
                self.pkgsend_bulk(self.durl1, self.same_pub2)
                # Enable SHA-2 hashes in the other repository.
                self.dcs[2].stop()
                self.dcs[2].set_debug_feature("hash=sha1+sha256")
                self.dcs[2].start()
                # pkgrecv the published package which only contains SHA-1
                # hashes to a repository which enables SHA-2 hashes.
                self.pkgrecv(self.durl1, "-d {0} {1}".format(self.durl2,
                    "same_pub2@1.1"))
                self.pkgrepo("-s {0} refresh".format(self.durl2))
                # Ensure no error log entry exists.
                self.file_doesnt_contain(self.dcs[2].get_logpath(),
                    "missing the expected attribute")

        def test_search_ignore_publisher_with_no_origin(self):
            """ Check that if pkg search will ignore the publisher with no
            origin."""
            self.pkgsend_bulk(self.durl1, self.example_pkg11,
                    refresh_index=True)
            self.image_create(self.durl1)
            self.pkg("set-publisher somepub")
            self.pkg("search example_pkg")


if __name__ == "__main__":
        unittest.main()

# Vim hints
# vim:ts=8:sw=8:et:fdm=marker
