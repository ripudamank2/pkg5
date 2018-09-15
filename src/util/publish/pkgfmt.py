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
# Copyright (c) 2009, 2016, Oracle and/or its affiliates. All rights reserved.
#

from __future__ import print_function

# Prefixes should be ordered alphabetically with most specific first.
DRIVER_ALIAS_PREFIXES = (
    "firewire",
    "pccard",
    "pciexclass",
    "pciclass",
    "pciex",
    "pcie",
    "pci",
    "pnpPNP",
    "usbia",
    "usbif",
    "usbi",
    "usb",
)

# Format a manifest according to the following rules:
#
# 1) File leading comments are left alone
# 2) All other comments stay w/ the first non-comment line that follows
#    them
# 3) Actions appear grouped by type, ignoring macros
# 4) Actions are limited to 80 chars; continuation lines are accepted
#    and emitted
# 5) variant & facet tags appear at the end of actions
# 6) multi-valued tags appear at the end aside from the above
# 7) key attribute tags come first

try:
        import copy
        import errno
        import getopt
        import gettext
        import locale
        import operator
        import os
        import re
        import six
        import sys
        import tempfile
        import traceback
        import warnings
        from difflib import unified_diff
        from functools import cmp_to_key
        from six.moves import cStringIO

        import pkg
        import pkg.actions
        import pkg.misc as misc
        import pkg.portable
        from pkg.misc import emsg, PipeError
        from pkg.actions.generic import quote_attr_value
        from pkg.actions.depend import known_types as dep_types
except KeyboardInterrupt:
        import sys
        sys.exit(1)

FMT_V1 = "v1"
FMT_V2 = "v2"

opt_unwrap = False
opt_check = False
opt_diffs = False
opt_format = FMT_V2
orig_opt_format = None

def usage(errmsg="", exitcode=2):
        """Emit a usage message and optionally prefix it with a more specific
        error message.  Causes program to exit."""

        if errmsg:
                error(errmsg)

        # -f is intentionally undocumented.
        print(_("""\
Usage:
        pkgfmt [-cdu] [file1] ... """), file=sys.stderr)

        sys.exit(exitcode)

def error(text, exitcode=1):
        """Emit an error message prefixed by the command name """

        # If we get passed something like an Exception, we can convert
        # it down to a string.
        text = str(text)

        # If the message starts with whitespace, assume that it should come
        # *before* the command-name prefix.
        text_nows = text.lstrip()
        ws = text[:len(text) - len(text_nows)]

        # This has to be a constant value as we can't reliably get our actual
        # program name on all platforms.
        emsg(ws + "pkgfmt: error: " + text_nows)

        if exitcode != None:
                sys.exit(exitcode)

def read_line(f):
        """Generates the lines in the file as tuples containing
        (action, prepended macro, list of prepended comment lines);
        handles continuation lines, transforms, etc."""

        accumulate = ""
        wrap_accumulate = ""
        noncomment_line_seen = False
        comments = []

        for l in f:
                line = l.strip()
                wrap_line = l
                # Preserve line continuations for transforms for V2,
                # but force standard leading space formatting.
                if line.endswith("\\"):
                        accumulate += line[:-1]
                        wrap_accumulate += re.sub("^\s+", "    ",
                            wrap_line.rstrip(" \t"))
                        continue
                elif accumulate:
                        line = accumulate + line
                        wrap_line = wrap_accumulate + re.sub("^\s+", "    ",
                            wrap_line)
                        accumulate = ""
                        wrap_accumulate = ""

                if not line or line[0] == "#":
                        comments.append(line)
                        continue

                if not noncomment_line_seen:
                        noncomment_line_seen = True
                        yield None, "", comments
                        comments = []

                if line.startswith("$("):
                        cp = line.index(")")
                        macro = line[:cp + 1]
                        actstr = line[cp + 1:]
                else:
                        macro = ""
                        actstr = line

                if actstr[0] == "<" and actstr[-1] == ">":
                        if opt_format == FMT_V2:
                                yield None, wrap_line.rstrip(), comments
                        else:
                                yield None, macro + actstr, comments

                        comments = []
                        macro = ""
                        continue

                try:
                        act = pkg.actions.fromstr(actstr)

                        # For formatting purposes, treat dependency actions that
                        # do not yet have a valid type as invalid.
                        if (act.name == "depend" and
                            act.attrs.get("type") not in dep_types):
                                raise pkg.actions.InvalidActionError(act,
                                    _("Unknown type '{0}' in depend "
                                      "action").format(act.attrs.get("type")))
                except (pkg.actions.MalformedActionError,
                    pkg.actions.UnknownActionError,
                    pkg.actions.InvalidActionError):
                        # cannot convert; treat as special macro
                        yield None, macro + actstr, comments
                else:
                        yield act, macro, comments

                comments = []

        if comments:
                yield None, "", comments

