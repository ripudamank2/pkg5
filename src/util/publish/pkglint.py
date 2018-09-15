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

#
# Copyright (c) 2010, 2016, Oracle and/or its affiliates. All rights reserved.
#

import codecs
import logging
import six
import sys
import gettext
import locale
import traceback
import warnings
from optparse import OptionParser

from pkg.client.api_errors import InvalidPackageErrors
from pkg import VERSION
from pkg.misc import PipeError
from pkg.client.pkgdefs import EXIT_OK, EXIT_OOPS, EXIT_BADOPT

import pkg.lint.engine as engine
import pkg.lint.log as log
import pkg.fmri as fmri
import pkg.manifest
import pkg.misc as misc
import pkg.client.api_errors as apx
import pkg.client.transport.exception as tx

logger = None

def error(message=""):
        """Emit an error message prefixed by the command name. """
        misc.emsg("pkglint: {0}".format(message))

        if logger is not None:
                logger.error(_("Error: {0}").format(message))

def msg(message):
        logger.info(message)

def debug(message):
        logger.debug(message)

def main_func():
        """Start pkglint."""

        global logger

        usage = \
            _("\n"
            "        %prog [-b build_no] [-c cache_dir] [-f file]\n"
            "            [-l uri ...] [-p regexp] [-r uri ...] [-v]\n"
            "            [manifest ...]\n"
            "        %prog -L")
        parser = OptionParser(usage=usage)

        parser.add_option("-b", dest="release", metavar="build_no",
            help=_("build to use from lint and reference repositories"))
        parser.add_option("-c", dest="cache", metavar="dir",
            help=_("directory to use as a repository cache"))
        parser.add_option("-f", dest="config", metavar="file",
            help=_("specify an alternative pkglintrc file"))
        parser.add_option("-l", dest="lint_uris", metavar="uri",
            action="append", help=_("lint repository URI"))
        parser.add_option("-L", dest="list_checks",
            action="store_true",
            help=_("list checks configured for this session and exit"))
        parser.add_option("-p", dest="pattern", metavar="regexp",
            help=_("pattern to match FMRIs in lint URI"))
        parser.add_option("-r", dest="ref_uris", metavar="uri",
            action="append", help=_("reference repository URI"))
        parser.add_option("-v", dest="verbose", action="store_true",
            help=_("produce verbose output, overriding settings in pkglintrc")
            )

        opts, args = parser.parse_args(sys.argv[1:])

        # without a cache option, we can't access repositories, so expect
        # local manifests.
        if not (opts.cache or opts.list_checks) and not args:
                parser.error(
                    _("Required -c option missing, no local manifests provided."
                    ))

        pattern = opts.pattern
        opts.ref_uris = _make_list(opts.ref_uris)
        opts.lint_uris = _make_list(opts.lint_uris)

        logger = logging.getLogger("pkglint")
        ch = logging.StreamHandler(sys.stdout)

        if opts.verbose:
                logger.setLevel(logging.DEBUG)
                ch.setLevel(logging.DEBUG)

        else:
                logger.setLevel(logging.INFO)
                ch.setLevel(logging.INFO)

        logger.addHandler(ch)

        lint_logger = log.PlainLogFormatter()
        try:
                if not opts.list_checks:
                        msg(_("Lint engine setup..."))
                lint_engine = engine.LintEngine(lint_logger,
                    config_file=opts.config, verbose=opts.verbose)

                if opts.list_checks:
                        list_checks(lint_engine.checkers,
                            lint_engine.excluded_checkers, opts.verbose)
                        return EXIT_OK

                if (opts.lint_uris or opts.ref_uris) and not opts.cache:
                        parser.error(
                            _("Required -c option missing when using "
                            "repositories."))

                manifests = []
                if len(args) >= 1:
                        manifests = read_manifests(args, lint_logger)
                        if None in manifests or \
                            lint_logger.produced_lint_msgs():
                                error(_("Fatal error in manifest - exiting."))
                                return EXIT_OOPS
                lint_engine.setup(ref_uris=opts.ref_uris,
                    lint_uris=opts.lint_uris,
                    lint_manifests=manifests,
                    cache=opts.cache,
                    pattern=pattern,
                    release=opts.release)

                msg(_("Starting lint run..."))

                lint_engine.execute()
                lint_engine.teardown()
                lint_logger.close()

        except engine.LintEngineSetupException as err:
                # errors during setup are likely to be caused by bad
                # input or configuration, not lint errors in manifests.
                error(err)
                return EXIT_BADOPT

        except engine.LintEngineException as err:
                error(err)
                return EXIT_OOPS

        if lint_logger.produced_lint_msgs():
                return EXIT_OOPS
        else:
                return EXIT_OK

