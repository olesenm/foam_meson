#!/usr/bin/env false
from os import path
import re
import tempfile
import subprocess
import pdb
from pathlib import Path
import pickle
from dataclasses import dataclass
import typing as T
import os
from meson_codegen import *
from enum import Enum

# todo: build scotch manually
optional_deps = {
    "mpfr": "lib",
    "gmp": "lib",
    "metis": "lib",
    "zoltan": "lib",
    "mgrid": "lib",
    "ccmio": "lib",
    "readline": "lib",
    "kahip": "dep",
    "scotch": "dep",
    "CGAL": "dep",
}

# Turns a string into a valid identifier that can be used as a variable name in meson.buil
def mangle_name(name):
    return name.replace("-", "_").replace("/", "_slash_")


# Kind of broken since it does not hash the function arguments
def disccache(original_func):
    def new_func(*args, **kwargs):
        fp = Path("disccache") / original_func.__name__
        if fp.exists():
            return pickle.load(open(fp, "rb"))
        else:
            ret = original_func(*args, **kwargs)
            pickle.dump(ret, open(fp, "wb"))
            return ret

    return new_func


# Find all directories that have a subdirectory called Make and are not marked as broken or ignored.
@disccache
def find_all_wmake_dirs(PROJECT_ROOT, yamldata):
    disable_scanning = [PROJECT_ROOT / p for p in yamldata["disable_scanning"]]
    ret = []
    for el in PROJECT_ROOT.rglob("Make"):
        if not path.isdir(el):
            continue
        el = el.parent
        if "codeTemplates" in el.parts:
            continue
        if el in disable_scanning:
            continue
        ret.append(el)
    return ret


# https://gist.github.com/ChunMinChang/88bfa5842396c1fbbc5b
def commentRemover(text):
    def replacer(match):
        s = match.group(0)
        if s.startswith("/"):
            return " "  # note: a space and not an empty string
        else:
            return s

    pattern = re.compile(
        r'//.*?$|/\*.*?\*/|\'(?:\\.|[^\\\'])*\'|"(?:\\.|[^\\"])*"',
        re.DOTALL | re.MULTILINE,
    )
    return re.sub(pattern, replacer, text)


def parse_options_file(wmake_dir):
    with open(wmake_dir / "Make" / "options") as infile:
        makefilesource = infile.read()
    makefilesource = commentRemover(makefilesource)
    makefilesource = makefilesource.replace("include $(GENERAL_RULES)/mpi-rules", "")

    vardict = {
        "$(LIB_SRC)": path.relpath("src", wmake_dir),
        "${LIB_SRC}": path.relpath("src", wmake_dir),
        "$(FOAM_UTILITIES)": path.relpath("applications/utilities", wmake_dir),
        "$(FOAM_SOLVERS)": path.relpath("applications/solvers", wmake_dir),
        "$(GENERAL_RULES)": "wmake/rules/General",
        "$(PLIBS)": "-lmpi",
        "$(PFLAGS)": "-DMPICH_SKIP_MPICXX -DOMPI_SKIP_MPICXX",
    }

    with tempfile.NamedTemporaryFile("w") as makeout:
        for key in vardict:
            makeout.write(key[2:-1] + "=" + vardict[key] + "\n")
        makeout.write(makefilesource)
        makeout.write(
            "\nprint_stuff:\n\techo $(LIB_INC)\n\techo $(EXE_INC)\n\techo $(LIB_LIBS)\n\techo $(EXE_LIBS)\n"
        )
        makeout.flush()
        vars = (
            subprocess.check_output(
                "make -s print_stuff --file " + makeout.name,
                shell=True,
                # env={"PATH": os.environ["PATH"]},
            )
            .decode()
            .split("\n")
        )
    vardict["$(LIB_INC)"] = vars[0]
    vardict["$(EXE_INC)"] = vars[1]
    vardict["$(LIB_LIBS)"] = vars[2]
    vardict["$(EXE_LIBS)"] = vars[3]
    assert vars[0] == "" or vars[1] == ""
    assert vars[2] == "" or vars[3] == ""
    return vardict


@disccache
def all_parse_options_file(wmake_dirs):
    return {wmake_dir: parse_options_file(wmake_dir) for wmake_dir in wmake_dirs}


