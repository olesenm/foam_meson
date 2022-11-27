#!/usr/bin/env python3

GROUP_FULL_DIRS = False
EXPLAIN_CODEGEN = False
CACHE_TOTDESC = False  # Only enable this if you are know what you are doing

from os import path, listdir, walk
import os
from meson_codegen import *
from scan_wmake import *
import sys
import textwrap
import yaml
import pdb
import cProfile
import subprocess
import shutil


def from_this_directory():
    os.chdir(path.dirname(sys.argv[0]))


assert "WM_PROJECT_DIR" not in os.environ, "Don't source etc/bashrc"

# see https://stackoverflow.com/questions/12217537/can-i-force-debugging-python-on-assertionerror
def info(type, value, tb):
    if hasattr(sys, "ps1") or not sys.stderr.isatty():
        # we are in interactive mode or we don't have a tty-like
        # device, so we call the default hook
        sys.__excepthook__(type, value, tb)
    else:
        import traceback, pdb

        # we are NOT in interactive mode, print the exception...
        traceback.print_exception(type, value, tb)
        print
        # ...then start the debugger in post-mortem mode.
        pdb.pm()


# sys.excepthook = info  # Todo: disable before release

# attempting to add a target with one of these names needs to fail immediately to avoid confusing with system libraries
target_blacklist = ["lib_boost_system", "lib_fftw3", "lib_mpi", "lib_z"]


def find_subdirs(dirpath, el, varname="incdirs", include_directories=False):
    assert el[-1] != "/"
    mesonsrc = ""
    fp = el
    if not path.exists(dirpath + "/../" + fp):
        print("warning, path does not exists")
        return ""
    includeDir = dirpath + "/../" + ("/".join(el.split("/")[:-1]))
    # print(dirpath, el, includeDir, fp)
    if include_directories:
        mesonsrc += varname + " += include_directories('" + fp + "')\n"
    else:
        mesonsrc += varname + " += '" + fp + "'\n"
    return mesonsrc
    for entries in walk(includeDir, topdown=False):
        flag = False
        for fp in entries[2]:
            if (
                fp.endswith(".hpp")
                or fp.endswith(".cpp")
                or fp.endswith(".C")
                or fp.endswith(".H")
            ):
                flag = True
        if flag:
            dp = remove_prefix(entries[0], dirpath)
            if include_directories:
                mesonsrc += (
                    varname
                    + " += include_directories('"
                    + "/".join(dp.split("/")[2:])
                    + "')\n"
                )
            else:
                mesonsrc += varname + " += '" + "/".join(dp.split("/")[2:]) + "'\n"
    return mesonsrc


def are_all_files_included(files_srcs, dirname):
    reclist = set()
    for f in dirname.rglob("*.C"):
        if "lnInclude" in f.parts:
            continue
        if f not in files_srcs:
            return False, None
        reclist.add(f)
    return True, reclist


def possible_groupings(files_srcs, fp):
    ret = []
    cur = fp
    ret.append((fp, [fp]))
    while True:
        cur = cur.parent
        flag, reclist = are_all_files_included(files_srcs, cur)
        if not flag:
            break
        ret.append((cur, reclist))
    return ret


def group_full_dirs(files_srcs):
    ret_files = []
    ret_dirs = []
    in_ret = {el: False for el in files_srcs}
    for fp in files_srcs:
        if fp.suffix == ".C":
            if in_ret[fp]:
                continue
            possible_groups = possible_groupings(files_srcs, fp)
            chosen = max(possible_groups, key=lambda x: len(x[1]))
            if chosen[0].is_file():
                ret_files.append(chosen[0])
            else:
                ret_dirs.append(chosen[0])
            for el in chosen[1]:
                in_ret[el] = True
        else:
            ret_files.append(fp)
            in_ret[fp] = True
    return ret_files, ret_dirs


def to_meson_array(python_ar: T.List[str]) -> str:
    if len(python_ar) == 0:
        return "[]"
    else:
        return "[\n" + "".join([f"    {el},\n" for el in python_ar]) + "]"


def fix_ws_inline(src: str, spaces: int, prefixed: bool = False) -> str:
    src = textwrap.dedent(src)
    src = src.strip("\n")
    src = src.replace("\n", "\n" + " " * spaces)
    if not prefixed and src == "":
        src += "# REMOVE NEWLINE"
    return src