def cmplines(a, b):
        """Compare two line tuples for sorting"""
        # we know that all lines that reach here have actions
        # make set actions first
        # depend actions last
        # rest in alpha order

        def typeord(a):
                if a.name == "set":
                        return 1
                if opt_format == FMT_V2:
                        if a.name in ("driver", "group", "user"):
                                return 3
                        if a.name in ("legacy", "license"):
                                return 4
                if a.name == "depend":
                        return 5
                return 2

        c = misc.cmp(typeord(a[0]), typeord(b[0]))
        if c:
                return c

        if opt_format != FMT_V2:
                c = misc.cmp(a[0].name, b[0].name)
                if c:
                        return c

        # Place set pkg.fmri actions first among set actions.
        if a[0].name == "set" and a[0].attrs["name"] == "pkg.fmri":
                return -1
        if b[0].name == "set" and b[0].attrs["name"] == "pkg.fmri":
                return 1

        # Place set actions with names that start with pkg. before any
        # remaining set actions.
        if a[0].name == "set" and a[0].attrs["name"].startswith("pkg.") and \
            not (b[0].name != "set" or b[0].attrs["name"].startswith("pkg.")):
                return -1
        if b[0].name == "set" and b[0].attrs["name"].startswith("pkg.") and \
            not (a[0].name != "set" or a[0].attrs["name"].startswith("pkg.")):
                return 1

        if opt_format == FMT_V2:
                # Place set pkg.summary actions second and pkg.description
                # options third.
                for attr in ("pkg.summary", "pkg.description"):
                        if (a[0].name == "set" and
                            a[0].attrs["name"] == attr and
                            not b[0].attrs["name"] == attr):
                                return -1
                        if (b[0].name == "set" and
                            b[0].attrs["name"] == attr and
                            not a[0].attrs["name"] == attr):
                                return 1

        # Sort actions based on key attribute (if applicable).
        key_attr = a[0].key_attr
        if key_attr and key_attr == b[0].key_attr:
                a_sk = b_sk = None
                if opt_format == FMT_V2:
                        if "path" in a[0].attrs and "path" in b[0].attrs:
                                # This ensures filesystem actions are sorted by
                                # path and link and hardlink actions are sorted
                                # by path and then target (when compared against
                                # each other).
                                if "target" in a[0].attrs and \
                                    "target" in b[0].attrs:
                                        a_sk = operator.itemgetter("path",
                                            "target")(a[0].attrs)
                                        b_sk = operator.itemgetter("path",
                                            "target")(b[0].attrs)
                                else:
                                        a_sk = a[0].attrs["path"]
                                        b_sk = b[0].attrs["path"]
                        elif a[0].name == "depend" and b[0].name == "depend":
                                a_sk = operator.itemgetter("type", "fmri")(
                                    a[0].attrs)
                                b_sk = operator.itemgetter("type", "fmri")(
                                    b[0].attrs)

                # If not using alternate format, or if no sort key has been
                # determined, fallback to sorting on key attribute.
                if not a_sk:
                        a_sk = a[0].attrs[key_attr]
                if not b_sk:
                        b_sk = b[0].attrs[key_attr]

                c = misc.cmp(a_sk, b_sk)
                # misc.cmp raises NotImplemented for uncomparable types in
                # Python 3. Sort them based on stringified key attribute.
                if c is NotImplemented:
                        c = misc.cmp(str(a_sk), str(b_sk))
                        if c:
                                return c
                elif c:
                        return c

        # No key attribute or key attribute sorting provides equal placement, so
        # sort based on stringified action.
        return misc.cmp(str(a[0]), str(b[0]))

