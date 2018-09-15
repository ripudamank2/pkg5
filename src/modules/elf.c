/*
 * CDDL HEADER START
 *
 * The contents of this file are subject to the terms of the
 * Common Development and Distribution License (the "License").
 * You may not use this file except in compliance with the License.
 *
 * You can obtain a copy of the license at usr/src/OPENSOLARIS.LICENSE
 * or http://www.opensolaris.org/os/licensing.
 * See the License for the specific language governing permissions
 * and limitations under the License.
 *
 * When distributing Covered Code, include this CDDL HEADER in each
 * file and include the License file at usr/src/OPENSOLARIS.LICENSE.
 * If applicable, add the following below this CDDL HEADER, with the
 * fields enclosed by brackets "[]" replaced with your own identifying
 * information: Portions Copyright [yyyy] [name of copyright owner]
 *
 * CDDL HEADER END
 */

/*
 *  Copyright (c) 2009, 2015, Oracle and/or its affiliates. All rights reserved.
 *  Copyright 2018 OmniOS Community Edition (OmniOSce) Association.
 */

#include <sys/stat.h>
#include <sys/types.h>
#include <sys/uio.h>
#include <fcntl.h>
#include <unistd.h>

#include <elf.h>
#include <gelf.h>

#include <liblist.h>
#include <elfextract.h>

#include <Python.h>

/*
 * When getting information about ELF files, sometimes we want to decide
 * which types of hash we want to calculate. This structure is used to
 * return information from arg parsing Python method arguments.
 *
 * 'fd'      the file descriptor of an ELF file
 * 'sha1'    an integer > 0 if we should calculate an SHA-1 hash
 * 'sha256'  an integer > 0 if we should calculate an SHA-2 256 hash
 *
 */
typedef struct
{
    int fd;
    int sha1;
    int sha256;
} hargs_t;

static int
pythonify_ver_liblist_cb(libnode_t *n, void *info, void *info2)
{
	PyObject *pverlist = (PyObject *)info;
	PyObject *ent;
	dyninfo_t *dyn = (dyninfo_t *)info2;
	char *str;

	if ((str = elf_strptr(dyn->elf, dyn->dynstr, n->nameoff)) == NULL) {
		PyErr_SetString(ElfError, elf_errmsg(-1));
		return (-1);
	}

	ent = Py_BuildValue("s", str);

	return (PyList_Append(pverlist, ent));
}

static int
pythonify_2dliblist_cb(libnode_t *n, void *info, void *info2)
{
	PyObject *pdep = (PyObject *)info;
	dyninfo_t *dyn = (dyninfo_t *)info2;
	char *str;

	PyObject *pverlist;

	pverlist = PyList_New(0);
	if (liblist_foreach(
	    n->verlist, pythonify_ver_liblist_cb, pverlist, dyn) == -1)
		return (-1);

	if ((str = elf_strptr(dyn->elf, dyn->dynstr, n->nameoff)) == NULL) {
		PyErr_SetString(ElfError, elf_errmsg(-1));
		return (-1);
	}

	return (PyList_Append(pdep, Py_BuildValue("[s,O]", str, pverlist)));
}

static int
pythonify_1dliblist_cb(libnode_t *n, void *info, void *info2)
{
	PyObject *pdef = (PyObject *)info;
	dyninfo_t *dyn = (dyninfo_t *)info2;
	char *str;

	if ((str = elf_strptr(dyn->elf, dyn->dynstr, n->nameoff)) == NULL) {
		PyErr_SetString(ElfError, elf_errmsg(-1));
		return (-1);
	}

	return (PyList_Append(pdef, Py_BuildValue("s", str)));
}
/*
 * Open a file named by python, setting an appropriate error on failure.
 */
static int
py_get_fd(PyObject *args)
{
	int fd;
	char *f;

	if (PyArg_ParseTuple(args, "s", &f) == 0) {
		PyErr_SetString(PyExc_ValueError, "could not parse argument");
		return (-1);
	}

	if ((fd = open(f, O_RDONLY)) < 0) {
		PyErr_SetFromErrnoWithFilename(PyExc_OSError, f);
		return (-1);
	}

	return (fd);
}

