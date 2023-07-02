#!/usr/bin/env false
from os import path
import re
import tempfile
import subprocess
import pdb
from pathlib import Path
import pickle
import typing as T
import os
from .meson_codegen import *
from enum import Enum
from . import heuristics

optional_deps = {
    "mpfr": "lib",
    "gmp": "lib",
    "metis": "lib",
    "readline": "lib",
    "perf_main": "lib",
    "GL": "lib",
    "CGAL": "dep",
    "zoltan": "broken",
    "mgrid": "broken",
    "ccmio": "broken",
    "kahip": "broken",
    "scotch": "broken",
    "scotcherrexit": "broken",
    "ptscotch": "broken",
    "ptscotcherrexit": "broken",
}


# Indicates that scan_wmake.py saw something too complicated in Make/files
class EncountedComplexConfig(Exception):
    pass


# Turns a string into a valid identifier that can be used as a variable name in meson.build
def mangle_name(name):
    return name.replace("-", "_").replace("/", "_slash_")


ACTIVATE_CACHE = False


# Kind of broken since it does not hash the function arguments
def disccache(original_func):
    def new_func(*args, **kwargs):
        if not ACTIVATE_CACHE:
            return original_func(*args, **kwargs)
        fp = Path("disccache") / (original_func.__name__ + ".pickle")
        if fp.exists():
            print(f"Loading cache from {fp}")
            return pickle.load(open(fp, "rb"))
        else:
            ret = original_func(*args, **kwargs)
            pickle.dump(ret, open(fp, "wb"))
            return ret

    return new_func


# Find all directories that have a subdirectory called Make and are not marked as broken or ignored.
@disccache
def find_all_wmake_dirs(PROJECT_ROOT):
    scanning_disabled = [Path(p) for p in heuristics.scanning_disabled()]
    ret = []
    for el in PROJECT_ROOT.rglob("Make"):
        if not path.isdir(el):
            continue
        el = el.relative_to(PROJECT_ROOT)
        el = el.parent
        if "codeTemplates" in el.parts:
            continue
        if el in scanning_disabled:
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


def parse_options_file(PROJECT_ROOT, wmake_dir):
    makefilesource = (PROJECT_ROOT / wmake_dir / "Make" / "options").read_text()
    makefilesource = commentRemover(makefilesource)
    makefilesource = makefilesource.replace("include $(GENERAL_RULES)/mpi-rules", "")

    vardict = {
        "$(LIB_SRC)": path.relpath("src", wmake_dir),
        "${LIB_SRC}": path.relpath("src", wmake_dir),
        "$(FOAM_UTILITIES)": path.relpath("applications/utilities", wmake_dir),
        "$(FOAM_SOLVERS)": path.relpath("applications/solvers", wmake_dir),
        "$(GENERAL_RULES)": str(PROJECT_ROOT / "wmake/rules/General"),
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
        # print(makeout.name)
        # import time

        # time.sleep(10000)
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
def all_parse_options_file(PROJECT_ROOT, wmake_dirs):
    return {
        wmake_dir: parse_options_file(PROJECT_ROOT, wmake_dir)
        for wmake_dir in wmake_dirs
    }


class Include:
    pass


class RecursiveInclude(Include):
    path: Path

    def __init__(self, path):
        self.path = path


class NonRecursiveInclude(Include):
    path: Path

    def __init__(self, path):
        self.path = path


class TargetType(Enum):
    exe = 1
    lib = 2


class GeneralizedSourcefile:
    pass


class SimpleSourcefile(GeneralizedSourcefile):
    path: Path

    def __init__(self, path):
        self.path = path


class FlexgenSourcefile(GeneralizedSourcefile):
    path: Path

    def __init__(self, path):
        self.path = path


class LyyM4Sourcefile(GeneralizedSourcefile):
    path: Path

    def __init__(self, path):
        self.path = path


class CverSourcefile(GeneralizedSourcefile):
    path: Path

    def __init__(self, path):
        self.path = path


class Intermediate:
    srcs: T.List[GeneralizedSourcefile]
    varname: str
    typ: TargetType

    def __init__(self, srcs, varname, typ):
        self.srcs = srcs
        self.varname = varname
        self.typ = typ


def substitute(vardict, cur):
    while True:
        old = cur
        for el in vardict:
            cur = cur.replace(el, vardict[el])
        if cur == old:
            return cur


# find -name files -type f -not -path ./wmake/makefiles/files | xargs rg "#" --
hardcoded_specials = {
    "precision": """
#if !defined(WM_DP)
primitives/Vector/doubleVector/doubleVector.C
primitives/Tensor/doubleTensor/doubleTensor.C
#endif
#if !defined(WM_SP) && !defined(WM_SPDP)
primitives/Vector/floatVector/floatVector.C
primitives/Tensor/floatTensor/floatTensor.C
#endif
""",
    "sunstack1": """
#ifdef SunOS64
dummyPrintStack.C
#else
printStack.C
#endif
""",
    "sunstack2": """
#ifdef __sun__
printStack/dummyPrintStack.C
#else
printStack/printStack.C
#endif
""",
}

special_oldnewstub = """
#if OPENFOAM > 1812
newStub.C
#else
oldStub.C
#endif
"""


def parse_files_file(PROJECT_ROOT, api_version, wmake_dir):
    specials = []
    path = PROJECT_ROOT / wmake_dir / "Make" / "files"
    src = path.read_text()
    src = commentRemover(src)

    for special, hardcoded in hardcoded_specials.items():
        if hardcoded in src:
            specials.append(special)
            src = src.replace(hardcoded, "\n")

    if special_oldnewstub in src:
        if int(api_version) > 1812:
            src = src.replace(special_oldnewstub, "\nnewStub.C\n")
        else:
            src = src.replace(special_oldnewstub, "\noldStub.C\n")

    lines = src.split("\n")
    lines = [line.strip() for line in lines if line.strip() != ""]

    srcs = []
    varname = None
    typ = None
    vardict = {}
    for line in lines:
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
            elif line.endswith(".Cver"):
                assert "$" not in line
                srcs.append(CverSourcefile(PROJECT_ROOT / wmake_dir / line))
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
                raise EncountedComplexConfig(
                    f"The file '{path}' contains the following line, but I do not know how to handle that:\n{line}"
                )
        else:
            raise EncountedComplexConfig(
                f"The file '{path}' contains the following line, but I do not know how to handle that:\n{line}"
            )
    return (
        Intermediate(
            srcs=srcs,
            varname=varname,
            typ=typ,
        ),
        specials,
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
                if el != "-DCGAL_INEXACT":
                    compile_flags.append(f"'{el}'")
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

                if not PROJECT_ROOT in abspath.parents:
                    # If abspath is not inside of PROJECT_ROOT, then 'path.relative_to(project_root)' at grepmarker_relto_inc will crash
                    options_path = PROJECT_ROOT / wmake_dir / "Make" / "options"
                    raise EncountedComplexConfig(
                        f"It seems like '{options_path}' is telling us to pass '-I{abspath}' to the compiler. But this path is outside of '{PROJECT_ROOT}', which is (currently) not supported."
                    )

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
            if el in [
                "boost_system",
                "fftw3",
                "mpi",
                "z",
            ] + list(optional_deps.keys()):
                dependencies.append(el.lower() + "_dep")
            else:
                order_depends.append("lib_" + mangle_name(el))
    return order_depends, dependencies
