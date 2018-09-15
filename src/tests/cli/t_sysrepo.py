#!/usr/bin/python
# -*- coding: utf-8 -*-
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
# Copyright (c) 2011, 2016, Oracle and/or its affiliates. All rights reserved.
#

from . import testutils
if __name__ == "__main__":
        testutils.setup_environment("../../../proto")
import pkg5unittest

import errno
import hashlib
import imp
import os
import os.path
import pkg.p5p
import shutil
import unittest
import shutil
import simplejson
import six
import stat
import sys
import time
from six.moves.urllib.error import HTTPError
from six.moves.urllib.parse import urlparse, unquote
from six.moves.urllib.request import urlopen

import pkg.misc as misc
import pkg.portable as portable

from pkg.digest import DEFAULT_HASH_FUNC

SYSREPO_USER = "pkg5srv"

class TestBasicSysrepoCli(pkg5unittest.ApacheDepotTestCase):
        """Some basic tests checking that we can deal with all of our arguments
        and that we handle invalid input correctly."""

        def setUp(self):
                self.sc = None
                pkg5unittest.ApacheDepotTestCase.setUp(self, ["test"])
                self.image_create()
                self.default_sc_runtime = os.path.join(self.test_root,
                    "sysrepo_runtime")
                self.default_sc_conf = os.path.join(self.default_sc_runtime,
                    "sysrepo_httpd.conf")

        def _start_sysrepo(self, runtime_dir=None):
                if not runtime_dir:
                        runtime_dir = self.default_sc_runtime
                self.sysrepo_port = self.next_free_port
                self.next_free_port += 1
                self.sc = pkg5unittest.SysrepoController(self.default_sc_conf,
                    self.sysrepo_port, runtime_dir, testcase=self)
                self.register_apache_controller("sysrepo", self.sc)
                self.sc.start()

        def test_0_sysrepo(self):
                """A very basic test to see that we can start the sysrepo."""

                # ensure we fail when not supplying the required argument
                self.sysrepo("", exit=2, fill_missing_args=False)

                self.sysrepo("")
                self._start_sysrepo()
                self.sc.stop()

        def test_1_sysrepo_usage(self):
                """Tests that we show a usage message."""

                ret, output = self.sysrepo("--help", out=True, exit=2)
                self.assertTrue("Usage:" in output,
                    "No usage string printed: {0}".format(output))

        def test_2_invalid_root(self):
                """We return an error given an invalid image root"""

                for invalid_root in ["/dev/null", "/etc/passwd", "/proc"]:
                        ret, output, err = self.sysrepo("-R {0}".format(invalid_root),
                            out=True, stderr=True, exit=1)
                        self.assertTrue(invalid_root in err, "error message "
                            "did not contain {0}: {1}".format(invalid_root, err))

        def test_3_invalid_cache_dir(self):
                """We return an error given an invalid cache_dir"""

                for invalid_cache in ["/dev/null", "/etc/passwd"]:
                        ret, output, err = self.sysrepo("-c {0}".format(invalid_cache),
                            out=True, stderr=True, exit=1)
                        self.assertTrue(invalid_cache in err, "error message "
                            "did not contain {0}: {1}".format(invalid_cache, err))

        def test_4_invalid_hostname(self):
                """We return an error given an invalid hostname"""

                for invalid_host in ["1.2.3.4.5.6", "pkgsysrepotestname", "."]:
                        ret, output, err = self.sysrepo("-h {0}".format(invalid_host),
                            out=True, stderr=True, exit=1)
                        self.assertTrue(invalid_host in err, "error message "
                            "did not contain {0}: {1}".format(invalid_host, err))

        def test_5_invalid_logs_dir(self):
                """We return an error given an invalid logs_dir"""

                for invalid_log in ["/dev/null", "/etc/passwd"]:
                        ret, output, err = self.sysrepo("-l {0}".format(invalid_log),
                            out=True, stderr=True, exit=1)
                        self.assertTrue(invalid_log in err, "error message "
                            "did not contain {0}: {1}".format(invalid_log, err))

                for invalid_log in ["/proc"]:
                        port = self.next_free_port
                        ret, output, err = self.sysrepo("-l {0} -p {1}".format(
                            invalid_log, port), out=True, stderr=True, exit=0)
                        self.assertRaises(pkg5unittest.ApacheStateException,
                            self._start_sysrepo)
                        self.sc.stop()

        def test_6_invalid_port(self):
                """We return an error given an invalid port"""

                for invalid_port in [999999, "bobcat", "-1234"]:
                        ret, output, err = self.sysrepo("-p {0}".format(invalid_port),
                            out=True, stderr=True, exit=1)
                        self.assertTrue(str(invalid_port) in err, "error message "
                            "did not contain {0}: {1}".format(invalid_port, err))

        def test_7_invalid_runtime_dir(self):
                """We return an error given an invalid runtime_dir"""

                for invalid_runtime in ["/dev/null", "/etc/passwd", "/proc"]:
                        ret, output, err = self.sysrepo("-r {0}".format(
                            invalid_runtime), out=True, stderr=True, exit=1)
                        self.assertTrue(invalid_runtime in err, "error message "
                            "did not contain {0}: {1}".format(invalid_runtime, err))

        def test_8_invalid_cache_size(self):
                """We return an error given an invalid cache_size"""

                for invalid_csize in [0, "cats", "-1234"]:
                        ret, output, err = self.sysrepo("-s {0}".format(invalid_csize),
                            out=True, stderr=True, exit=1)
                        self.assertTrue(str(invalid_csize) in err, "error message "
                            "did not contain {0}: {1}".format(invalid_csize, err))

        def test_9_invalid_templates_dir(self):
                """We return an error given an invalid templates_dir"""

                for invalid_tmp in ["/dev/null", "/etc/passwd", "/proc"]:
                        ret, output, err = self.sysrepo("-t {0}".format(invalid_tmp),
                            out=True, stderr=True, exit=1)
                        self.assertTrue(invalid_tmp in err, "error message "
                            "did not contain {0}: {1}".format(invalid_tmp, err))

        def test_10_invalid_http_timeout(self):
                """We return an error given an invalid http_timeout"""

                for invalid_time in ["cats", "0", "-1"]:
                        ret, output, err = self.sysrepo("-T {0}".format(invalid_time),
                            out=True, stderr=True, exit=1)
                        self.assertTrue("http_timeout" in err, "error message "
                             "did not contain http_timeout: {0}".format(err))

        def test_11_invalid_proxies(self):
                """We return an error given invalid proxies"""

                for invalid_proxy in ["http://", "https://foo.bar", "-1",
                    "http://user:password@hostname:3128"]:
                        ret, output, err = self.sysrepo("-w {0}".format(invalid_proxy),
                            out=True, stderr=True, exit=1)
                        self.assertTrue("http_proxy" in err, "error message "
                             "did not contain http_proxy: {0}".format(err))
                        ret, output, err = self.sysrepo("-W {0}".format(invalid_proxy),
                            out=True, stderr=True, exit=1)
                        self.assertTrue("https_proxy" in err, "error message "
                             "did not contain https_proxy: {0}".format(err))