static hargs_t
py_get_hash_args(PyObject *args, PyObject *kwargs)
{
	int fd = -1;
	char *f;
        int get_sha1 = 1;
        int get_sha256 = 0;

        hargs_t hargs;
        hargs.fd = -1;
        /*
         * By default, we always get an SHA-1 hash, and never get an SHA-2
         * hash.
         */
        hargs.sha1 = 1;
        hargs.sha256 = 0;

        static char *kwlist[] = {"fd", "sha1", "sha256", NULL};

	if (!PyArg_ParseTupleAndKeywords(args, kwargs, "s|ii", kwlist, &f,
            &get_sha1, &get_sha256)) {
		PyErr_SetString(PyExc_ValueError, "could not parse argument");
		return (hargs);
	}

	if ((fd = open(f, O_RDONLY)) < 0) {
		PyErr_SetFromErrnoWithFilename(PyExc_OSError, f);
		return (hargs);
	}

        hargs.fd = fd;
        hargs.sha1 = get_sha1;
        hargs.sha256 = get_sha256;
	return (hargs);
}

/*
 * For ELF operations: Need to check if a file is an ELF object.
 */
/*ARGSUSED*/
static PyObject *
elf_is_elf_object(PyObject *self, PyObject *args)
{
	int fd, ret;

	if ((fd = py_get_fd(args)) < 0)
		return (NULL);

	ret = iself(fd);

	(void) close(fd);

	if (ret == -1)
		return (NULL);

	return (Py_BuildValue("i", ret));
}

/*
 * Returns information about the ELF file in a dictionary
 * of the following format:
 *
 *  {
 *  	type: exe|so|core|rel,
 *  	bits: 32|64,
 *  	arch: sparc|x86|ppc|other|none,
 *  	end: lsb|msb,
 *  	osabi: none|linux|solaris|other
 *  }
 *
 *  XXX: I have yet to find a binary with osabi set to something
 *  aside from "none."
 */
/*ARGSUSED*/
static PyObject *
get_info(PyObject *self, PyObject *args)
{
	int fd;
	hdrinfo_t *hi = NULL;
	PyObject *pdict = NULL;

	if ((fd = py_get_fd(args)) < 0)
		return (NULL);

	if ((hi = getheaderinfo(fd)) == NULL)
		goto out;

	pdict = PyDict_New();
	PyDict_SetItemString(pdict, "type",
	    Py_BuildValue("s", pkg_string_from_type(hi->type)));
	PyDict_SetItemString(pdict, "bits", Py_BuildValue("i", hi->bits));
	PyDict_SetItemString(pdict, "arch",
	    Py_BuildValue("s", pkg_string_from_arch(hi->arch)));
	PyDict_SetItemString(pdict, "end",
	    Py_BuildValue("s", pkg_string_from_data(hi->data)));
	PyDict_SetItemString(pdict, "osabi",
	    Py_BuildValue("s", pkg_string_from_osabi(hi->osabi)));

out:
	if (hi != NULL)
		free(hi);
	(void) close(fd);
	return (pdict);
}

/*
 * Returns a dictionary with the requested hash(es).
 *
 * Dictionary format:
 *
 * {
 *	elfhash: "sha1hash",
 *	pkg.content-type.sha256: "sha2hash"
 * }
 *
 * If a hash was not requested, it is omitted from the dictionary.
 *
 */
/*ARGSUSED*/
static PyObject *
get_hashes(PyObject *self, PyObject *args, PyObject *keywords)
{
	hargs_t		hargs;
	hashinfo_t	*h = NULL;
	PyObject	*pdict = NULL;
	char            hexchars[17] = "0123456789abcdef";

 	hargs = py_get_hash_args(args, keywords);
	if (hargs.fd < 0)
		return (NULL);

 	if ((h = gethashes(hargs.fd, hargs.sha1, hargs.sha256)) == NULL)
		goto out;

 	if ((pdict = PyDict_New()) == NULL)
		goto out;

 	if (hargs.sha1 > 0) {
		int	i;
		char	hexhash[41];

 		for (i = 0; i < 20; i++) {
			hexhash[2 * i] = hexchars[(h->hash[i] & 0xf0) >> 4];
			hexhash[2 * i + 1] = hexchars[h->hash[i] & 0x0f];
		}
		hexhash[40] = '\0';
		if (PyDict_SetItemString(pdict, "elfhash",
			Py_BuildValue("s", hexhash)) != 0)
			goto pyerror;
	}

 	if (hargs.sha256 > 0) {
		int	i;
		char	hexhash[65];
 		for (i = 0; i < 32; i++) {
			hexhash[2 * i] = hexchars[(h->hash256[i] & 0xf0) >> 4];
			hexhash[2 * i + 1] = hexchars[h->hash256[i] & 0x0f];
		}
		hexhash[64] = '\0';
		if (PyDict_SetItemString(pdict, "pkg.content-type.sha256",
			Py_BuildValue("s", hexhash)) != 0)
			goto pyerror;
	}

 	goto out;

 pyerror:
	Py_CLEAR(pdict);

 out:
	(void) close(hargs.fd);

 	if (h != NULL)
		free(h);

 	return (pdict);
}