# A wrapper around str that changes some whitespace stuff
class WhitespaceFixer:
    temp: str

    def __init__(self):
        self.temp = ""

    def __iadd__(self, other):
        if not isinstance(other, str):
            return NotImplemented
        else:
            other = textwrap.dedent(other)
            other = other.strip("\n")
            if other != "":
                other += "\n"
            self.temp += other
        return self

    def __str__(self):
        return self.temp.replace("# REMOVE NEWLINE\n", "")


def wmake_to_meson(PROJECT_ROOT, wmake_dir, preprocessed, parsed_options):
    dirpath = wmake_dir / "Make"
    optionsdict = parsed_options
    files_list, files_specials = preprocessed
    inter = parse_files_file(PROJECT_ROOT, wmake_dir, files_list)
    includes, cpp_args = calc_includes_and_flags(PROJECT_ROOT, wmake_dir, optionsdict)
    order_depends, dependencies = calc_libs(optionsdict, inter.typ)

    template_part_1 = ""
    for el in files_specials:
        if el == "precision":
            template_part_1 = f"""
            dp_add = files('primitives/Vector/doubleVector/doubleVector.C', 'primitives/Tensor/doubleTensor/doubleTensor.C')
            sp_add = files('primitives/Vector/floatVector/floatVector.C', 'primitives/Tensor/floatTensor/floatTensor.C')
            if get_option('WM_PRECISION_OPTION') != 'DP'
                srcfiles += dp_add
            elif get_option('WM_PRECISION_OPTION') != 'SP' and get_option('WM_PRECISION_OPTION') != 'SPDP'
                srcfiles += sp_add
            endif
            """
        else:
            raise ValueError(f"Unknown special: {el}")

    template = WhitespaceFixer()

    files_srcs = []
    other_srcs = []
    for el in inter.srcs:
        match el:
            case SimpleSourcefile(x):
                files_srcs.append(x)
            case FoamConfigSourcefile():
                other_srcs.append("foamConfig_cpp")
            case FlexgenSourcefile(x):
                other_srcs.append(f"flexgen.process('<PATH>{x}</PATH>')")
            case LyyM4Sourcefile(x):
                name = remove_suffix(x.parts[-1], ".lyy-m4")
                varname = x.parts[-1]
                for c in "$", ".", "(", ")", "/", "_", "-":
                    varname = varname.replace(c, "_")
                varname + "_cpp"
                template += f"""
                {varname} = custom_target(
                    '{varname}',
                    input: '<PATH>{x}</PATH>',
                    output : '{name}.cc',
                    command: [m4lemon, meson.source_root(), '<PATH>{PROJECT_ROOT / wmake_dir}</PATH>', lemonbin, '@INPUT@', '@OUTPUT@' ])
                """
                other_srcs.append(varname)
            case _:
                raise NotImplemented

    rec_dirs_srcs = []
    if GROUP_FULL_DIRS:
        files_srcs, rec_dirs_srcs = group_full_dirs(files_srcs)
    rec_dirs_srcs_quoted = [f"'<PATH>{x}</PATH>'" for x in rec_dirs_srcs]
    srcs_quoted = (
        ["lnInclude_hack"] + other_srcs + [f"'<PATH>{x}</PATH>'" for x in files_srcs]
    )

    for include in includes:
        match include:
            case NonRecursiveInclude(path):
                if path.exists():
                    cpp_args.append(
                        f"'-I' + meson.source_root() / '{path.relative_to(PROJECT_ROOT)}'"
                    )
                else:
                    print(f"Warning: {path} does not exist")
            case RecursiveInclude(path):
                if path.exists():
                    cpp_args.append(
                        f"'-I' + meson.build_root() / '{path.relative_to(PROJECT_ROOT)}'"
                    )
                else:
                    print(f"Warning: {path} does not exist")
            case _:
                raise NotImplemented

    template += f"""
    srcfiles = {fix_ws_inline(to_meson_array(srcs_quoted), 4, True)}
    """
    if len(rec_dirs_srcs_quoted) != 0:
        template += f"""
        rec_dirs_srcs = {fix_ws_inline(to_meson_array(rec_dirs_srcs_quoted), 8, True)}
        foreach dir : rec_dirs_srcs
            srcfiles += run_command(meson.source_root() + '/meson/rec_C.sh', dir, check: true).stdout().strip().split('\\n')
        endforeach
        """
    template += f"""
    {fix_ws_inline(template_part_1, 4, False)}
    link_with = {fix_ws_inline(to_meson_array(order_depends), 4, True)}
    dependencies = {fix_ws_inline(to_meson_array(dependencies), 4, True)}
    cpp_args = {fix_ws_inline(to_meson_array(cpp_args), 4, True)}
    """

    if (
        wmake_dir
        == PROJECT_ROOT / "applications/utilities/surface/surfaceBooleanFeatures"
    ):
        order_depends.append("lib_PolyhedronReader")
        template += textwrap.dedent(
            """
        if cgal_dep.found()
            cpp_args += '-I' + meson.source_root() / 'applications/utilities/surface/surfaceBooleanFeatures/PolyhedronReader'
            link_with += lib_PolyhedronReader
            dependencies += cgal_dep
        else
            cpp_args += '-DNO_CGAL'
        endif
        """
        )
    elif is_subdir(PROJECT_ROOT / "src/OpenFOAM", wmake_dir):
        template += textwrap.dedent(
            """
            dependencies += z_dep
            """
        )
    elif is_subdir(
        PROJECT_ROOT / "applications/utilities/mesh/manipulation/setSet", wmake_dir
    ):
        template += textwrap.dedent(
            """
            if readline_dep.found()
                cpp_args += '-DHAVE_LIBREADLINE'
                dependencies += readline_dep
            endif
            """
        )
    elif is_subdir(
        PROJECT_ROOT / "applications/utilities/mesh/manipulation/renumberMesh",
        wmake_dir,
    ):
        template += textwrap.dedent(
            """
            if zoltan_dep.found()
                cpp_args += '-DHAVE_ZOLTAN'
                dependencies += zoltan_dep
            endif
            """
        )
    elif is_subdir(PROJECT_ROOT / "src/OSspecific/POSIX", wmake_dir):
        template += textwrap.dedent(
            """
            if fs.is_file('/usr/include/sys/inotify.h')
                cpp_args += -DFOAM_USE_INOTIFY'
            endif
            """
        )

    func = None
    name = None
    if inter.typ == TargetType.exe:
        func = "executable"
        name = remove_prefix(inter.varname, "exe_")
    elif inter.typ == TargetType.lib:
        func = "library"
        name = remove_prefix(inter.varname, "lib_")
    template += f"""
            {inter.varname} = {func}(
                '{name}',
                srcfiles,
                link_with: link_with,
                dependencies: dependencies,
                cpp_args: cpp_args,
                implicit_include_directories: false,
                install: true,
            )
    """
    if inter.typ == TargetType.lib:
        template += f"""
        pkg.generate({inter.varname})
        """

    template = Template(str(template))
    template.make_absolute(PROJECT_ROOT / wmake_dir)

    template.assert_absolute()
    template.cleanup()
    assert inter.varname not in target_blacklist
    return (
        Node(
            provides=inter.varname,
            ddeps=order_depends,
            template=template,
            ideal_path=wmake_dir.parts,
            debuginfo="This recipe originated from " + str(dirpath),
        ),
        rec_dirs_srcs,
    )