class Include:
    pass


@dataclass
class RecursiveInclude(Include):
    path: Path


@dataclass
class NonRecursiveInclude(Include):
    path: Path


def preprocess_files_file(wmake_dir):
    preprocessed = subprocess.check_output(
        [
            "cpp",
            # "-traditional-cpp",
            "-DOPENFOAM=2006",
            wmake_dir / "Make" / "files",
        ],
    ).decode()
    preprocessed = "\n".join(
        [
            line.rstrip()
            for line in preprocessed.split("\n")
            if not line.startswith("#") and not line.rstrip() == ""
        ]
    )
    return preprocessed


@disccache
def all_preprocess_files_file(wmake_dirs):
    return {wmake_dir: preprocess_files_file(wmake_dir) for wmake_dir in wmake_dirs}


class TargetType(Enum):
    exe = 1
    lib = 2


class GeneralizedSourcefile:
    pass


@dataclass
class SimpleSourcefile(GeneralizedSourcefile):
    path: Path


@dataclass
class FlexgenSourcefile(GeneralizedSourcefile):
    path: Path


@dataclass
class LyyM4Sourcefile(GeneralizedSourcefile):
    path: Path


@dataclass
class FoamConfigSourcefile(GeneralizedSourcefile):
    pass


@dataclass
class Intermediate:
    srcs: T.List[GeneralizedSourcefile]
    varname: str
    typ: TargetType


def substitute(vardict, cur):
    while True:
        old = cur
        for el in vardict:
            cur = cur.replace(el, vardict[el])
        if cur == old:
            return cur


def parse_files_file(PROJECT_ROOT, wmake_dir, preprocessed):
    srcs = []
    varname = None
    typ = None
    vardict = {}
    for line in preprocessed.split("\n"):
        if line.startswith("EXE"):
            line = remove_prefix(line, "EXE")
            line = remove_prefix(line, "=")
            if line.startswith("$(FOAM_APPBIN)"):
                line = remove_prefix(line, "$(FOAM_APPBIN)/")
            elif line.startswith("$(FOAM_USER_APPBIN)"):
                line = remove_prefix(line, "$(FOAM_USER_APPBIN)/")
            else:
                line = remove_prefix(line, "$(PWD)/")
            assert "$" not in line
            assert varname is None
            varname = "exe_" + mangle_name(line)
            typ = TargetType.exe
        elif line.startswith("LIB"):
            line = remove_prefix(line, "LIB")
            line = remove_prefix(line, "=")
            if line.startswith("$(FOAM_LIBBIN)/"):
                line = remove_prefix(line, "$(FOAM_LIBBIN)/")
            elif line.startswith("$(FOAM_MPI_LIBBIN)/"):
                line = remove_prefix(line, "$(FOAM_MPI_LIBBIN)/")
            else:
                line = remove_prefix(line, "$(FOAM_USER_LIBBIN)/")
            if line == "":
                continue
            line = "/".join(
                line.split("/")[:-1] + [remove_prefix(line.split("/")[-1], "lib")]
            )
            assert "$" not in line
            assert varname is None
            varname = "lib_" + mangle_name(line)
            typ = TargetType.lib
        elif "=" in line:
            ar = line.split("=")
            assert len(ar) == 2, line
            vardict["$(" + ar[0].rstrip() + ")"] = ar[1].strip()
        elif " " not in line:
            if line.endswith(".lyy-m4"):
                line = substitute(vardict, line)
                assert "$" not in line
                srcs.append(LyyM4Sourcefile(PROJECT_ROOT / wmake_dir / line))
            elif line.endswith(".L"):
                assert "$" not in line
                srcs.append(FlexgenSourcefile(PROJECT_ROOT / wmake_dir / line))
            elif line == "global/foamConfig.Cver":
                srcs.append(FoamConfigSourcefile())
            elif (
                line.endswith(".hpp")
                or line.endswith(".H")
                or line.endswith(".cpp")
                or line.endswith(".C")
                or line.endswith(".cc")
                or line.endswith(".cxx")
            ):
                line = substitute(vardict, line)
                assert "$" not in line
                srcs.append(SimpleSourcefile(PROJECT_ROOT / wmake_dir / line))
            else:
                raise ValueError(line)
        else:
            raise ValueError(line)
    return Intermediate(
        srcs=srcs,
        varname=varname,
        typ=typ,
    )