/*
 * Returns a dictionary with the relevant information.
 *
 * Dictionary format:
 *
 * {
 *	runpath: "/path:/entries",
 *	defs: ["version", ... ],
 *	deps: [["file", ["versionlist"]], ...],
 * }
 *
 * If any item is empty or has no value, it is omitted from the
 * dictionary.
 *
 * XXX: Currently, defs contains some duplicate entries.  There
 * may be meaning attached to this, or it may just be something
 * worth trimming out at this stage or above.
 *
 */
/*ARGSUSED*/
static PyObject *
get_dynamic(PyObject *self, PyObject *args)
{
	int 	i;
	int	fd;
	dyninfo_t 	*dyn = NULL;
	PyObject	*pdep = NULL;
	PyObject	*pdef = NULL;
	PyObject	*pdict = NULL;

	fd = py_get_fd(args);
        if (fd < 0)
		return (NULL);

	if ((dyn = getdynamic(fd)) == NULL)
		goto out;

	if ((pdict = PyDict_New()) == NULL)
		goto out;

	if (dyn->deps->head) {
		if ((pdep = PyList_New(0)) == NULL)
			goto err;
		if (liblist_foreach(
		    dyn->deps, pythonify_2dliblist_cb, pdep, dyn) == -1)
			goto err;
		if (PyDict_SetItemString(pdict, "deps", pdep) != 0)
			goto err;
	}
	if (dyn->def) {
		char *str;

		if ((pdef = PyList_New(0)) == NULL)
			goto err;
		if (liblist_foreach(
		    dyn->vers, pythonify_1dliblist_cb, pdef, dyn) == -1)
			goto err;
		if (PyDict_SetItemString(pdict, "vers", pdef) != 0)
			goto err;
		if ((str = elf_strptr(
		    dyn->elf, dyn->dynstr, dyn->def)) == NULL) {
			PyErr_SetString(ElfError, elf_errmsg(-1));
			goto err;
		}
		if (PyDict_SetItemString(pdict, "def",
		    Py_BuildValue("s", str)) != 0)
			goto err;
	}
	if (dyn->runpath) {
		char *str;

		if ((str = elf_strptr(
		    dyn->elf, dyn->dynstr, dyn->runpath)) == NULL) {
			PyErr_SetString(ElfError, elf_errmsg(-1));
			goto err;
		}
		if (PyDict_SetItemString(pdict, "runpath",
		    Py_BuildValue("s", str)) != 0)
			goto err;
	}

	goto out;

err:
	Py_CLEAR(pdict);

out:
	if (dyn != NULL)
            dyninfo_free(dyn);

	(void) close(fd);
	return (pdict);
}

static PyMethodDef methods[] = {
	{ "is_elf_object", elf_is_elf_object, METH_VARARGS },
	{ "get_info", get_info, METH_VARARGS },
	{ "get_dynamic", (PyCFunction)get_dynamic, METH_VARARGS },
	{ "get_hashes", (PyCFunction)get_hashes,
          METH_VARARGS | METH_KEYWORDS},
	{ NULL, NULL }
};

#if PY_MAJOR_VERSION >= 3
static struct PyModuleDef elfmodule = {
	PyModuleDef_HEAD_INIT,
	"elf",
	NULL,
	-1,
	methods
};
#endif

static PyObject *
moduleinit(void)
{
	PyObject *m;

#if PY_MAJOR_VERSION >= 3
	if ((m = PyModule_Create(&elfmodule)) == NULL)
		return (NULL);
#else
	if ((m = Py_InitModule("elf", methods)) == NULL)
		return (NULL);
#endif

	ElfError = PyErr_NewException("pkg.elf.ElfError", NULL, NULL);
	if (ElfError == NULL)
		return (NULL);

	Py_INCREF(ElfError);
	PyModule_AddObject(m, "ElfError", ElfError);

	return (m);
}

#if PY_MAJOR_VERSION >= 3
PyMODINIT_FUNC
PyInit_elf(void)
{
	return (moduleinit());
}
#else
PyMODINIT_FUNC
initelf(void)
{
	moduleinit();
}
#endif
