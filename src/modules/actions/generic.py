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
# Copyright (c) 2007, 2016, Oracle and/or its affiliates. All rights reserved.
#

"""module describing a generic packaging object

This module contains the Action class, which represents a generic packaging
object."""

import errno
import os

try:
        # Some versions of python don't have these constants.
        os.SEEK_SET
except AttributeError:
        os.SEEK_SET, os.SEEK_CUR, os.SEEK_END = range(3)
import six
import stat
import types
from io import BytesIO

import pkg.actions
import pkg.client.api_errors as apx
import pkg.digest as digest
import pkg.portable as portable
import pkg.variant as variant

from . import _common
from pkg.misc import EmptyDict, force_str

# Directories must precede all filesystem object actions; hardlinks must follow
# all filesystem object actions (except links).  Note that user and group
# actions precede file actions (so that the system permits chown'ing them to
# users and groups that may be delivered during the same operation); this
# implies that /etc/group and /etc/passwd file ownership needs to be part of
# initial contents of those files.
_orderdict = dict((k, i) for i, k in enumerate((
    "set",
    "depend",
    "group",
    "user",
    "dir",
    "file",
    "hardlink",
    "link",
    "driver",
    "unknown",
    "license",
    "legacy",
    "signature"
)))

# EmptyI for argument defaults; no import to avoid pkg.misc dependency.
EmptyI = tuple()

def quote_attr_value(s):
        """Returns a properly quoted version of the provided string suitable for
        use as an attribute value for actions in string form."""

        if " " in s or "'" in s or "\"" in s or s == "":
                if "\"" not in s:
                        return '"{0}"'.format(s)
                elif "'" not in s:
                        return "'{0}'".format(s)
                return '"{0}"'.format(s.replace("\"", "\\\""))
        return s

class NSG(type):
        """This metaclass automatically assigns a subclass of Action a
        namespace_group member if it hasn't already been specified.  This is a
        convenience for classes which are the sole members of their group and
        don't want to hardcode something arbitrary and unique."""

        __nsg = 0
        def __new__(mcs, name, bases, dict):
                nsg = None

                # We only look at subclasses of Action, and we ignore multiple
                # inheritance.
                if name != "Action" and issubclass(bases[0], Action):
                        # Iterate through the inheritance chain to see if any
                        # parent class has a namespace_group member, and grab
                        # its value.
                        for c in bases[0].__mro__:
                                if c == Action:
                                        break
                                nsg = getattr(c, "namespace_group", None)
                                if nsg is not None:
                                        break

                        # If the class didn't have a namespace_group member
                        # already, assign one.  If we found one in our traversal
                        # above, use that, otherwise make one up.
                        if "namespace_group" not in dict:
                                if not nsg:
                                        nsg = NSG.__nsg
                                        # Prepare for the next class.
                                        NSG.__nsg += 1
                                dict["namespace_group"] = nsg

                return type.__new__(mcs, name, bases, dict)

        @staticmethod
        def getstate(obj, je_state=None):
                """Returns the serialized state of this object in a format
                that that can be easily stored using JSON, pickle, etc."""
                return str(obj)

        @staticmethod
        def fromstate(state, jd_state=None):
                """Allocate a new object using previously serialized state
                obtained via getstate()."""
                return pkg.actions.fromstr(state)


