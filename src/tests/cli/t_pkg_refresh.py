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

# Copyright (c) 2008, 2016, Oracle and/or its affiliates. All rights reserved.

from . import testutils
if __name__ == "__main__":
        testutils.setup_environment("../../../proto")
import pkg5unittest

import hashlib
import os
import re
import shutil
import tempfile
import unittest

import pkg.catalog as catalog
import pkg.misc

from pkg.client import global_settings
from pkg.client.debugvalues import DebugValues


class TestPkgRefreshMulti(pkg5unittest.ManyDepotTestCase):

        # Tests in this suite use the read only data directory.
        need_ro_data = True

        foo1 = """
            open foo@1,5.11-0
            close """

        foo10 = """
            open foo@1.0,5.11-0
            close """

        foo11 = """
            open foo@1.1,5.11-0
            close """

        foo12 = """
            open foo@1.2,5.11-0
            close """

        foo121 = """
            open foo@1.2.1,5.11-0
            close """

        food12 = """
            open food@1.2,5.11-0
            close """

        cache10 = """
            open cache@1.0
            add file tmp/cat mode=0444 owner=root group=bin path=/etc/cat
            close """

        misc_files = ["tmp/cat"]

        def setUp(self):
                # This test suite needs actual depots.
                pkg5unittest.ManyDepotTestCase.setUp(self, ["test1", "test2",
                    "test1", "test1"], start_depots=True)
                self.make_misc_files(self.misc_files)

                self.durl1 = self.dcs[1].get_depot_url()
                self.durl2 = self.dcs[2].get_depot_url()
                self.durl3 = self.dcs[3].get_depot_url()

                # An empty repository for test1 to enable metadata tests
                # to continue to work as expected.
                self.durl4 = self.dcs[4].get_depot_url()

        def reduce_spaces(self, string):
                """Reduce runs of spaces down to a single space."""
                return re.sub(" +", " ", string)

        def get_op_entries(self, dc, op, op_ver, method="GET"):
                """Scan logpath for a specific depotcontroller looking for
                access log entries for an operation.  Returns a list of request
                URIs for each log entry found for the operation in chronological
                order."""

                # 127.0.0.1 - - [15/Oct/2009:00:15:38]
                # "GET [/<pub>]/catalog/1/catalog.base.C HTTP/1.1" 200 189 ""
                # "pkg/b1f63b112bff+ (sunos i86pc; 5.11 snv_122; none; pkg)"
                entry_comps = [
                    r"(?P<host>\S+)",
                    r"\S+",
                    r"(?P<user>\S+)",
                    r"\[(?P<request_time>.+)\]",
                    r'"(?P<request>.+)"',
                    r"(?P<response_status>[0-9]+)",
                    r"(?P<content_length>\S+)",
                    r'"(?P<referer>.*)"',
                    r'"(?P<user_agent>.*)"',
                ]
                log_entry = re.compile(r"\s+".join(entry_comps) + r"\s*\Z")

                logpath = dc.get_logpath()
                self.debug("check for operation entries in {0}".format(logpath))
                logfile = open(logpath, "r")
                entries = []
                for line in logfile.readlines():
                        m = log_entry.search(line)
                        if not m:
                                continue

                        host, user, req_time, req, status, clen, ref, agent = \
                            m.groups()

                        req_method, uri, protocol = req.split(" ")
                        if req_method != method:
                                continue

                        # Strip publisher from URI for this part.
                        uri = uri.replace("/test1", "")
                        uri = uri.replace("/test2", "")
                        req_parts = uri.strip("/").split("/", 3)
                        if req_parts[0] != op:
                                continue

                        if req_parts[1] != op_ver:
                                continue
                        entries.append(uri)
                logfile.close()
                self.debug("Found {0} for {1} /{2}/{3}/".format(entries, method, op,
                    op_ver))
                return entries

        def checkAnswer(self, expected, actual):
                self.assertEqualDiff(
                    self.reduce_spaces(expected).splitlines().sort(),
                    self.reduce_spaces(actual).splitlines().sort())

        def test_refresh_cli_options(self):
                """Test refresh and options."""

                durl = self.dcs[1].get_depot_url()
                self.image_create(durl, prefix="test1")

                self.pkg("refresh")
                self.pkg("refresh --full")
                self.pkg("refresh -q")
                self.pkg("refresh -F", exit=2)

        def test_general_refresh(self):
                self.image_create(self.durl1, prefix="test1")
                self.pkg("set-publisher -O " + self.durl2 + " test2")
                self.pkgsend_bulk(self.durl1, self.foo10)
                self.pkgsend_bulk(self.durl2, self.foo12)

                # This should fail as the publisher was just updated seconds
                # ago, and not enough time has passed yet for the client to
                # contact the repository to check for updates.
                self.pkg("list -aH pkg:/foo", exit=1)

                # This should succeed as a full refresh was requested, which
                # ignores the update check interval the client normally uses
                # to determine whether or not to contact the repository to
                # check for updates.
                self.pkg("refresh --full")
                self.pkg("list -aH pkg:/foo")

                expected = \
                    "foo 1.0-0 ---\n" + \
                    "foo (test2) 1.2-0 ---\n"
                self.checkAnswer(expected, self.output)

        def test_specific_refresh(self):
                self.image_create(self.durl1, prefix="test1")
                self.pkg("set-publisher -O " + self.durl2 + " test2")
                self.pkgsend_bulk(self.durl1, self.foo10)
                self.pkgsend_bulk(self.durl2, self.foo12)

                # This should fail since only a few seconds have passed since
                # the publisher's metadata was last checked, and so the catalog
                # will not yet reflect the last published package.
                self.pkg("list -aH pkg:/foo@1,5.11-0", exit=1)

                # This should succeed since a refresh is explicitly performed,
                # and so the catalog will reflect the last published package.
                self.pkg("refresh test1")
                self.pkg("list -aH pkg:/foo@1,5.11-0")

                expected = \
                    "foo 1.0-0 ---\n"
                self.checkAnswer(expected, self.output)

                # This should succeed since a refresh is explicitly performed,
                # and so the catalog will reflect the last published package.
                self.pkg("refresh test2")
                self.pkg("list -aH pkg:/foo")
                expected = \
                    "foo 1.0-0 ---\n" + \
                    "foo (test2) 1.2-0 ---\n"
                self.checkAnswer(expected, self.output)
                self.pkg("refresh unknownAuth", exit=1)
                self.pkg("set-publisher -P test2")
                self.pkg("list -aH pkg:/foo")
                expected = \
                    "foo (test1) 1.0-0 ---\n" + \
                    "foo 1.2-0 ---\n"
                self.pkgsend_bulk(self.durl1, self.foo11)
                self.pkgsend_bulk(self.durl2, self.foo11)

                # This should succeed since an explicit refresh is performed,
                # and so the catalog will reflect the last published package.
                self.pkg("refresh test1 test2")
                self.pkg("list -aHf pkg:/foo")
                expected = \
                    "foo (test1) 1.0-0 ---\n" + \
                    "foo (test1) 1.1-0 ---\n" + \
                    "foo 1.1-0 ---\n" + \
                    "foo 1.2-0 ---\n"
                self.checkAnswer(expected, self.output)

        def test_set_publisher_induces_full_refresh(self):
                self.pkgsend_bulk(self.durl3, self.foo11)
                self.pkgsend_bulk(self.durl3, self.foo10)
                self.pkgsend_bulk(self.durl1, self.foo10)
                self.pkgsend_bulk(self.durl2, self.foo11)
                self.image_create(self.durl1, prefix="test1")
                self.pkg("list -aH pkg:/foo")
                expected = \
                    "foo 1.0-0 ---\n"
                self.checkAnswer(expected, self.output)

                # If a privileged user requests this, it should fail since
                # publisher metadata will have been refreshed, but it will
                # be the metadata from a repository that does not contain
                # any package metadata for this publisher.
                self.pkg("set-publisher -O " + self.durl4 + " test1")
                self.pkg("list --no-refresh -avH pkg:/foo@1.0", exit=1)
                self.pkg("list --no-refresh -avH pkg:/foo@1.1", exit=1)

                # If a privileged user requests this, it should succeed since
                # publisher metadata will have been refreshed, and contains
                # package data for the publisher.
                self.pkg("set-publisher -O " + self.durl3 + " test1")
                self.pkg("list --no-refresh -afH pkg:/foo")
                expected = \
                    "foo 1.0-0 ---\n" \
                    "foo 1.1-0 ---\n"
                self.checkAnswer(expected, self.output)

        def test_set_publisher_induces_delayed_full_refresh(self):
                self.pkgsend_bulk(self.durl3, self.foo11)
                self.pkgsend_bulk(self.durl2, self.foo11)
                self.pkgsend_bulk(self.durl1, self.foo10)
                self.image_create(self.durl1, prefix="test1")
                self.pkg("list -aH pkg:/foo")
                expected = \
                    "foo 1.0-0 ---\n"
                self.checkAnswer(expected, self.output)
                self.dcs[2].stop()
                self.pkg("set-publisher --no-refresh -O " + self.durl3 + " test1")
                self.dcs[2].start()

                # This should fail when listing all known packages, and running
                # as an unprivileged user since the publisher's metadata can't
                # be updated.
                self.pkg("list -aH pkg:/foo@1.1", su_wrap=True, exit=1)

                # This should fail when listing all known packages, and running
                # as a privileged user since --no-refresh was specified.
                self.pkg("list -aH --no-refresh pkg:/foo@1.1", exit=1)

                # This should succeed when listing all known packages, and
                # running as a privileged user since the publisher's metadata
                # will automatically be updated, and the repository contains
                # package data for the publisher.
                self.pkg("list -aH pkg:/foo@1.1")
                expected = \
                    "foo 1.1-0 ---\n"
                self.checkAnswer(expected, self.output)

                # This should fail when listing all known packages, and
                # running as a privileged user since the publisher's metadata
                # will automatically be updated, but the repository doesn't
                # contain any data for the publisher.
                self.dcs[2].stop()
                self.pkg("set-publisher -O " + self.durl1 + " test1")
                self.pkg("set-publisher --no-refresh -O " + self.durl2 + " test1")
                self.dcs[2].start()
                self.pkg("list -aH --no-refresh pkg:/foo@1.1", exit=1)

        def test_refresh_certificate_problems(self):
                """Verify that an invalid or inaccessible certificate does not
                cause unexpected failure."""

                self.image_create(self.durl1, prefix="test1")

                key_path = os.path.join(self.keys_dir, "cs1_ch1_ta3_key.pem")
                cert_path = os.path.join(self.cs_dir, "cs1_ch1_ta3_cert.pem")

                self.pkg("set-publisher --no-refresh -O https://{0}1 test1".format(
                    self.bogus_url))
                self.pkg("set-publisher --no-refresh -c {0} test1".format(cert_path))
                self.pkg("set-publisher --no-refresh -k {0} test1".format(key_path))


                # This test relies on using the same implementation used in
                # image.py __store_publisher_ssl() which sets the paths to the
                # SSL keys/certs.
                img_key_path = os.path.join(self.img_path(), "var", "pkg",
                    "ssl", pkg.misc.get_data_digest(key_path,
                    hash_func=hashlib.sha1)[0])
                img_cert_path = os.path.join(self.img_path(), "var", "pkg",
                    "ssl", pkg.misc.get_data_digest(cert_path,
                    hash_func=hashlib.sha1)[0])

                # Make the cert/key unreadable by unprivileged users.
                os.chmod(img_key_path, 0000)
                os.chmod(img_cert_path, 0000)

                # Verify that an inaccessible certificate results in a normal
                # failure when attempting to refresh.
                self.pkg("refresh test1", su_wrap=True, exit=1)

                # Verify that an invalid certificate results in a normal failure
                # when attempting to refresh.
                open(img_key_path, "wb").close()
                open(img_cert_path, "wb").close()
                self.pkg("refresh test1", exit=1)

        def __get_cache_entries(self, dc):
                """Returns any HTTP cache headers found."""

                entries = []
                for hdr in ("CACHE-CONTROL", "PRAGMA"):
                        logpath = dc.get_logpath()
                        self.debug("check for HTTP cache headers in {0}".format(
                            logpath))
                        logfile = open(logpath, "r")
                        for line in logfile.readlines():
                                spos = line.find(hdr)
                                if spos > -1:
                                        self.debug("line: {0}".format(line))
                                        self.debug("hdr: {0} spos: {1}".format(hdr, spos))
                                        spos += len(hdr) + 1
                                        l = line[spos:].strip()
                                        l = l.strip("()")
                                        self.debug("l: {0}".format(l))
                                        if l:
                                                entries.append({ hdr: l })
                        logfile.close()
                return entries

        def test_catalog_v1(self):
                """Verify that refresh works as expected for publishers that
                have repositories that offer catalog/1/ in exceptional error
                cases."""

                dc = self.dcs[1]
                self.pkgsend_bulk(self.durl1, self.foo10)

                # First, verify that full retrieval works.
                self.image_create(self.durl1, prefix="test1")

                self.pkg("list -aH pkg:/foo@1.0")

                # Only entries for the full catalog files should exist.
                expected = [
                    "/catalog/1/catalog.attrs",
                    "/catalog/1/catalog.base.C"
                ]
                returned = self.get_op_entries(dc, "catalog", "1")
                self.assertEqual(returned, expected)

                # Next, verify that a "normal" incremental update works as
                # expected when the catalog has changed.
                self.pkgsend_bulk(self.durl1, self.foo11)

                self.pkg("list -aH")
                self.pkg("list -aH pkg:/foo@1.0")
                self.pkg("list -aH pkg:/foo@1.1", exit=1)

                self.pkg("refresh")
                self.pkg("list -aH pkg:/foo@1.1")

                # A bit hacky, but load the repository's catalog directly
                # and then get the list of updates files it has created.
                repo = dc.get_repo()
                v1_cat = repo.get_catalog("test1")
                update = list(v1_cat.updates.keys())[-1]

                # All of the entries from the previous operations, and then
                # entries for the catalog attrs file, and one catalog update
                # file for the incremental update should be returned.
                expected += [
                    "/catalog/1/catalog.attrs",
                    "/catalog/1/{0}".format(update)
                ]
                returned = self.get_op_entries(dc, "catalog", "1")
                self.assertEqual(returned, expected)

                # Next, verify that a "normal" incremental update works as
                # expected when the catalog hasn't changed.
                self.pkg("refresh test1")

                # All of the entries from the previous operations, and then
                # an entry for the catalog attrs file should be returned.
                expected += [
                    "/catalog/1/catalog.attrs"
                ]
                returned = self.get_op_entries(dc, "catalog", "1")
                self.assertEqual(returned, expected)

                # Next, verify that a "full" refresh after incrementals works
                # as expected.
                self.pkg("refresh --full test1")

                # All of the entries from the previous operations, and then
                # entries for each part of the catalog should be returned.
                expected += ["/catalog/1/catalog.attrs"]
                expected += ["/catalog/1/{0}".format(p) for p in v1_cat.parts.keys()]
                returned = self.get_op_entries(dc, "catalog", "1")
                self.assertEqual(returned, expected)

                # Next, verify that rebuilding the repository's catalog induces
                # a full refresh.  Note that doing this wipes out the contents
                # of the log so far, so expected needs to be reset and the
                # catalog reloaded.
                expected = []
                repo = dc.get_repo()
                v1_cat = repo.get_catalog("test1")

                dc.stop()
                dc.set_rebuild()
                dc.start()
                dc.set_norebuild()

                self.pkg("refresh")

                # The catalog.attrs will be retrieved twice due to the first
                # request's incremental update failure.
                expected += ["/catalog/1/catalog.attrs"]
                expected += ["/catalog/1/catalog.attrs"]
                expected += ["/catalog/1/{0}".format(p) for p in v1_cat.parts.keys()]
                returned = self.get_op_entries(dc, "catalog", "1")
                self.assertEqual(returned, expected)

                # Next, verify that if the client receives an incremental update
                # but the catalog is then rolled back to an earlier version
                # (think restoration of repository from backup) that the client
                # will induce a full refresh.

                # Preserve a copy of the existing repository.
                tdir = tempfile.mkdtemp(dir=self.test_root)
                trpath = os.path.join(tdir, os.path.basename(dc.get_repodir()))
                shutil.copytree(dc.get_repodir(), trpath)

                # Publish a new package.
                self.pkgsend_bulk(self.durl1, self.foo12)

                # Refresh to get an incremental update, and verify it worked.
                self.pkg("refresh")
                update = list(v1_cat.updates.keys())[-1]
                expected += [
                    "/catalog/1/catalog.attrs",
                    "/catalog/1/{0}".format(update)
                ]
                repo = dc.get_repo()
                v1_cat = repo.get_catalog("test1")

                # Stop the depot server and put the old repository data back.
                dc.stop()
                shutil.rmtree(dc.get_repodir())
                shutil.move(trpath, dc.get_repodir())
                dc.start()
                expected = []
                repo = dc.get_repo()
                v1_cat = repo.get_catalog("test1")

                # Now verify that a refresh induces a full retrieval.  The
                # catalog.attrs file will be retrieved twice due to the
                # failure case.
                self.pkg("refresh")
                expected += ["/catalog/1/catalog.attrs"]
                expected += ["/catalog/1/catalog.attrs"]
                expected += ["/catalog/1/{0}".format(p) for p in v1_cat.parts.keys()]
                returned = self.get_op_entries(dc, "catalog", "1")
                self.assertEqual(returned, expected)

                # Next, verify that if the client receives an incremental update
                # but the catalog is then rolled back to an earlier version
                # (think restoration of repository from backup) and then an
                # update that has already happened before is republished that
                # the client will induce a full refresh.

                # Preserve a copy of the existing repository.
                trpath = os.path.join(tdir, os.path.basename(dc.get_repodir()))
                shutil.copytree(dc.get_repodir(), trpath)

                # Publish a new package.
                self.pkgsend_bulk(self.durl1, self.foo12)
                repo = dc.get_repo()
                v1_cat = repo.get_catalog("test1")

                # Refresh to get an incremental update, and verify it worked.
                self.pkg("refresh")
                update = list(v1_cat.updates.keys())[-1]
                expected += [
                    "/catalog/1/catalog.attrs",
                    "/catalog/1/{0}".format(update)
                ]
                repo = dc.get_repo()
                v1_cat = repo.get_catalog("test1")

                # Stop the depot server and put the old repository data back.
                dc.stop()
                shutil.rmtree(dc.get_repodir())
                shutil.move(trpath, dc.get_repodir())
                dc.start()
                expected = []

                # Re-publish the new package.  This causes the same catalog
                # entry to exist, but at a different point in time in the
                # update logs.
                self.pkgsend_bulk(self.durl1, self.foo12)
                repo = dc.get_repo()
                v1_cat = repo.get_catalog("test1")
                update = list(v1_cat.updates.keys())[-1]

                # Now verify that a refresh induces a full retrieval.  The
                # catalog.attrs file will be retrieved twice due to the
                # failure case, and a retrieval of the incremental update
                # file that failed to be applied should also be seen.
                self.pkg("refresh")
                expected += [
                    "/catalog/1/catalog.attrs",
                    "/catalog/1/{0}".format(update),
                    "/catalog/1/catalog.attrs",
                ]
                expected += ["/catalog/1/{0}".format(p) for p in v1_cat.parts.keys()]
                returned = self.get_op_entries(dc, "catalog", "1")
                self.assertEqual(returned, expected)

                # Now verify that a full refresh will fail if the catalog parts
                # retrieved don't match the catalog attributes.  Do this by
                # saving a copy of the current repository catalog, publishing a
                # new package, putting back the old catalog parts and then
                # attempting a full refresh.  After that, verify the relevant
                # log entries exist.
                dc.stop()
                dc.set_debug_feature("headers")
                dc.start()

                old_cat = os.path.join(self.test_root, "old-catalog")
                cat_root = v1_cat.meta_root
                shutil.copytree(v1_cat.meta_root, old_cat)
                self.pkgsend_bulk(self.durl1, self.foo121)
                v1_cat = catalog.Catalog(meta_root=cat_root, read_only=True)
                for p in v1_cat.parts.keys():
                        # Overwrite the existing parts with empty ones.
                        part = catalog.CatalogPart(p, meta_root=cat_root)
                        part.destroy()

                        part = catalog.CatalogPart(p, meta_root=cat_root)
                        part.save()

                self.pkg("refresh --full", exit=1)
                expected = [
                    "/catalog/1/catalog.attrs",
                    "/catalog/1/catalog.base.C",
                ]
                returned = self.get_op_entries(dc, "catalog", "1")
                self.assertEqual(returned, expected)

                entries = self.__get_cache_entries(dc)
                expected = [
                    { "CACHE-CONTROL": "no-cache" },
                    { "CACHE-CONTROL": "no-cache" },
                    { "PRAGMA": "no-cache" },
                    { "PRAGMA": "no-cache" }
                ]
                self.assertEqualDiff(entries, expected)

                # Next, verify that a refresh without --full but that is
                # implicity a full because the catalog hasn't already been
                # retrieved is handled gracefully and the expected log
                # entries are present.
                dc.stop()
                dc.start()
                self.pkg("refresh", exit=1)
                expected = [
                    "/catalog/1/catalog.attrs",
                    "/catalog/1/catalog.base.C",
                    "/catalog/1/catalog.attrs",
                    "/catalog/1/catalog.base.C",
                ]
                returned = self.get_op_entries(dc, "catalog", "1")
                self.assertEqual(returned, expected)

                entries = self.__get_cache_entries(dc)
                # The first two requests should have not had any cache
                # headers attached, while the last two should have
                # triggered transport's revalidation logic.
                expected = [
                    { "CACHE-CONTROL": "max-age=0" },
                    { "CACHE-CONTROL": "max-age=0" },
                ]
                self.assertEqualDiff(entries, expected)

                # Next, purposefully corrupt the catalog.attrs file in the
                # repository and attempt a refresh.  The client should fail
                # gracefully.
                f = open(os.path.join(v1_cat.meta_root, "catalog.attrs"), "w")
                f.write("INVALID")
                f.close()
                self.pkg("refresh", exit=1)

                # Finally, restore the catalog and verify the client can
                # refresh.
                shutil.rmtree(v1_cat.meta_root)
                shutil.copytree(old_cat, v1_cat.meta_root)
                self.pkg("refresh")

        def __gen_expected(self, count):
                """Generate expected header fields result."""
                expected = []
                for i in range(count):
                        expected.append({ "CACHE-CONTROL": "no-cache" })
                for i in range(count):
                        expected.append({ "PRAGMA": "no-cache" })
                return expected

        def test_ignore_network_cache_1(self):
                """Verify that --no-network-cache option works for transport
                module."""

                dc = self.dcs[1]
                self.pkgsend_bulk(self.durl1, self.cache10)

                # First, verify refresh triggers expected cache headers when
                # retrieving catalog.
                self.image_create(self.durl1, prefix="test1")
                dc.stop()
                dc.set_debug_feature("headers")
                dc.start()
                self.pkg("--no-network-cache refresh")
                entries = self.__get_cache_entries(dc)
                expected = self.__gen_expected(2)
                self.assertEqualDiff(entries, expected)

                # Second, verify contents triggers expected cache headers when
                # fetch manifest.
                self.pkg("--no-network-cache contents -rm cache")
                entries = self.__get_cache_entries(dc)
                expected = self.__gen_expected(4)
                self.assertEqualDiff(entries, expected)

                # Third, verify install triggers expected cache headers.
                self.pkg("--no-network-cache install cache")
                entries = self.__get_cache_entries(dc)
                expected = self.__gen_expected(7)
                self.assertEqualDiff(entries, expected)

        def test_ignore_network_cache_2(self):
                """Verify that global setting client_no_network_cache works for
                transport module."""

                dc = self.dcs[1]
                self.pkgsend_bulk(self.durl1, self.cache10)

                # Verify refresh triggers expected cache headers when
                # retrieving catalog.
                api_obj = self.image_create(self.durl1, prefix="test1")
                global_settings.client_no_network_cache = True
                dc.stop()
                dc.set_debug_feature("headers")
                dc.start()
                api_obj.refresh()
                entries = self.__get_cache_entries(dc)
                expected = self.__gen_expected(2)
                self.assertEqualDiff(entries, expected)

                # Verify install triggers expected cache headers.
                self._api_install(api_obj, ["cache"])
                entries = self.__get_cache_entries(dc)
                expected = self.__gen_expected(6)
                self.assertEqualDiff(entries, expected)

        def test_ignore_network_cache_3(self):
                """Verify that debug value no_network_cache works for
                transport module."""

                dc = self.dcs[1]
                self.pkgsend_bulk(self.durl1, self.cache10)

                # Verify refresh triggers expected cache headers when
                # retrieving catalog.
                api_obj = self.image_create(self.durl1, prefix="test1")
                DebugValues["no_network_cache"] = "true"
                dc.stop()
                dc.set_debug_feature("headers")
                dc.start()
                api_obj.refresh()
                entries = self.__get_cache_entries(dc)
                expected = self.__gen_expected(2)
                self.assertEqualDiff(entries, expected)

                # Verify install triggers expected cache headers.
                self._api_install(api_obj, ["cache"])
                entries = self.__get_cache_entries(dc)
                expected = self.__gen_expected(6)
                self.assertEqualDiff(entries, expected)

                # Verify pkgrecv triggers expected cache headers.
                rpth = tempfile.mkdtemp(dir=self.test_root)
                self.pkgrecv("{0} -d {1} -D no_network_cache=true --raw"
                    " cache".format(self.durl1, rpth))
                entries = self.__get_cache_entries(dc)
                expected = self.__gen_expected(11)
                self.assertEqualDiff(entries, expected)

        def test_multi_origin_refresh(self):
                """Test that refresh behaves correctly if some origins of a
                publisher are not reachable."""

                # Use depots 1,3,4 which are all for pub 'test1'.
                self.image_create(self.durl1, prefix="test1")
                self.pkg("set-publisher -g {0} -g {1} test1".format(self.durl3,
                    self.durl4))
                self.pkgsend_bulk(self.durl1, self.foo10)
                self.pkgsend_bulk(self.durl3, self.foo11)
                self.pkgsend_bulk(self.durl4, self.foo12)
                self.dcs[3].stop()
                self.dcs[4].stop()

                # Only packages in depot 1 should be visible,
                # refresh should exit with partial success.
                self.pkg("refresh", exit=3)
                self.pkg("list -af foo@1.0")
                self.pkg("list -af foo@1.1 foo@1.2", exit=1)

                # Only packages in depot 1 and 2 should be visible,
                # refresh should exit with partial success.
                self.dcs[3].start()
                self.pkg("refresh", exit=3)
                self.pkg("list -af foo@1.0 foo@1.1")
                self.pkg("list -af foo@1.2", exit=1)

                # All packages should be visible, refresh should be complete.
                self.dcs[4].start()
                self.pkg("refresh")
                self.pkg("list -af foo@1.0 foo@1.1 foo@1.2")

        def test_implicit_multi_origin_refresh(self):
                """Test that implicit refresh behaves correctly if some origins
                of a publisher are not reachable."""

                # Use depots 1,3,4 which are all for pub 'test1'.
                self.image_create(self.durl1, prefix="test1")
                self.pkg("set-publisher -g {0} -g {1} test1".format(self.durl3,
                    self.durl4))
                self.pkgsend_bulk(self.durl1, self.foo10)
                self.pkgsend_bulk(self.durl3, self.foo11)
                self.pkgsend_bulk(self.durl4, self.foo12)
                self.dcs[3].stop()
                self.dcs[4].stop()

                # For now we can only install the version which is in the only
                # online depot. However, the offline depots should not prevent
                # us from upgrading to whatever is available.
                self.pkg("install foo@latest")
                self.pkg("list foo@1.0")

                # When we enable additional depots, newer version of foo should
                # become available for install without us having to refresh
                # explicitly.
                self.dcs[3].start()
                self.pkg("install foo@latest")
                self.pkg("list foo@1.1")

                self.dcs[4].start()
                self.pkg("install foo@latest")
                self.pkg("list foo@1.2")

if __name__ == "__main__":
        unittest.main()

# Vim hints
# vim:ts=8:sw=8:et:fdm=marker
