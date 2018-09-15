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
# Copyright (c) 2015, 2016, Oracle and/or its affiliates. All rights reserved.
# Copyright 2018 OmniOS Community Edition (OmniOSce) Association.
#

from __future__ import division, unicode_literals
import six
from pkg._sha512_t import lib, ffi

"""A hash module computes SHA512/t. Now it only supports SHA512/256 and
SHA512/224.

The default hash function is SHA512/256. Change your hash function to
SHA512/224 with the argument t=224 when you create a hash object.

It mimics the behavior of hashlib.sha1 or hashlib.sha256. Hash objects have
methods update(arg), digest() and hexdigest(), and an attribute hash_size.
Also, the accepted input types, error messages and output types are similar
to what hashlib does.

For example:

#>>> import pkg.sha512_t
#>>> a = pkg.sha512_t.SHA512_t()
#>>> a.update("abc")
#>>> a.digest()
#'S\x04\x8e&\x81\x94\x1e\xf9\x9b.)\xb7kL}\xab\xe4\xc2\xd0\xc64\xfcmF\xe0\xe2
#\xf11\x07\xe7\xaf#'
#More condensed:

#>>> pkg.sha512_t.SHA512_t("abc").hexdigest()
#'53048e2681941ef99b2e29b76b4c7dabe4c2d0c634fc6d46e0e2f13107e7af23'

#>>> pkg.sha512_t.SHA512_t(t=224).hexdigest()
#'4634270f707b6a54daae7530460842e20e37ed265ceee9a43e8924aa'
"""


class SHA512_t(object):

    def __init__(self, message=None, t=256):
        self.ctx = ffi.new("SHA2_CTX *")
        if t == 256:
            lib.SHA2Init(lib.SHA512_256, self.ctx)
        elif t == 224:
            lib.SHA2Init(lib.SHA512_224, self.ctx)
        else:
            raise ValueError("The module only supports "
                             "SHA512/256 or SHA512/224.")

        self.hash_size = t

        if message:
                self.update(message)

    def update(self, message):
        """Update the hash object with the string arguments."""
        if six.PY3 and isinstance(message, str):
            raise TypeError("Unicode-objects must be encoded before hashing")
        if not isinstance(message, (six.string_types, bytes)):
            raise TypeError("Message must be string or buffer.")
        if isinstance(message, six.text_type):
            message = message.encode("utf-8")
        lib.SHA2Update(self.ctx, message, len(message))

    def digest(self):
        """Return the digest of the strings passed to the update()
        method so far."""

        digest = ffi.new("unsigned char[]", self.hash_size // 8)
        shc = ffi.new("SHA2_CTX *")
        # Create a temporary ctx that copies self.ctx because SHA512_t_Final
        # will zeroize the context passed in.
        lib.memcpy(shc, self.ctx, ffi.sizeof("SHA2_CTX"))
        lib.SHA2Final(digest, shc)

        return b"".join(six.int2byte(i) for i in digest)

    def hexdigest(self):
        """Return hexadecimal digest of the strings passed to the update()
        method so far."""

        # import goes here to prevent circular import
        from pkg.misc import binary_to_hex
        return binary_to_hex(self.digest())

# Vim hints
# vim:ts=4:sw=4:et:fdm=marker