def write_line(line, fileobj):
        """Write out a manifest line"""
        # write out any comments w/o changes
        global opt_unwrap

        comments = "\n".join(line[2])
        act = line[0]
        out = line[1] + act.name

        sattrs = act.attrs
        ahash = None
        try:
                ahash = act.hash
                if ahash and ahash != "NOHASH":
                        if "=" not in ahash and " " not in ahash and \
                            '"' not in ahash:
                                out += " " + ahash
                        else:
                                sattrs = copy.copy(act.attrs)
                                sattrs["hash"] = ahash
                                ahash = None
        except AttributeError:
                # No hash to stash.
                pass

        # high order bits in sorting
        def kvord(a):
                # Variants should always be last attribute.
                if a[0].startswith("variant."):
                        return 7
                # Facets should always be before variants.
                if a[0].startswith("facet."):
                        return 6
                # List attributes should be before facets and variants.
                if isinstance(a[1], list):
                        return 5

                # note closure hack...
                if opt_format == FMT_V2:
                        if act.name == "depend":
                                # For depend actions, type should always come
                                # first even though it's not the key attribute,
                                # and fmri should always come after type.
                                if a[0] == "fmri":
                                        return 1
                                elif a[0] == "type":
                                        return 0
                        elif act.name == "driver":
                                # For driver actions, attributes should be in
                                # this order: name, perms, clone_perms, privs,
                                # policy, devlink, alias.
                                if a[0] == "alias":
                                        return 6
                                elif a[0] == "devlink":
                                        return 5
                                elif a[0] == "policy":
                                        return 4
                                elif a[0] == "privs":
                                        return 3
                                elif a[0] == "clone_perms":
                                        return 2
                                elif a[0] == "perms":
                                        return 1
                        elif act.name != "user":
                                # Place target after path, owner before group,
                                # and all immediately after the action's key
                                # attribute.
                                if a[0] == "mode":
                                        return 3
                                elif a[0] == "group":
                                        return 2
                                elif a[0] == "owner" or a[0] == "target":
                                        return 1

                # Any other attributes should come just before list, facet,
                # and variant attributes.
                if a[0] != act.key_attr:
                        return 4

                # No special order for all other cases.
                return 0

        # actual key function
        def key_func(a):
                return (kvord(a), a[0])

        JOIN_TOK = " \\\n    "
        def grow(a, b, rem_values, force_nl=False):
                if opt_unwrap or not force_nl:
                        lastnl = a.rfind("\n")
                        if lastnl == -1:
                                lastnl = 0

                        if opt_format == FMT_V2 and rem_values == 1:
                                # If outputting the last attribute value, then
                                # use full line length.
                                max_len = 80
                        else:
                                # If V1 format, or there are more attributes to
                                # output, then account for line-continuation
                                # marker.
                                max_len = 78

                        # Note this length comparison doesn't include the space
                        # used to append the second part of the string.
                        if opt_unwrap or (len(a) - lastnl + len(b) < max_len):
                                return a + " " + b
                return a + JOIN_TOK + b

        def get_alias_key(v):
                """This function parses an alias attribute value into a list
                of numeric values (e.g. hex -> int) and strings that can be
                sensibly compared for sorting."""

                alias = None
                prefix = None
                for pfx in DRIVER_ALIAS_PREFIXES:
                        if v.startswith(pfx):
                                # Strip known prefixes before attempting
                                # to create list of sort values.
                                alias = v.replace(pfx, "")
                                prefix = pfx
                                break

                if alias is None:
                        # alias didn't start with known prefix; use
                        # raw value for sorting.
                        return [v]

                entry = [prefix]
                for part in alias.split(","):
                        for comp in part.split("."):
                                try:
                                        cval = int(comp, 16)
                                except ValueError:
                                        cval = comp
                                entry.append(cval)
                return entry

        def cmp_aliases(a, b):
                if opt_format == FMT_V1:
                        # Simple comparison for V1 format.
                        return misc.cmp(a, b)
                # For V2 format, order aliases by interpreted value.
                return misc.cmp(get_alias_key(a), get_alias_key(b))

        def astr(aout):
                # Number of attribute values for first line and remaining.
                first_line = True
                first_attr_count = 0
                rem_attr_count = 0

                # Total number of remaining attribute values to output.
                total_count = sum(len(act.attrlist(k)) for k in sattrs)
                rem_count = total_count

                # Now build the action output string an attribute at a time.
                for k, v in sorted(six.iteritems(sattrs), key=key_func):
                        # Newline breaks are only forced when there is more than
                        # one value for an attribute.
                        if not (isinstance(v, list) or isinstance(v, set)):
                                nv = [v]
                                use_force_nl = False
                        else:
                                nv = v
                                use_force_nl = True

                        cmp_attrs = None
                        if k == "alias":
                                cmp_attrs = cmp_to_key(cmp_aliases)
                        for lmt in sorted(nv, key=cmp_attrs):
                                force_nl = use_force_nl and \
                                    (k == "alias" or (opt_format == FMT_V2 and
                                    k.startswith("pkg.debug")))

                                aout = grow(aout, "=".join((k,
                                    quote_attr_value(lmt))), rem_count,
                                    force_nl=force_nl)

                                # Must be done for each value.
                                if first_line and JOIN_TOK in aout:
                                        first_line = False
                                        first_attr_count = \
                                            (total_count - rem_count)
                                        if ahash and ahash != "NOHASH":
                                                first_attr_count += 1
                                        rem_attr_count = rem_count

                                rem_count -= 1

                return first_attr_count, rem_attr_count, aout

        first_attr_count, rem_attr_count, output = astr(out)
        if opt_format == FMT_V2 and not opt_unwrap:
                outlines = output.split(JOIN_TOK)

                # If wrapping only resulted in two lines, and the second line
                # only has one attribute and the first line had zero attributes,
                # unwrap the action.
                if first_attr_count < 2 and rem_attr_count == 1 and \
                    len(outlines) == 2 and first_attr_count == 0:
                        opt_unwrap = True
                        output = astr(out)[-1]
                        opt_unwrap = False

        if comments:
                print(comments, file=fileobj)

        if opt_format == FMT_V2:
                # Force 'dir' actions to use four spaces at beginning of lines
                # so they line up with other filesystem actions such as file,
                # link, etc.
                output = re.sub("^dir ", "dir  ", output)
        print(output, file=fileobj)