# metaclass-assignment; pylint: disable=W1623
@six.add_metaclass(NSG)
class Action(object):
        """Class representing a generic packaging object.

        An Action is a very simple wrapper around two dictionaries: a named set
        of data streams and a set of attributes.  Data streams generally
        represent files on disk, and attributes represent metadata about those
        files.
        """

        __slots__ = ["attrs", "data"]

        # 'name' is the name of the action, as specified in a manifest.
        name = "generic"
        # 'key_attr' is the name of the attribute whose value must be unique in
        # the namespace of objects represented by a particular action.  For
        # instance, a file's key_attr would be its pathname.  Or a driver's
        # key_attr would be the driver name.  When 'key_attr' is None, it means
        # that all attributes of the action are distinguishing.
        key_attr = None
        # 'globally_identical' is True if all actions representing a single
        # object on a system must be identical.
        globally_identical = False
        # 'refcountable' is True if the action type can safely be delivered
        # multiple times.
        refcountable = False
        # 'namespace_group' is a string whose value is shared by actions which
        # share a common namespace.  As a convenience to the classes which are
        # the sole members of their group, this is set to a non-None value for
        # subclasses by the NSG metaclass.
        namespace_group = None
        # 'ordinality' is a numeric value that is used during action comparison
        # to determine action sorting.
        ordinality = _orderdict["unknown"]
        # 'unique_attrs' is a tuple listing the attributes which must be
        # identical in order for an action to be safely delivered multiple times
        # (for those that can be).
        unique_attrs = ()

        # The version of signature used.
        sig_version = 0
        # Most types of actions do not have a payload.
        has_payload = False

        # Python 3 will ignore the __metaclass__ field, but it's still useful
        # for class attribute access.
        __metaclass__ = NSG

        # __init__ is provided as a native function (see end of class
        # declaration).

        def set_data(self, data):
                """This function sets the data field of the action.

                The "data" parameter is the file to use to set the data field.
                It can be a string which is the path to the file, a function
                which provides the file when called, or a file handle to the
                file."""

                if data is None:
                        self.data = None
                        return

                if isinstance(data, six.string_types):
                        if not os.path.exists(data):
                                raise pkg.actions.ActionDataError(
                                    _("No such file: '{0}'.").format(data),
                                    path=data)
                        elif os.path.isdir(data):
                                raise pkg.actions.ActionDataError(
                                    _("'{0}' is not a file.").format(data),
                                    path=data)

                        def file_opener():
                                return open(data, "rb")
                        self.data = file_opener
                        if "pkg.size" not in self.attrs:
                                try:
                                        fs = os.stat(data)
                                        self.attrs["pkg.size"] = str(fs.st_size)
                                except EnvironmentError as e:
                                        raise \
                                            pkg.actions.ActionDataError(
                                            e, path=data)
                        return

                if hasattr(data, "__call__"):
                        # Data is not None, and is callable.
                        self.data = data
                        return

                if "pkg.size" in self.attrs:
                        self.data = lambda: data
                        return

                try:
                        sz = data.size
                except AttributeError:
                        try:
                                try:
                                        sz = os.fstat(data.fileno()).st_size
                                except (AttributeError, TypeError):
                                        try:
                                                try:
                                                        data.seek(0,
                                                            os.SEEK_END)
                                                        sz = data.tell()
                                                        data.seek(0)
                                                except (AttributeError,
                                                    TypeError):
                                                        d = data.read()
                                                        sz = len(d)
                                                        data = BytesIO(d)
                                        except (AttributeError, TypeError):
                                                # Raw data was provided; fake a
                                                # file object.
                                                sz = len(data)
                                                data = BytesIO(data)
                        except EnvironmentError as e:
                                raise pkg.actions.ActionDataError(e)

                self.attrs["pkg.size"] = str(sz)
                self.data = lambda: data

        def __str__(self):
                """Serialize the action into manifest form.

                The form is the name, followed by the SHA1 hash, if it exists,
                (this use of a positional SHA1 hash is deprecated, with
                pkg.*hash.* attributes being preferred over positional hashes)
                followed by attributes in the form 'key=value'.  All fields are
                space-separated; fields with spaces in the values are quoted.

                Note that an object with a datastream may have been created in
                such a way that the hash field is not populated, or not
                populated with real data.  The action classes do not guarantee
                that at the time that __str__() is called, the hash is properly
                computed.  This may need to be done externally.
                """

                sattrs = list(self.attrs.keys())
                out = self.name
                try:
                        h = self.hash
                        if h:
                                if "=" not in h and " " not in h and \
                                    '"' not in h:
                                        out += " " + h
                                else:
                                        sattrs.append("hash")
                except AttributeError:
                        # No hash to stash.
                        pass

                # Sort so that we get consistent action attribute ordering.
                # We pay a performance penalty to do so, but it seems worth it.
                sattrs.sort()

                for k in sattrs:
                        # Octal literal in Python 3 begins with "0o", such as
                        # "0o755", but we want to keep "0755" in the output.
                        if k == "mode" and isinstance(self.attrs[k], str) and \
                            self.attrs[k].startswith("0o"):
                                self.attrs[k] = "0" + self.attrs[k][2:]
                        try:
                               v = self.attrs[k]
                        except KeyError:
                                # If we can't find the attribute, it must be the
                                # hash. 'h' will only be in scope if the block
                                # at the start succeeded.
                                v = h

                        if type(v) is list or type(v) is set:
                                out += " " + " ".join([
                                    "=".join((k, quote_attr_value(lmt)))
                                    for lmt in v
                                ])
                        elif " " in v or "'" in v or "\"" in v or v == "":
                                if "\"" not in v:
                                        out += " " + k + "=\"" + v + "\""
                                elif "'" not in v:
                                        out += " " + k + "='" + v + "'"
                                else:
                                        out += " " + k + "=\"" + \
                                            v.replace("\"", "\\\"") + "\""
                        else:
                                out += " " + k + "=" + v

                return out

        def __repr__(self):
                return "<{0} object at {1:#x}: {2}>".format(self.__class__,
                    id(self), self)

        def sig_str(self, a, ver):
                """Create a stable string representation of an action that
                is deterministic in its creation.  If creating a string from an
                action is non-deterministic, then manifest signing cannot work.

                The parameter "a" is the signature action that's going to use
                the string produced.  It's needed for the signature string
                action, and is here to keep the method signature the same.
                """

                # Any changes to this function or any subclasses sig_str mean
                # Action.sig_version must be incremented.

                if ver != Action.sig_version:
                        raise apx.UnsupportedSignatureVersion(ver, sig=self)

                out = self.name
                if hasattr(self, "hash") and self.hash is not None:
                        out += " " + self.hash

                def q(s):
                        if " " in s or "'" in s or "\"" in s or s == "":
                                if "\"" not in s:
                                        return '"{0}"'.format(s)
                                elif "'" not in s:
                                        return "'{0}'".format(s)
                                else:
                                        return '"{0}"'.format(
                                            s.replace("\"", "\\\""))
                        else:
                                return s

                # Sort so that we get consistent action attribute ordering.
                # We pay a performance penalty to do so, but it seems worth it.
                for k in sorted(self.attrs.keys()):
                        v = self.attrs[k]
                        # Octal literal in Python 3 begins with "0o", such as
                        # "0o755", but we want to keep "0755" in the output.
                        if k == "mode" and v.startswith("0o"):
                                self.attrs[k] = "0" + v[2:]
                        if type(v) is list:
                                out += " " + " ".join([
                                    "{0}={1}".format(k, q(lmt)) for lmt in sorted(v)
                                ])
                        elif " " in v or "'" in v or "\"" in v or v == "":
                                if "\"" not in v:
                                        out += " " + k + "=\"" + v + "\""
                                elif "'" not in v:
                                        out += " " + k + "='" + v + "'"
                                else:
                                        out += " " + k + "=\"" + \
                                            v.replace("\"", "\\\"") + "\""
                        else:
                                out += " " + k + "=" + v

                return out

        def __eq__(self, other):
                if self.name == other.name and \
                    getattr(self, "hash", None) == \
                        getattr(other, "hash", None) and \
                    self.attrs == other.attrs:
                        return True
                return False

        def __ne__(self, other):
                if self.name == other.name and \
                    getattr(self, "hash", None) == \
                        getattr(other, "hash", None) and \
                    self.attrs == other.attrs:
                        return False
                return True

        def __hash__(self):
                return hash(id(self))

        def compare(self, other):
                return (id(self) > id(other)) - (id(self) < id(other))

        def __lt__(self, other):
                if self.ordinality == other.ordinality:
                        if self.compare(other) < 0: # often subclassed
                                return True
                        else:
                                return False
                return self.ordinality < other.ordinality

        def __gt__(self, other):
                if self.ordinality == other.ordinality:
                        if self.compare(other) > 0: # often subclassed
                                return True
                        else:
                                return False
                return self.ordinality > other.ordinality

        def __le__(self, other):
                return self == other or self < other

        def __ge__(self, other):
                return self == other or self > other

        def different(self, other, cmp_hash=False, pkgplan=None,
            cmp_unsigned=False,):
                """Returns True if other represents a non-ignorable
                change from self.

                By default, this means two actions are different if
                any of their attributes are different.  Subclasses
                should override this behavior when appropriate.

                For subclasses that support content hashes, cmp_hash
                may be set to True. This prevents comparing all hash
                attributes as simple value comparisons, and instead
                compares only non-hash attributes, then tests the
                most preferred hash for equivalence.

                When cmp_unsigned=True, we'll check the unsigned versions of
                hash instead of signed versions of hash on both actions.
                """

                # We could ignore key_attr, or possibly assert that it's the
                # same.
                sattrs = self.attrs
                oattrs = other.attrs
                sset = set(six.iterkeys(sattrs))
                oset = set(six.iterkeys(oattrs))

                # Remove all hash attributes from literal comparison
                # sets if we want to compare most preferred hash.
                if cmp_hash:
                        hset = set([a for a in (sset | oset)
                            if digest.is_hash_attr(a)])
                        sset -= hset
                        oset -= hset

                if sset.symmetric_difference(oset):
                        return True

                # Do simple value or sorted list comparisons on common
                # attributes. This set doesn't include hash attributes if
                # cmp_hash is True.
                for a in sset:
                        x = sattrs[a]
                        y = oattrs[a]
                        if x != y:
                                if len(x) == len(y) and \
                                    type(x) is list and type(y) is list:
                                        if sorted(x) != sorted(y):
                                                return True
                                else:
                                        return True

                if not cmp_hash:
                        return False

                hash_type = digest.CONTENT_HASH
                if pkgplan:
                        # import goes here to prevent circular import
                        from pkg.client.imageconfig import CONTENT_UPDATE_POLICY
                        if pkgplan.image.cfg.get_policy_str(
                            CONTENT_UPDATE_POLICY) != "when-required":
                                # check file hash if content policy requires
                                hash_type = digest.HASH

                # if hash_type is digest.CONTENT_HASH,
                # digest.get_common_preferred_hash() tries to return the most
                # preferred content-hash attribute and falls back to returning
                # the action.hash values if there are no other common hash
                # attributes, and will throw an AttributeError if one or the
                # other actions don't have an action.hash attribute.
                shash = ohash = None
                try:
                        hash_attr, shash, ohash, hash_func = \
                            digest.get_common_preferred_hash(
                                self, other, hash_type=hash_type,
                                cmp_unsigned=cmp_unsigned)
                except AttributeError:
                        # If action.hash is set on exactly one of self
                        # and other, then we're trying to compare
                        # actions of disparate subclasses.
                        if hasattr(self, "hash") ^ hasattr(other, "hash"):
                                raise AssertionError("attempt to compare a "
                                    "{0} action to a {1} action".format(
                                    self.name, other.name))

                if shash != ohash:
                        return True

                # If there's no common preferred hash, we have to
                # treat these actions as different
                return shash is None and ohash is None

        def differences(self, other):
                """Returns the attributes that have different values between
                other and self."""
                sset = set(self.attrs.keys())
                oset = set(other.attrs.keys())
                l = sset.symmetric_difference(oset)
                for k in sset & oset: # over attrs in both dicts
                        if type(self.attrs[k]) == list and \
                            type(other.attrs[k]) == list:
                                if sorted(self.attrs[k]) != sorted(other.attrs[k]):
                                        l.add(k)
                        elif self.attrs[k] != other.attrs[k]:
                                l.add(k)
                return (l)

        def consolidate_attrs(self):
                """Removes duplicate values from values which are lists."""
                for k in self.attrs:
                        if isinstance(self.attrs[k], list):
                                self.attrs[k] = list(set(self.attrs[k]))

        def generate_indices(self):
                """Generate the information needed to index this action.

                This method, and the overriding methods in subclasses, produce
                a list of four-tuples.  The tuples are of the form
                (action_name, key, token, full value).  action_name is the
                string representation of the kind of action generating the
                tuple.  'file' and 'depend' are two examples.  It is required to
                not be None.  Key is the string representation of the name of
                the attribute being indexed.  Examples include 'basename' and
                'path'.  Token is the token to be searched against.  Full value
                is the value to display to the user in the event this token
                matches their query.  This is useful for things like categories
                where what matched the query may be a substring of what the
                desired user output is.
                """

                # Indexing based on the SHA-1 hash is enough for the generic
                # case.
                if hasattr(self, "hash"):
                        return [
                            (self.name, "content", self.hash, self.hash),
                        ]
                return []

        def get_installed_path(self, img_root):
                """Given an image root, return the installed path of the action
                if it has a installable payload (i.e. 'path' attribute)."""
                try:
                        return os.path.normpath(os.path.join(img_root,
                            self.attrs["path"]))
                except KeyError:
                        return

        def distinguished_name(self):
                """ Return the distinguishing name for this action,
                    preceded by the type of the distinguishing name.  For
                    example, for a file action, 'path' might be the
                    key_attr.  So, the distinguished name might be
                    "path: usr/lib/libc.so.1".
                """

                if self.key_attr is None:
                        return str(self)
                return "{0}: {1}".format(
                    self.name, self.attrs.get(self.key_attr, "???"))

        def makedirs(self, path, **kw):
                """Make directory specified by 'path' with given permissions, as
                well as all missing parent directories.  Permissions are
                specified by the keyword arguments 'mode', 'uid', and 'gid'.

                The difference between this and os.makedirs() is that the
                permissions specify only those of the leaf directory.  Missing
                parent directories inherit the permissions of the deepest
                existing directory.  The leaf directory will also inherit any
                permissions not explicitly set."""

                # generate the components of the path.  The first
                # element will be empty since all absolute paths
                # always start with a root specifier.
                pathlist = portable.split_path(path)

                # Fill in the first path with the root of the filesystem
                # (this ends up being something like C:\ on windows systems,
                # and "/" on unix.
                pathlist[0] = portable.get_root(path)

                g = enumerate(pathlist)
                for i, e in g:
                        # os.path.isdir() follows links, which isn't
                        # desirable here.
                        p = os.path.join(*pathlist[:i + 1])
                        try:
                                fs = os.lstat(p)
                        except OSError as e:
                                if e.errno == errno.ENOENT:
                                        break
                                raise

                        if not stat.S_ISDIR(fs.st_mode):
                                if p == path:
                                        # Allow caller to handle target by
                                        # letting the operation continue,
                                        # and whatever error is encountered
                                        # being raised to the caller.
                                        break

                                err_txt = _("Unable to create {path}; a "
                                    "parent directory {p} has been replaced "
                                    "with a file or link.  Please restore the "
                                    "parent directory and try again.").format(
                                    **locals())
                                raise apx.ActionExecutionError(self,
                                    details=err_txt, error=e,
                                    fmri=kw.get("fmri"))
                else:
                        # XXX Because the filelist codepath may create
                        # directories with incorrect permissions (see
                        # pkgtarfile.py), we need to correct those permissions
                        # here.  Note that this solution relies on all
                        # intermediate directories being explicitly created by
                        # the packaging system; otherwise intermediate
                        # directories will not get their permissions corrected.
                        fs = os.lstat(path)
                        mode = kw.get("mode", fs.st_mode)
                        uid = kw.get("uid", fs.st_uid)
                        gid = kw.get("gid", fs.st_gid)
                        try:
                                if mode != fs.st_mode:
                                        os.chmod(path, mode)
                                if uid != fs.st_uid or gid != fs.st_gid:
                                        portable.chown(path, uid, gid)
                        except  OSError as e:
                                if e.errno != errno.EPERM and \
                                    e.errno != errno.ENOSYS:
                                        raise
                        return

                fs = os.stat(os.path.join(*pathlist[:i]))
                for i, e in g:
                        p = os.path.join(*pathlist[:i])
                        try:
                                os.mkdir(p, fs.st_mode)
                        except OSError as e:
                                if e.errno != errno.ENOTDIR:
                                        raise
                                err_txt = _("Unable to create {path}; a "
                                    "parent directory {p} has been replaced "
                                    "with a file or link.  Please restore the "
                                    "parent directory and try again.").format(
                                    **locals())
                                raise apx.ActionExecutionError(self,
                                    details=err_txt, error=e,
                                    fmri=kw.get("fmri"))

                        os.chmod(p, fs.st_mode)
                        try:
                                portable.chown(p, fs.st_uid, fs.st_gid)
                        except OSError as e:
                                if e.errno != errno.EPERM:
                                        raise

                # Create the leaf with any requested permissions, substituting
                # missing perms with the parent's perms.
                mode = kw.get("mode", fs.st_mode)
                uid = kw.get("uid", fs.st_uid)
                gid = kw.get("gid", fs.st_gid)
                os.mkdir(path, mode)
                os.chmod(path, mode)
                try:
                        portable.chown(path, uid, gid)
                except OSError as e:
                        if e.errno != errno.EPERM:
                                raise

        def get_varcet_keys(self):
                """Return the names of any facet or variant tags in this
                action."""

                # Hot path; grab reference to attrs and use list comprehensions
                # to construct the results.  This is faster than iterating over
                # attrs once and appending to two lists separately.
                attrs = self.attrs
                return [k for k in attrs if k[:8] == "variant."], \
                    [k for k in attrs if k[:6] == "facet."]

        def get_variant_template(self):
                """Return the VariantCombinationTemplate that the variant tags
                of this action define."""

                return variant.VariantCombinationTemplate(dict((
                    (v, self.attrs[v]) for v in self.get_varcet_keys()[0]
                )))

        def strip(self, preserve=EmptyDict):
                """Strip actions of attributes which are unnecessary once
                those actions have been installed in an image.  Stripped
                actions are saved in an images stripped action cache and used
                for conflicting actions checks during image planning
                operations."""

                for key in list(self.attrs.keys()):
                        # strip out variant and facet information
                        if key[:8] == "variant." or key[:6] == "facet.":
                                del self.attrs[key]
                                continue
                        # keep unique attributes
                        if not self.unique_attrs or key in self.unique_attrs:
                                continue
                        # keep file action overlay attributes
                        if self.name == "file" and key == "overlay":
                                continue
                        # keep specified keys
                        if key in preserve.get(self.name, []):
                                continue
                        # keep link/hardlink action mediator attributes
                        if (self.name == "link" or self.name == "hardlink") \
                            and key[:8] == "mediator":
                                continue
                        del self.attrs[key]

        def strip_variants(self):
                """Remove all variant tags from the attrs dictionary."""

                for k in list(self.attrs.keys()):
                        if k.startswith("variant."):
                                del self.attrs[k]

        def verify(self, img, **args):
                """Returns a tuple of lists of the form (errors, warnings,
                info).  The error list will be empty if the action has been
                correctly installed in the given image."""
                return [], [], []

        def _validate_fsobj_common(self):
                """Private, common validation logic for filesystem objects that
                returns a list of tuples of the form (attr_name, error_message).
                """

                errors = []

                bad_mode = False
                raw_mode = self.attrs.get("mode")
                if not raw_mode or isinstance(raw_mode, list):
                        bad_mode = True
                else:
                        mlen = len(raw_mode)
                        # Common case for our packages is 4 so place that first.
                        if not (mlen == 4 or mlen == 3 or mlen == 5):
                                bad_mode = True
                        elif mlen == 5 and raw_mode[0] != "0":
                                bad_mode = True

                # The group, mode, and owner attributes are intentionally only
                # required during publication as it is anticipated that the
                # there will eventually be defaults for these (possibly parent
                # directory, etc.).  By only requiring these attributes here,
                # it prevents publication of packages for which no default
                # currently exists, while permitting future changes to remove
                # that limitaiton and use sane defaults.
                if not bad_mode:
                        try:
                                mode = str(int(raw_mode, 8))
                        except (TypeError, ValueError):
                                bad_mode = True
                        else:
                                bad_mode = mode == ""

                if bad_mode:
                        if not raw_mode:
                                errors.append(("mode", _("mode is required; "
                                    "value must be of the form '644', "
                                    "'0644', or '04755'.")))
                        elif isinstance(raw_mode, list):
                                errors.append(("mode", _("mode may only be "
                                    "specified once")))
                        else:
                                errors.append(("mode", _("'{0}' is not a valid "
                                    "mode; value must be of the form '644', "
                                    "'0644', or '04755'.").format(raw_mode)))

                try:
                        owner = self.attrs.get("owner", "").rstrip()
                except AttributeError:
                        errors.append(("owner", _("owner may only be specified "
                            "once")))

                try:
                        group = self.attrs.get("group", "").rstrip()
                except AttributeError:
                        errors.append(("group", _("group may only be specified "
                            "once")))

                return errors

        def get_fsobj_uid_gid(self, pkgplan, fmri):
                """Returns a tuple of the form (owner, group) containing the uid
                and gid of the filesystem object.  If the attributes are missing
                or invalid, an InvalidActionAttributesError exception will be
                raised."""

                path = self.get_installed_path(pkgplan.image.get_root())

                # The attribute may be missing.
                owner = self.attrs.get("owner", "").rstrip()

                # Now attempt to determine the uid and raise an appropriate
                # exception if it can't be.
                try:
                        owner = pkgplan.image.get_user_by_name(owner)
                except KeyError:
                        if not owner:
                                # Owner was missing; let validate raise a more
                                # informative error.
                                self.validate(fmri=fmri)

                        # Otherwise, the user is unknown; attempt to report why.
                        pd = pkgplan.image.imageplan.pd
                        if owner in pd.removed_users:
                                # What package owned the user that was removed?
                                src_fmri = pd.removed_users[owner]

                                raise pkg.actions.InvalidActionAttributesError(
                                    self, [("owner", _("'{path}' cannot be "
                                    "installed; the owner '{owner}' was "
                                    "removed by '{src_fmri}'.").format(
                                    path=path, owner=owner,
                                    src_fmri=src_fmri))],
                                    fmri=fmri)
                        elif owner in pd.added_users:
                                # This indicates an error on the part of the
                                # caller; the user should have been added
                                # before attempting to install the file.
                                raise

                        # If this spot was reached, the user wasn't part of
                        # the operation plan and is completely unknown or
                        # invalid.
                        raise pkg.actions.InvalidActionAttributesError(
                            self, [("owner", _("'{path}' cannot be "
                                    "installed; '{owner}' is an unknown "
                                    "or invalid user.").format(path=path,
                                    owner=owner))],
                                    fmri=fmri)

                # The attribute may be missing.
                group = self.attrs.get("group", "").rstrip()

                # Now attempt to determine the gid and raise an appropriate
                # exception if it can't be.
                try:
                        group = pkgplan.image.get_group_by_name(group)
                except KeyError:
                        if not group:
                                # Group was missing; let validate raise a more
                                # informative error.
                                self.validate(fmri=pkgplan.destination_fmri)

                        # Otherwise, the group is unknown; attempt to report
                        # why.
                        pd = pkgplan.image.imageplan.pd
                        if group in pd.removed_groups:
                                # What package owned the group that was removed?
                                src_fmri = pd.removed_groups[group]

                                raise pkg.actions.InvalidActionAttributesError(
                                    self, [("group", _("'{path}' cannot be "
                                    "installed; the group '{group}' was "
                                    "removed by '{src_fmri}'.").format(
                                    path=path, group=group,
                                    src_fmri=src_fmri))],
                                    fmri=pkgplan.destination_fmri)
                        elif group in pd.added_groups:
                                # This indicates an error on the part of the
                                # caller; the group should have been added
                                # before attempting to install the file.
                                raise

                        # If this spot was reached, the group wasn't part of
                        # the operation plan and is completely unknown or
                        # invalid.
                        raise pkg.actions.InvalidActionAttributesError(
                            self, [("group", _("'{path}' cannot be "
                                    "installed; '{group}' is an unknown "
                                    "or invalid group.").format(path=path,
                                    group=group))],
                                    fmri=pkgplan.destination_fmri)

                return owner, group

        def verify_fsobj_common(self, img, ftype):
                """Common verify logic for filesystem objects."""

                errors = []
                warnings = []
                info = []

                abort = False
                def ftype_to_name(ftype):
                        assert ftype is not None
                        tmap = {
                                stat.S_IFIFO: "fifo",
                                stat.S_IFCHR: "character device",
                                stat.S_IFDIR: "directory",
                                stat.S_IFBLK: "block device",
                                stat.S_IFREG: "regular file",
                                stat.S_IFLNK: "symbolic link",
                                stat.S_IFSOCK: "socket",
                        }
                        if ftype in tmap:
                                return tmap[ftype]
                        else:
                                return "Unknown (0x{0:x})".format(ftype)

                mode = owner = group = None
                if "mode" in self.attrs:
                        mode = int(self.attrs["mode"], 8)
                if "owner" in self.attrs:
                        owner = self.attrs["owner"]
                        try:
                                owner = img.get_user_by_name(owner)
                        except KeyError:
                                errors.append(_("Owner: {0} is unknown").format(
                                    owner))
                                owner = None
                if "group" in self.attrs:
                        group = self.attrs["group"]
                        try:
                                group = img.get_group_by_name(group)
                        except KeyError:
                                errors.append(_("Group: {0} is unknown ").format(
                                    group))
                                group = None

                path = self.get_installed_path(img.get_root())

                lstat = None
                try:
                        lstat = os.lstat(path)
                except OSError as e:
                        if e.errno == errno.ENOENT:
                                if self.attrs.get("preserve", "") == "legacy":
                                        # It's acceptable for files with
                                        # preserve=legacy to be missing;
                                        # nothing more to validate.
                                        return (lstat, errors, warnings, info,
                                            abort)
                                errors.append(
                                    _("Missing: {0} does not exist").format(
                                    ftype_to_name(ftype)))
                        elif e.errno == errno.EACCES:
                                errors.append(_("Skipping: Permission denied"))
                        else:
                                errors.append(
                                    _("Unexpected Error: {0}").format(e))
                        abort = True

                if abort:
                        return lstat, errors, warnings, info, abort

                if ftype is not None and ftype != stat.S_IFMT(lstat.st_mode):
                        errors.append(_("File Type: '{found}' should be "
                            "'{expected}'").format(
                            found=ftype_to_name(stat.S_IFMT(lstat.st_mode)),
                            expected=ftype_to_name(ftype)))
                        abort = True

                if owner is not None and lstat.st_uid != owner:
                        errors.append(_("Owner: '{found_name} "
                            "({found_id:d})' should be '{expected_name} "
                            "({expected_id:d})'").format(
                            found_name=img.get_name_by_uid(lstat.st_uid,
                            True), found_id=lstat.st_uid,
                            expected_name=self.attrs["owner"],
                            expected_id=owner))

                if group is not None and lstat.st_gid != group:
                        errors.append(_("Group: '{found_name} "
                            "({found_id})' should be '{expected_name} "
                            "({expected_id})'").format(
                            found_name=img.get_name_by_gid(lstat.st_gid,
                            True), found_id=lstat.st_gid,
                            expected_name=self.attrs["group"],
                            expected_id=group))

                if mode is not None and stat.S_IMODE(lstat.st_mode) != mode:
                        errors.append(_("Mode: {found} should be "
                            "{expected}").format(
                            found=oct(stat.S_IMODE(lstat.st_mode)),
                            expected=oct(mode)))
                return lstat, errors, warnings, info, abort

        def needsdata(self, orig, pkgplan):
                """Returns True if the action transition requires a
                datastream."""
                return False

        def get_size(self):
                return int(self.attrs.get("pkg.size", "0"))

        def attrlist(self, name):
                """return list containing value of named attribute."""
                try:
                        value = self.attrs[name]
                except KeyError:
                        return []
                if type(value) is not list:
                        return [value]
                return value

        def directory_references(self):
                """Returns references to paths in action."""
                if "path" in self.attrs:
                        return [os.path.dirname(os.path.normpath(
                            self.attrs["path"]))]
                return []

        def preinstall(self, pkgplan, orig):
                """Client-side method that performs pre-install actions."""
                pass

        def install(self, pkgplan, orig):
                """Client-side method that installs the object."""
                pass

        def postinstall(self, pkgplan, orig):
                """Client-side method that performs post-install actions."""
                pass

        def preremove(self, pkgplan):
                """Client-side method that performs pre-remove actions."""
                pass

        def remove(self, pkgplan):
                """Client-side method that removes the object."""
                pass

        def remove_fsobj(self, pkgplan, path):
                """Shared logic for removing file and link objects."""

                # Necessary since removal logic is reused by install.
                fmri = pkgplan.destination_fmri
                if not fmri:
                        fmri = pkgplan.origin_fmri

                try:
                        portable.remove(path)
                except EnvironmentError as e:
                        if e.errno == errno.ENOENT:
                                # Already gone; don't care.
                                return
                        elif e.errno == errno.EBUSY and os.path.ismount(path):
                                # User has replaced item with mountpoint, or a
                                # package has been poorly implemented.
                                err_txt = _("Unable to remove {0}; it is in use "
                                    "as a mountpoint.  To continue, please "
                                    "unmount the filesystem at the target "
                                    "location and try again.").format(path)
                                raise apx.ActionExecutionError(self,
                                    details=err_txt, error=e, fmri=fmri)
                        elif e.errno == errno.EBUSY:
                                # os.path.ismount() is broken for lofs
                                # filesystems, so give a more generic
                                # error.
                                err_txt = _("Unable to remove {0}; it is in "
                                    "use by the system, another process, or "
                                    "as a mountpoint.").format(path)
                                raise apx.ActionExecutionError(self,
                                    details=err_txt, error=e, fmri=fmri)
                        elif e.errno == errno.EPERM and \
                            not stat.S_ISDIR(os.lstat(path).st_mode):
                                # Was expecting a directory in this failure
                                # case, it is not, so raise the error.
                                raise
                        elif e.errno in (errno.EACCES, errno.EROFS):
                                # Raise these permissions exceptions as-is.
                                raise
                        elif e.errno != errno.EPERM:
                                # An unexpected error.
                                raise apx.ActionExecutionError(self, error=e,
                                    fmri=fmri)

                        # Attempting to remove a directory as performed above
                        # gives EPERM.  First, try to remove the directory,
                        # if it isn't empty, salvage it.
                        try:
                                os.rmdir(path)
                        except OSError as e:
                                if e.errno in (errno.EPERM, errno.EACCES):
                                        # Raise permissions exceptions as-is.
                                        raise
                                elif e.errno not in (errno.EEXIST,
                                    errno.ENOTEMPTY):
                                        # An unexpected error.
                                        raise apx.ActionExecutionError(self,
                                            error=e, fmri=fmri)

                                pkgplan.salvage(path)

        def postremove(self, pkgplan):
                """Client-side method that performs post-remove actions."""
                pass

        def include_this(self, excludes, publisher=None):
                """Callables in excludes list returns True
                if action is to be included, False if
                not"""
                for c in excludes:
                        if not c(self, publisher=publisher):
                                return False
                return True

        def validate(self, fmri=None):
                """Performs additional validation of action attributes that
                for performance or other reasons cannot or should not be done
                during Action object creation.  An ActionError exception (or
                subclass of) will be raised if any attributes are not valid.
                This is primarily intended for use during publication or during
                error handling to provide additional diagonostics.

                'fmri' is an optional package FMRI (object or string) indicating
                what package contained this action.
                """

                self._validate(fmri=fmri)

        def _validate(self, fmri=None, numeric_attrs=EmptyI,
             raise_errors=True, required_attrs=EmptyI, single_attrs=EmptyI):
                """Common validation logic for all action types.

                'fmri' is an optional package FMRI (object or string) indicating
                what package contained this action.

                'numeric_attrs' is a list of attributes that must have an
                integer value.

                'raise_errors' is a boolean indicating whether errors should be
                raised as an exception or returned as a list of tuples of the
                form (attr_name, error_message).

                'single_attrs' is a list of attributes that should only be
                specified once.
                """

                errors = []
                for attr in self.attrs:
                        if ((attr.startswith("facet.") or
                            attr == "reboot-needed" or attr in single_attrs) and
                            type(self.attrs[attr]) is list):
                                errors.append((attr, _("{0} may only be "
                                    "specified once").format(attr)))
                        elif attr in numeric_attrs:
                                try:
                                        int(self.attrs[attr])
                                except (TypeError, ValueError):
                                        errors.append((attr, _("{0} must be an "
                                            "integer").format(attr)))

                for attr in required_attrs:
                        val = self.attrs.get(attr)
                        if not val or \
                            (isinstance(val, six.string_types) and not val.strip()):
                                errors.append((attr,
                                    _("{0} is required").format(attr)))

                if raise_errors and errors:
                        raise pkg.actions.InvalidActionAttributesError(self,
                            errors, fmri=fmri)
                return errors

        def fsobj_checkpath(self, pkgplan, final_path):
                """Verifies that the specified path doesn't contain one or more
                symlinks relative to the image root.  Raises an
                ActionExecutionError exception if path check fails."""

                valid_dirs = pkgplan.image.imageplan.valid_directories
                parent_path = os.path.dirname(final_path)
                if parent_path in valid_dirs:
                        return

                real_parent_path = os.path.realpath(parent_path)
                if parent_path == real_parent_path:
                        valid_dirs.add(parent_path)
                        return

                fmri = pkgplan.destination_fmri

                # Now test each component of the parent path until one is found
                # to be a link.  When found, that's the parent that has been
                # redirected to some other location.
                tmp = parent_path
                img_root = pkgplan.image.root.rstrip(os.path.sep)
                while 1:
                        if tmp == img_root:
                                # No parent directories up to the root were
                                # found to be links, so assume this is ok.
                                valid_dirs.add(parent_path)
                                return

                        if os.path.islink(tmp):
                                # We've found the parent that changed locations.
                                break
                        # Drop the final component.
                        tmp = os.path.split(tmp)[0]

                parent_dir = tmp
                parent_target = os.path.realpath(parent_dir)
                err_txt = _("Cannot install '{final_path}'; parent directory "
                    "{parent_dir} is a link to {parent_target}.  To "
                    "continue, move the directory to its original location and "
                    "try again.").format(**locals())
                raise apx.ActionExecutionError(self, details=err_txt,
                    fmri=fmri)

        if six.PY3:
                def __init__(self, data=None, **attrs):
                        # create a bound method (no unbound method in Python 3)
                        _common._generic_init(self, data, **attrs)

if six.PY2:
        # create an unbound method
        Action.__init__ = types.MethodType(_common._generic_init, None, Action)

# Vim hints
# vim:ts=8:sw=8:et:fdm=marker