class TestDetailedSysrepoCli(pkg5unittest.ApacheDepotTestCase):

        persistent_setup = True

        sample_pkg = """
            open sample@1.0,5.11-0
            add file tmp/sample_file mode=0444 owner=root group=bin path=/usr/bin/sample
            close"""

        new_pkg = """
            open new@1.0,5.11-0
            add file tmp/sample_file mode=0444 owner=root group=bin path=/usr/bin/new
            close"""

        misc_files = ["tmp/sample_file"]

        def setUp(self):
                # see test_7_response_overlaps
                self.overlap_pubs = ["versions", "versionsX", "syspub",
                    "Xsyspub"]
                pubs = ["test1", "test2"]
                pubs.extend(self.overlap_pubs)
                pkg5unittest.ApacheDepotTestCase.setUp(self, pubs,
                    start_depots=True)

                # Most tests use a single system-repository instance, "sc",
                # but some also use an alternative instance, "alt_sc".
                self.sc = None
                self.alt_sc = None

                self.default_sc_runtime = os.path.join(self.test_root,
                    "sysrepo_runtime")
                # add another level to the tree used to store the alternative
                # runtime dir, since the sysrepo writes
                # <runtime>/../sysrepo_httpd.pid, which would clash with the
                # default instance
                self.alt_sc_runtime = os.path.sep.join([self.test_root,
                    "alt_sysrepo_runtime", "alt"])
                self.default_sc_conf = os.path.join(self.default_sc_runtime,
                    "sysrepo_httpd.conf")
                self.alt_sc_conf = os.path.join(self.alt_sc_runtime,
                    "sysrepo_httpd.conf")
                self.default_sc_p5s = os.path.sep.join([self.default_sc_runtime,
                    "htdocs", "syspub", "0", "index.html"])
                self.make_misc_files(self.misc_files)
                self.durl1 = self.dcs[1].get_depot_url()
                self.rurl1 = self.dcs[1].get_repo_url()
                self.durl2 = self.dcs[2].get_depot_url()
                for dc_num in self.dcs:
                        durl = self.dcs[dc_num].get_depot_url()
                        self.pkgsend_bulk(durl, self.sample_pkg)

        def _start_sysrepo(self, runtime_dir=None, alt=False):
                """Starts a system repository instance, either using the default
                or alternative configurations."""
                if not runtime_dir:
                        runtime_dir = self.default_sc_runtime
                self.sysrepo_port = self.next_free_port
                self.next_free_port += 1

                if alt:
                        conf = self.alt_sc_conf
                        runtime_dir = self.alt_sc_runtime
                        self.alt_sc = pkg5unittest.SysrepoController(conf,
                            self.sysrepo_port, runtime_dir, testcase=self)
                        self.register_apache_controller("alt_sysrepo",
                            self.alt_sc)
                        self.alt_sc.start()
                else:
                        self.sc = pkg5unittest.SysrepoController(
                            self.default_sc_conf,
                            self.sysrepo_port, runtime_dir, testcase=self)
                        self.register_apache_controller("sysrepo",
                            self.sc)
                        self.sc.start()

        def test_1_substring_proxy(self):
                """We can proxy publishers that are substrings of each other"""
                # XXX not implemented yet
                pass

        def test_2_invalid_proxy(self):
                """We return an invalid response for urls we don't proxy"""
                # XXX not implemented yet
                pass

        def test_3_cache_dir(self):
                """Our cache_dir value is used"""

                self.image_create(prefix="test1", repourl=self.durl1)

                cache_dir = os.path.join(self.test_root, "t_sysrepo_cache")
                port = self.next_free_port
                self.sysrepo("-R {0} -c {1} -p {2}".format(self.get_img_path(),
                    cache_dir, port))
                self._start_sysrepo()

                # 1. grep for the Cache keyword in the httpd.conf
                self.file_contains(self.default_sc_conf, "CacheEnable disk /")
                self.file_doesnt_contain(self.default_sc_conf,
                    "CacheEnable mem")
                self.file_doesnt_contain(self.default_sc_conf, "MCacheSize")
                self.file_contains(self.default_sc_conf, "CacheRoot {0}".format(
                    cache_dir))

                # 2. publish a file, then install using the proxy
                # check that the proxy has written some content into the cache
                # XXX not implemented yet.
                self.sc.stop()

                # 3. use urllib to pull the url for the file again, verify
                # we've got a cache header on the HTTP response
                # XXX not implemented yet.

                # 4. ensure memory and None settings are written
                cache_dir = "None"
                self.sysrepo("-c {0} -p {1}".format(cache_dir, port))
                self.file_doesnt_contain(self.default_sc_conf, "CacheEnable")

                cache_dir = "memory"
                self.sysrepo("-c {0} -p {1}".format(cache_dir, port))
                self.file_doesnt_contain(self.default_sc_conf,
                    "CacheEnable disk")
                self.file_contains(self.default_sc_conf, "CacheEnable mem")
                self.file_contains(self.default_sc_conf, "MCacheSize")

        def test_4_logs_dir(self):
                """Our logs_dir value is used"""

                self.image_create(prefix="test1", repourl=self.durl1)

                logs_dir = os.path.join(self.test_root, "t_sysrepo_logs")
                port = self.next_free_port
                self.sysrepo("-l {0} -p {1}".format(logs_dir, port))
                self._start_sysrepo()

                # 1. grep for the logs dir in the httpd.conf
                self.file_contains(self.default_sc_conf,
                    "ErrorLog \"{0}/error_log\"".format(logs_dir))
                self.file_contains(self.default_sc_conf,
                    "CustomLog \"{0}/access_log\"".format(logs_dir))
                # 2. verify our log files exist once the sysrepo has started
                for name in ["error_log", "access_log"]:
                        os.path.exists(os.path.join(logs_dir, name))
                self.sc.stop()

        def test_5_port_host(self):
                """Our port value is used"""
                self.image_create(prefix="test1", repourl=self.durl1)

                port = self.next_free_port
                self.sysrepo("-p {0} -h localhost".format(port))
                self._start_sysrepo()
                self.file_contains(self.default_sc_conf, "Listen localhost:{0}".format(
                    port))
                self.sc.stop()

        def test_6_permissions(self):
                """Our permissions are correct on all generated files"""

                # 1. check the permissions
                # XXX not implemented yet.
                pass

        def test_7_response_overlaps(self):
                """We can proxy publishers that are == or substrings of our
                known responses"""

                self.image_create(prefix="test1", repourl=self.durl1)

                overlap_dcs = []
                # identify the interesting repos, those that we've configured
                # using publisher prefixes that match our responses
                for dc_num in [num for num in self.dcs if
                    (self.dcs[num].get_property("publisher", "prefix")
                    in self.overlap_pubs)]:
                        dc = self.dcs[dc_num]
                        name = dc.get_property("publisher", "prefix")
                        overlap_dcs.append(dc)
                        # we need to use -R here since it doesn't get added
                        # automatically by self.pkg() because we've got
                        # "versions" as one of the CLI args (it being an
                        # overlapping publisher name)
                        self.pkg("-R {img} set-publisher -g {url} {pub}".format(
                            img=self.get_img_path(),
                            url=dc.get_repo_url(), pub=name))

                # Start a system repo based on the configuration above
                self.sysrepo("")
                self._start_sysrepo()

                # attempt to create images using the sysrepo
                for dc in overlap_dcs:
                        pub = dc.get_property("publisher", "prefix")
                        hash = hashlib.sha1(misc.force_bytes("file://" +
                            dc.get_repodir().rstrip("/"))).hexdigest()
                        url = "http://localhost:{port}/{pub}/{hash}/".format(
                            port=self.sysrepo_port, hash=hash,
                            pub=pub)
                        self.set_img_path(os.path.join(self.test_root,
                            "sysrepo_image"))
                        self.pkg_image_create(prefix=pub, repourl=url)
                        self.pkg("-R {0} install sample".format(self.get_img_path()))

                self.sc.stop()

        def test_8_file_publisher(self):
                """A proxied file publisher works as a normal file publisher,
                including package archives"""
                #
                # The standard system publisher client code does not use the
                # "publisher/0" response, so we need this test to exercise that.

                self.image_create(prefix="test1", repourl=self.durl1)

                # create a version of this url with a symlink, to ensure we
                # can follow links in urls
                urlresult = urlparse(self.rurl1)
                symlink_path = os.path.join(self.test_root, "repo_symlink")
                os.symlink(urlresult.path, symlink_path)
                symlinked_url = "file://{0}".format(symlink_path)

                # create a p5p archive
                p5p_path = os.path.join(self.test_root,
                    "test_8_file_publisher_archive.p5p")
                p5p_url = "file://{0}".format(p5p_path)
                self.pkgrecv(server_url=self.durl1, command="-a -d {0} sample".format(
                    p5p_path))

                for file_url in [self.rurl1, symlinked_url, p5p_url]:
                        self.image_create(prefix="test1", repourl=self.durl1)
                        self.pkg("set-publisher -g {0} test1".format(file_url))
                        self.sysrepo("")
                        self._start_sysrepo()

                        hash = hashlib.sha1(misc.force_bytes(
                            file_url.rstrip("/"))).hexdigest()
                        url = "http://localhost:{port}/test1/{hash}/".format(
                            port=self.sysrepo_port, hash=hash)
                        self.pkg_image_create(prefix="test1", repourl=url)
                        self.pkg("install sample")
                        self.pkg("contents -rm sample")
                        # the sysrepo doesn't support search ops for file repos
                        self.pkg("search -r sample", exit=1)
                        self.sc.stop()

        def test_9_unsupported_publishers(self):
                """Ensure we fail when asked to proxy < v4 file repos"""

                v3_repo_root = os.path.join(self.test_root, "sysrepo_test_9")
                os.mkdir(v3_repo_root)
                v3_repo_path = os.path.join(v3_repo_root, "repo")

                self.pkgrepo("create --version 3 {0}".format(v3_repo_path))
                self.pkgrepo("-s {0} set publisher/prefix=foo".format(v3_repo_path))
                for path in [v3_repo_path]:
                        self.image_create(repourl="file://{0}".format(path))
                        self.sysrepo("-R {0}".format(self.img_path()), exit=1)

        def test_10_missing_file_repo(self):
                """Ensure we print the right error message in the face of
                a missing repository."""
                repo_path = os.path.join(self.test_root, "test_10_missing_repo")
                self.pkgrepo("create {0}".format(repo_path))
                self.pkgrecv(server_url=self.durl1, command="-d {0} sample".format(
                    repo_path))
                self.pkgrepo("-s {0} set publisher/prefix=foo".format(repo_path))
                self.pkgrepo("-s {0} rebuild".format(repo_path))
                self.image_create(repourl="file://{0}".format(repo_path))
                shutil.rmtree(repo_path)
                ret, output, err = self.sysrepo("-R {0}".format(self.img_path()),
                    out=True, stderr=True, exit=1)
                # restore our image before going any further
                self.assertTrue("does not exist" in err, "unable to find expected "
                    "error message in stderr: {0}".format(err))

        def test_11_proxy_args(self):
                """Ensure we write configuration to tell Apache to use a remote
                proxy when proxying requests when using -w or -W"""
                self.image_create(prefix="test1", repourl=self.durl1)

                for arg, directives in [
                    ("-w http://foo", ["ProxyRemote http http://foo"]),
                    ("-W http://foo", ["ProxyRemote https http://foo"]),
                    ("-w http://foo -W http://foo",
                    ["ProxyRemote http http://foo",
                    "ProxyRemote https http://foo"])]:
                            self.sysrepo(arg)
                            for d in directives:
                                    self.file_contains(self.default_sc_conf, d)

        def test_12_cache_dir_permissions(self):
                """Our cache_dir permissions and ownership are verified"""

                exp_uid = portable.get_user_by_name(SYSREPO_USER, None, False)
                self.image_create(prefix="test1", repourl=self.durl1)

                cache_dir = os.path.join(self.test_root, "t_sysrepo_cache")
                # first verify that the user running the test has permissions
                try:
                        os.mkdir(cache_dir)
                        os.chown(cache_dir, exp_uid, 1)
                        os.rmdir(cache_dir)
                except OSError as e:
                        if e.errno == errno.EPERM:
                                raise pkg5unittest.TestSkippedException(
                                    "User running test does not have "
                                    "permissions to chown to uid {0}".format(exp_uid))
                        raise

                # Run sysrepo to create cache directory
                port = self.next_free_port
                self.sysrepo("-R {0} -c {1} -p {2}".format(self.get_img_path(),
                    cache_dir, port))

                self._start_sysrepo()
                self.sc.stop()

                # Remove cache directory
                os.rmdir(cache_dir)

                # Again run sysrepo and then verify permissions
                cache_dir = os.path.join(self.test_root, "t_sysrepo_cache")
                port = self.next_free_port
                self.sysrepo("-R {0} -c {1} -p {2}".format(self.get_img_path(),
                    cache_dir, port))
                self._start_sysrepo()

                # Wait for service to come online. Try for 30 seconds.
                count = 0
                while (count < 10):
                        time.sleep(3)
                        count = count + 1
                        if (os.access(cache_dir, os.F_OK)):
                                break

                # Verify cache directory exists.
                self.assertTrue(os.access(cache_dir, os.F_OK))

                filemode = stat.S_IMODE(os.stat(cache_dir).st_mode)
                self.assertEqualDiff(0o755, filemode)
                uid = os.stat(cache_dir)[4]
                exp_uid = portable.get_user_by_name(SYSREPO_USER, None, False)
                self.assertEqualDiff(exp_uid, uid)

                self.sc.stop()

        def test_13_changing_p5p(self):
                """Ensure that when a p5p file changes from beneath us, or
                disappears, the system repository and any pkg(5) clients
                react correctly."""

                # create a p5p archive
                p5p_path = os.path.join(self.test_root,
                    "test_12_changing_p5p_archive.p5p")
                p5p_url = "file://{0}".format(p5p_path)
                self.pkgrecv(server_url=self.durl1, command="-a -d {0} sample".format(
                    p5p_path))

                # configure an image from which to generate a sysrepo config
                self.image_create(prefix="test1", repourl=self.durl1)
                self.pkg("set-publisher -g {0} test1".format(p5p_url))
                self.sysrepo("")
                self._start_sysrepo()

                # create an image which uses the system publisher
                hash = hashlib.sha1(misc.force_bytes(p5p_url.rstrip("/"))).hexdigest()
                url = "http://localhost:{port}/test1/{hash}/".format(
                    port=self.sysrepo_port, hash=hash)

                self.debug("using {0} as repo url".format(url))
                self.pkg_image_create(prefix="test1", repourl=url)
                self.pkg("install sample")

                # modify the p5p file - publish a new package and an
                # update of the existing package, then recreate the p5p file.
                self.pkgsend_bulk(self.durl1, self.new_pkg)
                self.pkgsend_bulk(self.durl1, self.sample_pkg)
                os.unlink(p5p_path)
                self.pkgrecv(server_url=self.durl1,
                    command="-a -d {0} sample new".format(p5p_path))

                # ensure we can install our new packages through the system
                # publisher url
                self.pkg("install new")
                self.pkg("publisher")

                # remove the p5p file, which should still allow us to uninstall
                renamed_p5p_path = p5p_path + ".renamed"
                os.rename(p5p_path, renamed_p5p_path)
                self.pkg("uninstall new")

                # ensure we can't install the packages or perform operations
                # that require the p5p file to be present
                self.pkg("install new", exit=1)
                self.pkg("contents -rm new", exit=1)

                # replace the p5p file, and ensure the client can install again
                os.rename(renamed_p5p_path, p5p_path)
                self.pkg("install new")
                self.pkg("contents -rm new")

                self.sc.stop()

        def test_14_bad_input(self):
                """Tests the system repository with some bad input: wrong
                paths, unicode in urls, and some very long urls to ensure
                the responses are as expected."""
                # create a p5p archive
                p5p_path = os.path.join(self.test_root,
                    "test_13_bad_input.p5p")
                p5p_url = "file://{0}".format(p5p_path)
                self.pkgrecv(server_url=self.durl1, command="-a -d {0} sample".format(
                    p5p_path))
                p5p_hash = hashlib.sha1(misc.force_bytes(
                    p5p_url.rstrip("/"))).hexdigest()
                file_url = self.dcs[2].get_repo_url()
                file_hash = hashlib.sha1(misc.force_bytes(
                    file_url.rstrip("/"))).hexdigest()

                # configure an image from which to generate a sysrepo config
                self.image_create(prefix="test1", repourl=self.durl1)

                self.pkg("set-publisher -p {0}".format(file_url))
                self.pkg("set-publisher -g {0} test1".format(p5p_url))
                self.sysrepo("")
                self._start_sysrepo()

                # some incorrect urls
                queries_404 = [
                    "noodles"
                    "/versions/1"
                    "/"
                ]

                # a place to store some long urls
                queries_414 = []

                # add urls and some unicode.  We test a file repository,
                # which makes sure Apache can deal with the URLs appropriately,
                # as well as a p5p repository, exercising our mod_wsgi app.
                for hsh, pub in [("test1", p5p_hash), ("test2", file_hash)]:
                        queries_404.append("{0}/{1}/catalog/1/ΰŇﺇ⊂⏣⊅ℇ".format(
                            pub, hsh))
                        queries_404.append("{0}/{1}/catalog/1/{2}".format(
                            pub, hsh, "f" + "u" * 1000))
                        queries_414.append("{0}/{1}/catalog/1/{2}".format(
                            pub, hsh, "f" * 900000 + "u"))

                def test_response(part, code):
                        """Given a url substring and an expected error code,
                        check that the system repository returns that code
                        for a url constructed from that part."""
                        url = "http://localhost:{0}/{1}".format(
                            self.sysrepo_port, part)
                        try:
                                resp =  urlopen(url, None, None)
                        except HTTPError as e:
                                if e.code != code:
                                        self.assertTrue(False,
                                            "url {0} returned: {1}".format(url, e))

                for url_part in queries_404:
                        # Python 3's http.client try to encode the url with
                        # ASCII encoding, so non-ASCII characters should have
                        # been eliminated earlier.
                        test_response(misc.force_bytes(url_part), 404)
                for url_part in queries_414:
                        test_response(url_part, 414)
                self.sc.stop()

        def test_15_unicode(self):
                """Tests the system repository with some unicode paths to p5p
                files."""
                # Running test on remote machines, the locale is usally "C",
                # then the file system encoding will be "ascii" and os.mkdir
                # will fail with some unicode characters in Python 3 because
                # os.mkdir uses the file system encoding. We don't have a way
                # to set the file system encoding in Python, so we just skip.
                if six.PY3 and sys.getfilesystemencoding() == "ascii":
                        return
                unicode_str = "ΰŇﺇ⊂⏣⊅ℇ"
                unicode_dir = os.path.join(self.test_root, unicode_str)
                os.mkdir(unicode_dir)

                # create paths to p5p files, using unicode dir or file names
                p5p_unicode_dir = os.path.join(unicode_dir,
                    "test_14_unicode.p5p")
                p5p_unicode_file = os.path.join(self.test_root,
                    "{0}.p5p".format(unicode_str))

                for p5p_path in [p5p_unicode_dir, p5p_unicode_file]:
                        p5p_url = "file://{0}".format(p5p_path)
                        self.pkgrecv(server_url=self.durl1,
                            command="-a -d {0} sample".format(p5p_path))
                        p5p_hash = hashlib.sha1(misc.force_bytes(
                            p5p_url.rstrip("/"))).hexdigest()

                        self.image_create()
                        self.pkg("set-publisher -p {0}".format(p5p_url))

                        self.sysrepo("")
                        self._start_sysrepo()

                        # ensure we can get content from the p5p file
                        for path in ["catalog/1/catalog.attrs",
                            "catalog/1/catalog.base.C",
                            "file/1/f5da841b7c3601be5629bb8aef928437de7d534e"]:
                                url = "http://localhost:{0}/test1/{1}/{2}".format(
                                    self.sysrepo_port, p5p_hash, path)
                                resp = urlopen(url, None, None)
                                self.debug(resp.readlines())

                        self.sc.stop()

        def test_16_config_cache(self):
                """We can load/store our configuration cache correctly."""

                cache_path = "var/cache/pkg/sysrepo_pub_cache.dat"
                full_cache_path = os.path.join(self.get_img_path(), cache_path)
                sysrepo_runtime_dir = os.path.join(self.test_root,
                    "sysrepo_runtime")
                sysrepo_conf = os.path.join(sysrepo_runtime_dir,
                    "sysrepo_httpd.conf")

                # a basic check that the config cache looks sane
                self.image_create(prefix="test1", repourl=self.durl1)
                self.file_doesnt_exist(cache_path)

                self.sysrepo("", stderr=True)
                self.assertTrue("Unable to load config" not in self.output)
                self.assertTrue("Unable to store config" not in self.output)
                self.file_exists(cache_path)
                self.file_contains(sysrepo_conf, self.durl1)
                self.file_remove(cache_path)

                # install some sample packages to our image, just to ensure
                # that sysrepo doesn't mind, and cache creation works
                self.pkg("install sample")
                self.sysrepo("", stderr=True)
                self.assertTrue("Unable to load config" not in self.output)
                self.assertTrue("Unable to store config" not in self.output)
                self.file_exists(cache_path)
                self.file_contains(sysrepo_conf, self.durl1)
                self.file_remove(cache_path)

                # ensure we get warnings when we can't load/store the config
                os.makedirs(full_cache_path)
                self.sysrepo("", stderr=True)
                self.assertTrue("Unable to load config" in self.errout)
                self.assertTrue("Unable to store config" in self.errout)
                self.file_contains(sysrepo_conf, self.durl1)
                os.rmdir(full_cache_path)

                # ensure we get warnings when loading a corrupt cache
                self.sysrepo("")
                self.file_append(cache_path, "noodles")
                self.sysrepo("", stderr=True)
                self.assertTrue("Invalid config cache file at" in self.errout)
                # we should have overwritten the corrupt cache, so check again
                self.sysrepo("", stderr=True)
                self.assertTrue("Invalid config cache file at" not in self.errout)
                self.file_contains(cache_path, self.durl1)
                self.file_remove(cache_path)

                # ensure that despite valid JSON in the cache, we still
                # treat it as corrupt, and clobber the old cache
                rubbish = {"food preference": "I like noodles."}
                other = ["nonsense here"]
                with open(full_cache_path, "w") as cache_file:
                        simplejson.dump((rubbish, other), cache_file)
                self.sysrepo("", stderr=True)
                self.assertTrue("Invalid config cache at" in self.errout)
                self.file_doesnt_contain(cache_path, "noodles")
                self.file_contains(cache_path, self.durl1)
                self.file_contains(sysrepo_conf, self.durl1)

                # ensure we get a new cache on publisher modification
                self.file_doesnt_contain(cache_path, self.rurl1)
                self.pkg("set-publisher -g {0} test1".format(self.rurl1))
                self.file_doesnt_exist(cache_path)
                self.sysrepo("")
                self.file_contains(cache_path, [self.rurl1, self.durl1])

                # record the last modification time of the cache
                st_cache = os.lstat(full_cache_path)
                mtime = st_cache.st_mtime

                # no image modification, so no new config file
                self.sysrepo("")
                self.assertTrue(mtime == os.lstat(full_cache_path).st_mtime,
                    "Changed mtime of cache despite no image config change")

                # load the config from the cache, remove a URI then save
                # it - despite being well-formed, the cache doesn't contain the
                # same configuration as the image, simulating an older version
                # of pkg(1) having changed publisher configuration.
                with open(full_cache_path, "r") as cache_file:
                        uri_pub_map, no_uri_pubs = simplejson.load(cache_file)

                with open(full_cache_path, "w") as cache_file:
                        del uri_pub_map[self.durl1]
                        simplejson.dump((uri_pub_map, no_uri_pubs), cache_file,
                            indent=True)
                # make sure we've definitely broken it
                self.file_doesnt_contain(cache_path, self.durl1)

                # we expect an 'invalid config cache' message, and a new cache
                # written with correct content.
                self.sysrepo("", stderr=True)
                self.assertTrue("Invalid config cache at" in self.errout)
                self.file_contains(cache_path, self.durl1)
                self.sysrepo("")

                # rename the cache file, then symlink it
                os.rename(full_cache_path, full_cache_path + ".new")
                os.symlink(full_cache_path + ".new", full_cache_path)
                self.pkg("set-publisher -G {0} test1".format(self.durl1))
                # by running pkg set-publisher, we should have removed the
                # symlink
                self.file_doesnt_exist(cache_path)
                # replace the symlink
                os.symlink(full_cache_path + ".new", full_cache_path)

                self.sysrepo("", stderr=True)
                self.assertTrue("Unable to load config" in self.errout)
                self.assertTrue("not a regular file" in self.errout)
                self.assertTrue("Unable to store config" in self.errout)
                # our symlinked cache should be untouched, and still contain
                # rurl1, despite it being absent from our actual configuration.
                self.file_contains(cache_path, self.durl1)
                self.file_doesnt_contain(sysrepo_conf, self.durl1)

                # check that an image with no publishers works
                self.pkg("unset-publisher test1")
                self.pkg("publisher", out=True, stderr=True)
                self.file_doesnt_exist(cache_path)
                self.sysrepo("", stderr=True)
                self.assertTrue("Unable to load config" not in self.output)
                self.assertTrue("Unable to store config" not in self.output)
                self.file_doesnt_contain(sysrepo_conf, self.durl1)

                # check that removing packages doesn't impact the cache
                self.pkg("uninstall sample")
                self.sysrepo("", stderr=True)
                self.assertTrue("Unable to load config" not in self.output)
                self.assertTrue("Unable to store config" not in self.output)
                self.file_remove(cache_path)
                self.sysrepo("", stderr=True)
                self.assertTrue("Unable to load config" not in self.output)
                self.assertTrue("Unable to store config" not in self.output)

                # check that when a file-repository is inaccessible, the
                # sysrepo_httpd.conf generated from the cache remains identical
                self.pkg("set-publisher -g {0} test1".format(self.rurl1))
                self.sysrepo("", stderr=True)
                saved_sysrepo_conf = os.path.join(self.test_root,
                    "test_16_config_cache_sysrepo_httpd.conf.old")
                os.rename(sysrepo_conf, saved_sysrepo_conf)
                # Make the file repository inaccessible (simulating eg. an
                # offline NFS server)
                # We should still be able to generate the same sysrepo config
                # using our cached information.
                repo_dir = self.dcs[1].get_repodir()
                os.rename(repo_dir, repo_dir + ".new")
                try:
                        self.sysrepo("", stderr=True)
                        self.assertTrue(misc.get_data_digest(sysrepo_conf,
                            hash_func=DEFAULT_HASH_FUNC)[0] ==
                            misc.get_data_digest(saved_sysrepo_conf,
                            hash_func=DEFAULT_HASH_FUNC)[0],
                            "system repository configuration changed "
                            "unexpectedly.")
                finally:
                        os.rename(repo_dir + ".new", repo_dir)

        def test_17_proxy(self):
                """ Ensure that the system repository can proxy access
                through another proxy."""

                self.image_create(prefix="test1", repourl=self.durl1)

                # Start a system repository instance that we will use as a
                # convenient way to configure a simple http proxy
                alt_logs_dir = os.path.join(self.test_root, "alt_sysrepo_logs")
                self.sysrepo("-r {0} -l {1}".format(self.alt_sc_runtime,
                    alt_logs_dir))
                self._start_sysrepo(alt=True)
                alt_sc_port = self.sysrepo_port

                # Start another system-repository using the 1st sysrepo instance
                # as a http proxy
                def_logs_dir = os.path.join(self.test_root, "def_sysrepo_logs")
                self.sysrepo("-r {0} -w http://localhost:{1} -l {2}".format(
                    self.default_sc_runtime, alt_sc_port, def_logs_dir))
                self._start_sysrepo()

                # check the configuration
                self.file_contains(self.default_sc_conf,
                    "ProxyRemote http http://localhost:{0}".format(alt_sc_port))

                # configure an image to use the system repository
                saved_sysrepo_env = os.environ.get("PKG_SYSREPO_URL")
                os.environ["PKG_SYSREPO_URL"] = "http://localhost:{0}".format(
                    self.sysrepo_port)
                self.image_create()
                self.pkg("set-property use-system-repo True")
                self.pkg("refresh")
                self.pkg("list -af")

                # Both logs should show access requests for our catalogs, but
                # only the system-repository this image is configured to use
                # should show access requests for /versions/0 (the versions
                # response of  the system repository itself, not the pkg.depot
                # we're pointing at via the http proxy)
                alt_log = os.path.join(alt_logs_dir, "access_log")
                def_log = os.path.join(def_logs_dir, "access_log")

                self.file_contains(alt_log, "catalog/1/catalog.attrs")
                self.file_contains(def_log, "catalog/1/catalog.attrs")
                self.file_doesnt_contain(alt_log, "GET /versions/0/")
                self.file_contains(def_log, "GET /versions/0/")

                # When we disable the proxy, pkg operations through the system
                # repository are affected
                self.alt_sc.stop()

                self.image_create()
                self.pkg("set-property use-system-repo True")
                ret, out, err = self.pkg("refresh", exit=1, stderr=True,
                    out=True)
                self.assertTrue("503 reason: Service Unavailable" in err)

                # By enabling the remote proxy, the system-repository should
                # now be able to proxy this resource.
                self.alt_sc.start()

                self.pkg("set-property use-system-repo True")
                self.pkg("refresh")

                self.alt_sc.stop()
                self.sc.stop()

                if saved_sysrepo_env:
                        os.environ["PKG_SYSREPO_URL"] = saved_sysrepo_env
                else:
                        del os.environ["PKG_SYSREPO_URL"]

        def test_17_granular_proxies(self):
                """Ensure that when an image has --proxy values set, that we add
                appropriate ProxyRemote directives for those publishers."""

                # We use --no-refresh because our proxy doesn't exist
                self.image_create()
                self.pkg("set-publisher --no-refresh -g {0} "
                    "--proxy http://foobar test1".format(self.durl1))

                self.sysrepo("")
                self.file_contains(self.default_sc_conf,
                    "ProxyRemote {0} http://foobar".format(self.durl1))

                self.pkg("set-publisher --no-refresh -g {0} "
                    "--proxy http://bar test2".format(self.durl2))

                self.sysrepo("")
                self.file_contains(self.default_sc_conf,
                    "ProxyRemote {0} http://foobar".format(self.durl1))
                self.file_contains(self.default_sc_conf,
                    "ProxyRemote {0} http://bar".format(self.durl2))

                # Ensure we fail when an image is set with a proxy we don't
                # support.
                self.image_create()
                self.pkg("set-publisher --no-refresh -g {0} "
                    "--proxy http://user:password@foobar test1".format(self.durl1))
                self.sysrepo("", exit=1)