def main_func():
        gettext.install("pkg", "/usr/share/locale",
            codeset=locale.getpreferredencoding())
        global opt_unwrap
        global opt_check
        global opt_diffs
        global opt_format
        global orig_opt_format

        # Purposefully undocumented; just like -f.
        env_format = os.environ.get("PKGFMT_OUTPUT")
        if env_format:
                opt_format = orig_opt_format = env_format

        ret = 0
        opt_set = set()

        try:
                opts, pargs = getopt.getopt(sys.argv[1:], "cdf:u?", ["help"])
                for opt, arg in opts:
                        opt_set.add(opt)
                        if opt == "-c":
                                opt_check = True
                        elif opt == "-d":
                                opt_diffs = True
                        elif opt == "-f":
                                opt_format = orig_opt_format = arg
                        elif opt == "-u":
                                opt_unwrap = True
                        elif opt in ("--help", "-?"):
                                usage(exitcode=0)
        except getopt.GetoptError as e:
                usage(_("illegal global option -- {0}").format(e.opt))
        if len(opt_set - set(["-f"])) > 1:
                usage(_("only one of [cdu] may be specified"))
        if opt_format not in (FMT_V1, FMT_V2):
                usage(_("unsupported format '{0}'").format(opt_format))


        def difference(in_file):
                whole_f1 = in_file.readlines()
                f2 = cStringIO()
                fmt_file(cStringIO("".join(whole_f1)), f2)
                f2.seek(0)
                whole_f2 = f2.readlines()

                if whole_f1 == whole_f2:
                        if opt_diffs:
                                return 0, ""
                        return 0, "".join(whole_f2)
                elif opt_diffs:
                        return 1, "".join(unified_diff(whole_f2,
                            whole_f1))
                return 1, "".join(whole_f2)

        flist = pargs
        if not flist:
                try:
                        in_file = cStringIO()
                        in_file.write(sys.stdin.read())
                        in_file.seek(0)

                        ret, formatted = difference(in_file)
                        if ret == 1 and opt_check:
                                # Manifest was different; if user didn't specify
                                # a format explicitly, try V1 format.
                                if not orig_opt_format:
                                        opt_format = FMT_V1
                                        in_file.seek(0)
                                        rcode, formatted = difference(in_file)
                                        opt_format = FMT_V2
                                        if rcode == 0:
                                                # Manifest is in V1 format.
                                                return 0

                                error(_("manifest is not in pkgfmt form"))
                        elif ret == 1 and not opt_diffs:
                                # Treat as successful exit if not checking
                                # formatting or displaying diffs.
                                ret = 0

                        # Display formatted version (explicit 'end' needed to
                        # prevent output of extra newline) even if manifest
                        # didn't need formatting for the stdin case.  (The
                        # assumption is that it might be used in a pipeline.)
                        if formatted:
                                print(formatted, end="")
                except EnvironmentError as e:
                        if e.errno == errno.EPIPE:
                                # User closed input or output (i.e. killed piped
                                # program before all input was read or output
                                # was written).
                                return 1
                return ret

        ret = 0
        tname = None
        for fname in flist:
                try:
                        # force path to be absolute; gives better diagnostics if
                        # something goes wrong.
                        path = os.path.abspath(fname)

                        with open(fname, "r") as f:
                                rcode, formatted = difference(f)
                        if rcode == 0:
                                continue

                        if opt_check:
                                # Manifest was different; if user didn't specify
                                # a format explicitly, try V1 format.
                                if not orig_opt_format:
                                        opt_format = FMT_V1
                                        with open(fname, "r") as f:
                                                rcode, formatted = difference(f)
                                        opt_format = FMT_V2
                                        if rcode == 0:
                                                # Manifest is in V1 format.
                                                continue

                                ret = 1
                                error(_("{0} is not in pkgfmt form; run pkgfmt "
                                    "on file without -c or -d to reformat "
                                    "manifest in place").format(fname), exitcode=None)
                                continue
                        elif opt_diffs:
                                # Display differences (explicit 'end' needed to
                                # prevent output of extra newline).
                                ret = 1
                                print(formatted, end=" ")
                                continue
                        elif ret != 1:
                                # Treat as successful exit if not checking
                                # formatting or displaying diffs.
                                ret = 0

                        # Replace manifest with formatted version.
                        pathdir = os.path.dirname(path)
                        tfd, tname = tempfile.mkstemp(dir=pathdir)
                        with os.fdopen(tfd, "w") as t:
                                t.write(formatted)

                        try:
                                # Ensure existing mode is preserved.
                                mode = os.stat(fname).st_mode
                                os.chmod(tname, mode)
                                os.rename(tname, fname)
                        except EnvironmentError as e:
                                error(str(e), exitcode=1)
                except (EnvironmentError, IOError) as e:
                        error(str(e), exitcode=1)
                finally:
                        if tname:
                                try:
                                        pkg.portable.remove(tname)
                                except EnvironmentError as e:
                                        if e.errno != errno.ENOENT:
                                                raise

        return ret