def is_subdir(parent, child):
    return str(child).startswith(os.path.abspath(str(parent)) + os.sep)


from json import JSONEncoder


class MyEncoder(JSONEncoder):
    def default(self, o):
        return o.__dict__


def main():
    from_this_directory()
    os.chdir("..")
    Path("disccache").mkdir(exist_ok=True)

    PATCH_OUTPUT = "patch.diff"
    PROJECT_ROOT = Path(os.getcwd()) / "disccache" / "dev"

    if not PROJECT_ROOT.exists():
        subprocess.check_call(
            [
                "git",
                "clone",
                "https://develop.openfoam.com/Development/openfoam.git",
                PROJECT_ROOT,
                "--depth=1",
            ]
        )

    if "## About OpenFOAM" not in (PROJECT_ROOT / "README.md").read_text():
        raise ValueError(
            "It looks like PROJECT_ROOT does not point to an OpenFOAM repository"
        )

    with open("meson/data.yaml", "r") as stream:
        yamldata = yaml.safe_load(stream)
    broken_dirs = [PROJECT_ROOT / p for p in yamldata["broken_dirs"]]

    wmake_dirs = find_all_wmake_dirs(PROJECT_ROOT, yamldata)
    totdesc = BuildDesc(PROJECT_ROOT)
    preprocessed = all_preprocess_files_file(PROJECT_ROOT, wmake_dirs)
    parsed_options = all_parse_options_file(PROJECT_ROOT, wmake_dirs)
    all_configure_time_recursively_scanned_dirs = set()

    broken_provides = []
    for wmake_dir in wmake_dirs:
        node, configure_time_recursively_scanned_dirs = wmake_to_meson(
            PROJECT_ROOT, wmake_dir, preprocessed[wmake_dir], parsed_options[wmake_dir]
        )
        if wmake_dir in broken_dirs:
            broken_provides.append(node.provides)
            continue
        all_configure_time_recursively_scanned_dirs.update(
            configure_time_recursively_scanned_dirs
        )
        totdesc.add_node(node)

    totdesc.remove_what_depends_on(broken_provides)
    if len(totdesc.elements) < 100:
        print(
            "WARNING: An unusually low amount of targets were found. We probably did not find the correct OpenFOAM folder"
        )

    recursive_regen_dirs = ["src", "applications", "tutorials"]
    recursive_regen_dirs_joined = ", ".join([f"'{el}'" for el in recursive_regen_dirs])
    recursive_regen_dirs = [PROJECT_ROOT / el for el in recursive_regen_dirs]

    for dirp in all_configure_time_recursively_scanned_dirs:
        assert any(
            is_subdir(el, dirp) for el in recursive_regen_dirs
        ), "If a file in the directory {dirp} or in one of its (recursive) subdirectories is created, meson will not reconfigure itself, but a reconfiguration would be necessary"

    optional_deps_joined = ""
    for name, typ in optional_deps.items():
        if typ in ["dep", "broken"]:
            func = "dependency"
        elif typ == "lib":
            func = "cppc.find_library"
        else:
            raise ValueError()
        varname = name.lower() + "_dep"
        if typ == "broken":
            name = ""
        optional_deps_joined += (
            f"\n{varname} = {func}('{name}', required: false, disabler: true)"
        )

    mainsrc = textwrap.dedent(
        f"""
    project('OpenFOAM', 'c', 'cpp',
    version: run_command('etc' / 'meson_helpers' / 'get_version.sh', '.', check: true).stdout(),
    default_options : ['warning_level=0', 'b_lundef=false', 'b_asneeded=false'])

    cmake = import('cmake')
    fs = import('fs')
    pkg = import('pkgconfig')

    cppc = meson.get_compiler('cpp')

    add_project_arguments('-DWM_LABEL_SIZE=' + get_option('WM_LABEL_SIZE'), language : ['c', 'cpp'])
    add_project_arguments('-DWM_ARCH=' + get_option('WM_ARCH'), language : ['c', 'cpp'])
    add_project_arguments('-DWM_' + get_option('WM_PRECISION_OPTION'), language : ['c', 'cpp'])
    add_project_arguments('-DNoRepository', language : ['c', 'cpp'])
    add_project_arguments('-DOPENFOAM=2006', language : ['c', 'cpp'])
    add_project_arguments('-DOMPI_SKIP_MPICXX', language : ['c', 'cpp'])
    add_project_arguments('-ftemplate-depth-100', language : ['c', 'cpp'])
    add_project_arguments('-m64', language : ['c', 'cpp'])
    add_project_link_arguments('-Wl,--add-needed', language : ['c', 'cpp'])
    if cppc.get_id() == 'gcc'
        add_project_arguments('-DWM_COMPILER="Gcc"', language : 'cpp')
    elif cppc.get_id() == 'clang'
        add_project_arguments('-DWM_COMPILER="Clang"', language : 'cpp')
    else
        error('Unknown Compiler. I do not know what to fill in here for the dots: -DWM_COMPILER="..."')
    endif
    if get_option('debug')
        add_project_arguments('-DWM_COMPILE_OPTION="Debug"', language : ['c', 'cpp'])
        add_project_arguments('-DFULLDEBUG', language : ['c', 'cpp'])
        add_project_arguments('-Wfatal-errors', language : ['c', 'cpp'])
        add_project_arguments('-fdefault-inline', language : ['c', 'cpp'])
        add_project_arguments('-finline-functions', language : ['c', 'cpp'])
    else
        add_project_arguments('-DWM_COMPILE_OPTION="Opt"', language : ['c', 'cpp'])
        add_project_arguments('-frounding-math', language : ['c', 'cpp'])
    endif

    foamConfig_cpp = custom_target('foamConfig.cpp',
    output : 'foamConfig.cpp',
    input : 'src/OpenFOAM/global/foamConfig.Cver',
    command : [meson.source_root() / 'etc' / 'meson_helpers' / 'set_versions_in_foamConfig_Cver.sh', meson.source_root(), '@OUTPUT@'])

    m_dep = cppc.find_library('m')
    dl_dep = cppc.find_library('dl')
    z_dep = cppc.find_library('z')
    fftw3_dep = cppc.find_library('fftw3')
    mpi_dep = cppc.find_library('mpi')
    {textwrap.indent(optional_deps_joined, "    ")}

    thread_dep = dependency('threads')
    boost_system_dep = dependency('boost', modules : ['system'])

    lemonbin = executable('lemon', 'wmake/src/lemon.c', native: true)

    # Shamelessly stolen from https://github.com/mesonbuild/meson/blob/master/test%20cases/frameworks/8%20flex/meson.build
    flex = find_program('flex')
    flexgen = generator(flex,
    output : '@PLAINNAME@.yy.cpp',
    arguments : ['--c++', '--full', '-o', '@OUTPUT@', '@INPUT@'])

    m4lemon = find_program('etc' / 'meson_helpers' / 'm4lemon.sh')

    lnInclude_hack = custom_target(
        output: 'fake.h',
        command: [
            meson.source_root() / 'etc' / 'meson_helpers' / 'create_all_symlinks.py',
            meson.source_root(),
            meson.build_root(),
            run_command('date', check: true).stdout().split('\\n')[0] # To make sure that this target is rerun if meson is reconfigured. split('\\n')[0] is there because build.ninja would get a bit ugly otherwise.
            ])

    if meson.get_cross_property('hack_to_detect_forks_regen_on_dir_change', 0) == 1
        regen_on_dir_change([{recursive_regen_dirs_joined}], recursive: true)
    else
        warning('Your meson version does not support regen_on_dir_change. Either get use the meson version from https://github.com/volker-weissmann/meson , or run "touch ' + meson.source_root() + '/meson.build" everytime you add a new source file. Otherwise you might get a stale build.')
    endif
    """
    )

    totdesc.set_custom_prefix(PROJECT_ROOT / "meson.build", mainsrc)

    if EXPLAIN_CODEGEN:
        print(
            "WARNING: You enabled EXPLAIN_CODEGEN. Attempting to build will not work due to broken meson.build files."
        )
        totdesc.explainatory_helper()
        return

    # There is a nameclash problem: Without this hacky mitigation
    # here, the build will fail:
    # applications/utilities/mesh/generation/extrude2DMesh/extrude2DMesh/meson.build
    # writes a library to
    # builddir/applications/utilities/mesh/generation/extrude2DMesh/extrude2DMesh/libextrude2DMesh.so
    # . That means that the directory
    # builddir/applications/utilities/mesh/generation/extrude2DMesh/extrude2DMesh/
    # will be created. Later,
    # applications/utilities/mesh/generation/extrude2DMesh/meson.build
    # will try write an executable to
    # builddir/applications/utilities/mesh/generation/extrude2DMesh/extrude2DMesh
    # but will fail, because you cannot write to a filepath if this
    # filepath is an existing directory.
    # This could be considered a bug in meson, but meson (probably)
    # will not fix this:
    # https://github.com/mesonbuild/meson/issues/8752
    totdesc.elements["exe_extrude2DMesh"].outpath = Path(
        "applications/utilities/mesh"
    ).parts

    totdesc.set_outpaths()
    totdesc.writeToFileSystem()
    Path(PROJECT_ROOT / "etc/meson_helpers").mkdir(exist_ok=True)
    for fn in [
        "get_version.sh",
        "set_versions_in_foamConfig_Cver.sh",
        "m4lemon.sh",
        "create_all_symlinks.py",
    ]:
        shutil.copyfile(f"meson/{fn}", PROJECT_ROOT / "etc/meson_helpers" / fn)
    shutil.copyfile("meson_options.txt", PROJECT_ROOT / "meson_options.txt")

    assert (
        os.system(
            f'cd "{PROJECT_ROOT}" && git add -A && git diff HEAD > {os.getcwd() + "/" + PATCH_OUTPUT} && git reset HEAD'
        )
        == 0
    )


if __name__ == "__main__":
    main()
    # cProfile.run('main()')