class TestP5pWsgi(pkg5unittest.SingleDepotTestCase):
        """A class to directly exercise the p4p mod_wsgi application outside
        of Apache and the system repository itself.

        By calling the web application directly, we have a little more
        flexibility when writing tests.  Other system-repository tests will
        exercise much of the mod_wsgi configuration and framework, but these
        tests will be easier to debug and faster to run.

        Note that since we call the web application directly, the web app can
        intentionally emit some tracebacks to stderr, which will be seen by
        the test framework."""

        persistent_setup = False

        sample_pkg = """
            open sample@1.0,5.11-0
            add file tmp/sample_file mode=0444 owner=root group=bin path=/usr/bin/sample
            close"""

        new_pkg = """
            open new@1.0,5.11-0
            add file tmp/sample_file mode=0444 owner=root group=bin path=/usr/bin/new
            close"""

        misc_files = { "tmp/sample_file": "carrots" }

        def setUp(self):
                pkg5unittest.SingleDepotTestCase.setUp(self, start_depot=True)
                self.image_create()

                # we have to dynamically load the mod_wsgi webapp, since it
                # lives outside our normal search path
                mod_name = "sysrepo_p5p"
                src_name = "{0}.py".format(mod_name)
                sysrepo_p5p_file = open(os.path.join(self.sysrepo_template_dir,
                    src_name))
                self.sysrepo_p5p = imp.load_module(mod_name, sysrepo_p5p_file,
                    src_name, ("py", "r", imp.PY_SOURCE))

                # now create a simple p5p file that we can use in our tests
                self.make_misc_files(self.misc_files)
                self.pkgsend_bulk(self.durl, self.sample_pkg)
                self.pkgsend_bulk(self.durl, self.new_pkg)

                self.p5p_path = os.path.join(self.test_root,
                    "mod_wsgi_archive.p5p")

                self.pkgrecv(server_url=self.durl,
                    command="-a -d {0} sample new".format(self.p5p_path))
                self.http_status = ""

        def test_queries(self):
                """Ensure that we return proper HTTP response codes."""

                def start_response(status, response_headers, exc_info=None):
                        """A dummy response function, used to capture output"""
                        self.http_status = status

                environ = {}
                hsh = "123abcdef"
                environ["SYSREPO_RUNTIME_DIR"] = self.test_root
                environ["PKG5_TEST_ENV"] = "True"
                environ[hsh] = self.p5p_path

                def test_query_responses(queries, code, expect_content=False):
                        """Given a list of queries, and a string we expect to
                        appear in each response, invoke the wsgi application
                        with each query and check response codes.  Also check
                        that content was returned or not."""

                        for query in queries:
                                seen_content = False
                                environ["QUERY_STRING"] = unquote(query)
                                self.http_status = ""

                                try:
                                        # The WSGI application writes to stdout
                                        # so to reduce console noise, we
                                        # redirect that temporarily.
                                        saved_stdout = sys.stdout
                                        sys.stdout = six.StringIO()
                                        for item in self.sysrepo_p5p.application(
                                            environ, start_response):
                                                seen_content = item
                                finally:
                                        sys.stdout = saved_stdout

                                self.assertTrue(code in self.http_status,
                                    "Query {0} response did not contain {1}: {2}".format(
                                    query, code, self.http_status))
                                if expect_content:
                                        self.assertTrue(seen_content,
                                            "No content returned for {0}".format(
                                            query))
                                else:
                                        self.assertFalse(seen_content,
                                            "Unexpected content for {0}".format(query))

                # the easiest way to get the name of one of the manifests
                # in the archive is to look for it in the index
                archive = pkg.p5p.Archive(self.p5p_path)
                idx = archive.get_index()
                mf = None
                for item in idx.keys():
                        if item.startswith("publisher/test/pkg/new/"):
                                mf = item.replace(
                                    "publisher/test/pkg/new/", "new@")
                archive.close()

                queries_200 = [
                    # valid file, matches the hash of the content in misc_files
                    "pub=test&hash={0}&path=file/1/f890d49474e943dc07a766c21d2bf35d6e527e89".format(hsh),
                    # valid catalog parts
                    "pub=test&hash={0}&path=catalog/1/catalog.attrs".format(hsh),
                    "pub=test&hash={0}&path=catalog/1/catalog.base.C".format(hsh),
                    # valid manifest
                    "pub=test&hash={0}&path=manifest/0/{1}".format(hsh, mf)
                ]

                queries_404 = [
                    # wrong path
                    "pub=test&hash={0}&path=catalog/1/catalog.attrsX".format(hsh),
                    # invalid publisher
                    "pub=WRONG&hash={0}&path=catalog/1/catalog.attrs".format(hsh),
                    # incorrect path
                    "pub=test&hash={0}&path=file/1/12u3yt123123".format(hsh),
                    # incorrect path (where the first path component is unknown)
                    "pub=test&hash={0}&path=carrots/1/12u3yt123123".format(hsh),
                    # incorrect manifest, with an unknown package name
                    "pub=test&hash={0}&path=manifest/0/foo{1}".format(hsh, mf),
                    # incorrect manifest, with an illegal FMRI
                    "pub=test&hash={0}&path=manifest/0/{1}foo".format(hsh, mf)
                ]

                queries_400 = [
                    # missing publisher (while p5p files can return content
                    # despite no publisher, our mod_wsgi app requires a
                    # publisher)
                    "hash={0}&path=catalog/1/catalog.attrs".format(hsh),
                    # missing path
                    "pub=test&hash={0}".format(hsh),
                    # malformed query
                    "&&???&&&",
                    # no hash key
                    "pub=test&hashX={0}&path=catalog/1/catalog.attrs".format(hsh),
                    # unknown hash value
                    "pub=test&hash=carrots&path=catalog/1/catalog.attrs"
                ]

                test_query_responses(queries_200, "200", expect_content=True)
                test_query_responses(queries_400, "400")
                test_query_responses(queries_404, "404")

                # generally we try to shield users from internal server errors,
                # however in the case of a missing p5p file on the server
                # this seems like the right thing to do, rather than to return
                # a 404.
                # The end result for pkg client with 500 or a 404 code is the
                # same, but the former will result in more useful information
                # in the system-repository error_log.
                os.unlink(self.p5p_path)
                queries_500 = queries_200 + queries_404
                test_query_responses(queries_500, "500")
                # despite the missing p5p file, we should still get 400 errors
                test_query_responses(queries_400, "400")


if __name__ == "__main__":
        unittest.main()

# Vim hints
# vim:ts=8:sw=8:et:fdm=marker