def fmt_file(in_file, out_file):
        lines = []
        saw_action = False
        trailing_comments = []

        for tp in read_line(in_file):
                if tp[0] is None:
                        if saw_action and not tp[1]:
                                # Comments without a macro or transform
                                # nearby will be placed at the end if
                                # found after actions.
                                trailing_comments.extend(tp[2])
                                continue

                        # Any other comments, transforms, or unparseables
                        # will simply be printed back out wherever they
                        # were found before or after actions.
                        for l in tp[2]:
                                print(l, file=out_file)
                        if tp[1]:
                                print(tp[1], file=out_file)
                else:
                        lines.append(tp)
                        saw_action = True

        lines.sort(key=cmp_to_key(cmplines))
        for l in lines:
                write_line(l, out_file)
        out_file.writelines("\n".join(trailing_comments))
        if trailing_comments:
                # Ensure file ends with newline.
                out_file.write("\n")


if __name__ == "__main__":
        if six.PY3:
                # disable ResourceWarning: unclosed file
                warnings.filterwarnings("ignore", category=ResourceWarning)
        try:
                __ret = main_func()
        except (PipeError, KeyboardInterrupt):
                # We don't want to display any messages here to prevent
                # possible further broken pipe (EPIPE) errors.
                __ret = 1
        except SystemExit as _e:
                raise _e
        except:
                traceback.print_exc()
                error(misc.get_traceback_message(), exitcode=None)
                __ret = 99

        sys.exit(__ret)

# Vim hints
# vim:ts=8:sw=8:et:fdm=marker
