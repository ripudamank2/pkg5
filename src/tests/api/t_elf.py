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

import unittest
import pkg.elf as elf
import os
import re
import pkg.portable

class TestElf(pkg5unittest.Pkg5TestCase):
        need_ro_data = True

        # If something in this list does not exist, the test_valid_elf
        # tests may fail.  At some point if someone moves paths around in
        # ON, this might fail.  Sorry!
        elf_paths = [
            "/usr/bin/mdb",
            "/usr/bin/__ARCH__/mdb",
            "/usr/lib/libc.so",
            "/usr/lib/__ARCH__/libc.so",
            "/usr/lib/crti.o",
            "/usr/lib/__ARCH__/crti.o",
            "/kernel/drv/__ARCH__/sd",
            "/kernel/fs/__ARCH__/zfs",
            "/usr/kernel/drv/__ARCH__/ksyms",
        ]

        def test_non_elf(self):
                """Test that elf routines gracefully handle non-elf objects."""

                p = "this-is-not-an-elf-file.so"
                self.make_misc_files({p: "this is only a test"})
                os.chdir(self.test_root)
                self.assertEqual(elf.is_elf_object(p), False)
                self.assertRaises(elf.ElfError, elf.get_dynamic, p)
                self.assertRaises(elf.ElfError, elf.get_hashes, p)
                self.assertRaises(elf.ElfError, elf.get_info, p)

        def test_non_existent(self):
                """Test that elf routines gracefully handle ENOENT."""

                os.chdir(self.test_root)
                p = "does/not/exist"
                self.assertRaises(OSError, elf.is_elf_object, p)
                self.assertRaises(OSError, elf.get_dynamic, p)
                self.assertRaises(OSError, elf.get_hashes, p)
                self.assertRaises(OSError, elf.get_info, p)

        def test_valid_elf(self):
                """Test that elf routines work on a small set of objects."""
                arch = pkg.portable.get_isainfo()[0]
                for p in self.elf_paths:
                        p = re.sub("__ARCH__", arch, p)
                        self.debug("testing elf file {0}".format(p))
                        self.assertTrue(os.path.exists(p), "{0} does not exist".format(p))
                        self.assertEqual(elf.is_elf_object(p), True)
                        elf.get_dynamic(p)
                        elf.get_hashes(p)
                        elf.get_info(p)

        def test_valid_elf_hash(self):
                """Test that the elf routines generate the expected hash"""

                o = os.path.join(self.test_root, "ro_data/elftest.so.1")
                d = elf.get_hashes(o, sha1=True, sha256=True)
                self.assertEqual(d['elfhash'],
                    '083308992c921537fd757548964f89452234dd11');
                self.assertEqual(d['pkg.content-type.sha256'],
                    '7c4f1f347b6d6e65e7542ffb21a05471728a80a5449fddd715186c6cbfdba4b0');

        def test_get_hashes_params(self):
                """Test that get_hashes(..) returns checksums according to the
                parameters passed to the method."""

                # Check that the hashes generated have the correct length
                # depending on the algorithm used to generated.
                sha1_len = 40
                sha256_len = 64

                # the default is to return an SHA-1 elfhash only
                d = elf.get_hashes(self.elf_paths[0])
                self.assertTrue(len(d["elfhash"]) == sha1_len)
                self.assertTrue("pkg.content-type.sha256" not in d)

                d = elf.get_hashes(self.elf_paths[0], sha256=True)
                self.assertTrue(len(d["elfhash"]) == sha1_len)
                self.assertTrue(len(d["pkg.content-type.sha256"]) == sha256_len)

                d = elf.get_hashes(self.elf_paths[0], sha1=False, sha256=True)
                self.assertTrue("elfhash" not in d)
                self.assertTrue(len(d["pkg.content-type.sha256"]) == sha256_len)

                d = elf.get_hashes(self.elf_paths[0], sha1=False, sha256=False)
                self.assertTrue("elfhash" not in d)
                self.assertTrue("pkg.content-type.sha256" not in d)

if __name__ == "__main__":
        unittest.main()

# Vim hints
# vim:ts=8:sw=8:et:fdm=marker