def list_checks(checkers, exclude, verbose=False):
        """Prints a human-readable version of configured checks."""

        # used for justifying output
        width = 28

        def get_method_desc(method, verbose):
                if "pkglint_desc" in method.__dict__ and not verbose:
                        return method.pkglint_desc
                else:
                        return "{0}.{1}.{2}".format(method.__self__.__class__.__module__,
                            method.__self__.__class__.__name__,
                            method.__func__.__name__)

        def emit(name, value):
                msg("{0} {1}".format(name.ljust(width), value))

        def print_list(items):
                k = list(items.keys())
                k.sort()
                for lint_id in k:
                        emit(lint_id, items[lint_id])

        include_items = {}
        exclude_items = {}

        for checker in checkers:
                for m, lint_id in checker.included_checks:
                        include_items[lint_id] = get_method_desc(m, verbose)

        for checker in exclude:
                for m, lint_id in checker.excluded_checks:
                        exclude_items[lint_id] = get_method_desc(m, verbose)
                for m, lint_id in checker.included_checks:
                        exclude_items[lint_id] = get_method_desc(m, verbose)

        for checker in checkers:
                for m, lint_id in checker.excluded_checks:
                        exclude_items[lint_id] = get_method_desc(m, verbose)

        if include_items or exclude_items:
                if verbose:
                        emit(_("NAME"), _("METHOD"))
                else:
                        emit(_("NAME"), _("DESCRIPTION"))
                print_list(include_items)

                if exclude_items:
                        msg(_("\nExcluded checks:"))
                        print_list(exclude_items)

def read_manifests(names, lint_logger):
        """Read a list of filenames, return a list of Manifest objects."""

        manifests = []
        for filename in names:
                data = None
                # borrowed code from publish.py
                lines = []      # giant string of all input lines
                linecnts = []   # tuples of starting line no., ending line no
                linecounter = 0 # running total
                try:
                        f = codecs.open(filename, "rb", "utf-8")
                        data = f.read()
                except UnicodeDecodeError as e:
                        lint_logger.critical(_("Invalid file {file}: "
                            "manifest not encoded in UTF-8: {err}").format(
                            file=filename, err=e),
                            msgid="lint.manifest002")
                        continue
                except IOError as e:
                        lint_logger.critical(_("Unable to read manifest file "
                            "{file}: {err}").format(file=filename, err=e),
                            msgid="lint.manifest001")
                        continue
                lines.append(data)
                linecnt = len(data.splitlines())
                linecnts.append((linecounter, linecounter + linecnt))
                linecounter += linecnt

                manifest = pkg.manifest.Manifest()
                try:
                        manifest.set_content(content="\n".join(lines))
                except pkg.actions.ActionError as e:
                        lineno = e.lineno
                        for i, tup in enumerate(linecnts):
                                if lineno > tup[0] and lineno <= tup[1]:
                                        lineno -= tup[0]
                                        break
                        else:
                                lineno = "???"

                        lint_logger.critical(
                            _("Error in {file} line: {ln}: {err} ").format(
                            file=filename,
                            ln=lineno,
                            err=str(e)), "lint.manifest002")
                        manifest = None
                except InvalidPackageErrors as e:
                        lint_logger.critical(
                            _("Error in file {file}: {err}").format(
                            file=filename,
                            err=str(e)), "lint.manifest002")
                        manifest = None

                if manifest and "pkg.fmri" in manifest:
                        try:
                                manifest.fmri = \
                                    pkg.fmri.PkgFmri(manifest["pkg.fmri"])
                        except fmri.IllegalFmri as e:
                                lint_logger.critical(
                                    _("Error in file {file}: "
                                    "{err}").format(
                                    file=filename, err=e),
                                    "lint.manifest002")
                        if manifest.fmri:
                                if not manifest.fmri.version:
                                        lint_logger.critical(
                                            _("Error in file {0}: "
                                            "pkg.fmri does not include a "
                                            "version string").format(filename),
                                            "lint.manifest003")
                                else:
                                        manifests.append(manifest)

                elif manifest:
                        lint_logger.critical(
                            _("Manifest {0} does not declare fmri.").format(filename),
                            "lint.manifest003")
                else:
                        manifests.append(None)
        return manifests

def _make_list(opt):
        """Makes a list out of opt, and returns it."""

        if isinstance(opt, list):
                return opt
        elif opt is None:
                return []
        else:
                return [opt]


if __name__ == "__main__":
        misc.setlocale(locale.LC_ALL, "", error)
        gettext.install("pkg", "/usr/share/locale",
            codeset=locale.getpreferredencoding())
        misc.set_fd_limits(printer=error)

        if six.PY3:
                # disable ResourceWarning: unclosed file
                warnings.filterwarnings("ignore", category=ResourceWarning)
        try:
                __ret = main_func()
        except (PipeError, KeyboardInterrupt):
                # We don't want to display any messages here to prevent
                # possible further broken pipe (EPIPE) errors.
                __ret = EXIT_BADOPT
        except SystemExit as __e:
                __ret = __e.code
        except (apx.InvalidDepotResponseException, tx.TransportFailures) as __e:
                error(__e)
                __ret = EXIT_BADOPT
        except:
                traceback.print_exc()
                error(misc.get_traceback_message())
                __ret = 99

        sys.exit(__ret)

# Vim hints
# vim:ts=8:sw=8:et:fdm=marker