def calc_includes_and_flags(
    PROJECT_ROOT, wmake_dir, optionsdict
) -> T.Tuple[T.List[Include], T.List[str]]:
    includes: T.List[Include] = [
        NonRecursiveInclude(PROJECT_ROOT / wmake_dir),
    ]
    compile_flags: T.List[str] = []
    for inckey in ["$(EXE_INC)", "$(LIB_INC)"]:
        for arg in optionsdict[inckey].split(" "):
            el = arg.lstrip()
            if el == "":
                continue
            if el.startswith("-D") or el in ["-g", "-O0", "-Wno-old-style-cast"]:
                compile_flags.append(el)
            elif el.startswith("-I"):
                if "$" in el:
                    print(dirpath, "warning: unresolved variable in ", el)
                    continue
                el = remove_prefix(el, "-I")
                if os.path.isabs(el):
                    abspath = Path(el)
                else:
                    abspath = PROJECT_ROOT / wmake_dir / el
                    abspath = Path(os.path.normpath(str(abspath)))
                if abspath.parts[-1] == "lnInclude":
                    recdir = abspath.parent
                    includes.append(RecursiveInclude(recdir))
                    continue
                else:
                    includes.append(NonRecursiveInclude(abspath))
                    continue
                    if path.exists(abspath):
                        incdirs.append("'<PATH>" + str(abspath) + "</PATH>'")
                    else:
                        print(
                            "warning:",
                            abspath,
                            "does not exist",
                        )
                        show_debugging_help(arg)
            else:
                raise NotImplementedError("Unknown compiler flag")
    includes.append(RecursiveInclude(PROJECT_ROOT / wmake_dir)),
    includes.append(RecursiveInclude(PROJECT_ROOT / "src" / "OpenFOAM"))
    includes.append(RecursiveInclude(PROJECT_ROOT / "src" / "OSspecific" / "POSIX"))
    return includes, compile_flags


def calc_libs(optionsdict, typ: TargetType) -> T.List[Include]:
    order_depends: T.List[str] = []
    dependencies: T.List[str] = []
    if typ == TargetType.exe:
        order_depends.append("lib_OpenFOAM")
        dependencies += ["m_dep", "dl_dep"]

    for libkey in ["$(EXE_LIBS)", "$(LIB_LIBS)"]:
        for el in optionsdict[libkey].split(" "):
            el = el.lstrip()
            if el == "":
                continue
            if "$" in el:
                print("warning: unresolved variable in ", el)
                continue
            if el.endswith("libOSspecific.o"):
                order_depends.append("lib_OSspecific")
                continue
            if el == "-pthread":
                dependencies.append("thread_dep")
                continue
            if el.startswith("-L"):
                continue
            if el.startswith("-Wl,") and el.endswith(path.sep + "openmpi"):
                # on my machine: el == "-Wl,/usr/lib/openmpi"
                continue
            if el in [
                "-Wl,-rpath",
                "-Wl,/usr/lib",
                "-Wl,--enable-new-dtags",
            ]:  # These flags orignate from the line
                # PLIBS   = $(shell mpicc --showme:link)
                # in wmake/rules/General/mpi-mpicc-openmpi
                # I don't really know what these flags do, but I think we would notice it if it would be necessary.
                continue
            if not el.startswith("-l"):
                print("warning in ", dirpath, ": not starting with -l: ", el)
                exit(1)
                continue

            el = remove_prefix(el, "-l")
            flag = True
            for lib in [
                "boost_system",
                "fftw3",
                "mpi",
                "z",
            ] + list(optional_deps.keys()):
                if el == lib:
                    dependencies.append(lib.lower() + "_dep")
                    flag = False
            if flag and el not in [
                "scotcherrexit",
                "ptscotch",
                "ptscotcherrexit",
            ]:  # todo remote the "el not in ..." stuff
                order_depends.append("lib_" + mangle_name(el))
    return order_depends, dependencies
