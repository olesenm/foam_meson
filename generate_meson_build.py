#!/usr/bin/env python3
import os
import sys
import textwrap
import argparse
import shutil
import typing as T
import re
from pathlib import Path
import src.heuristics
from src.meson_codegen import (
    remove_prefix,
    remove_suffix,
    BuildDesc,
    Template,
    Node,
)
from src.scan_wmake import (
    parse_files_file,
    all_parse_options_file,
    EncountedComplexConfig,
    find_all_wmake_dirs,
    calc_includes_and_flags,
    calc_libs,
    SimpleSourcefile,
    FlexgenSourcefile,
    CverSourcefile,
    LyyM4Sourcefile,
    NonRecursiveInclude,
    RecursiveInclude,
    TargetType,
    mangle_name,
    optional_deps,
)

GROUP_FULL_DIRS = False
EXPLAIN_CODEGEN = False
REGEN_ON_DIR_CHANGE = False
LN_INCLUDE_MODEL = "always_regen"  # "always_regen" or "regen_on_reconfigure"


def from_this_directory():
    os.chdir(os.path.dirname(sys.argv[0]))


# attempting to add a target with one of these names needs to fail immediately to avoid confusing with system libraries
target_blacklist = ["lib_boost_system", "lib_fftw3", "lib_mpi", "lib_z"]


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


def fix_ws_inline(source: str, spaces: int, prefixed: bool = False) -> str:
    source = textwrap.dedent(source)
    source = source.strip("\n")
    source = source.replace("\n", "\n" + " " * spaces)
    if not prefixed and source == "":
        source += "# REMOVE NEWLINE"
    return source


def add_line_if(content: str, cond: bool) -> str:
    if cond:
        return content
    else:
        return "# REMOVE LINE"


# A wrapper around str that changes some whitespace stuff
class WhitespaceFixer:
    temp: str
    regex = re.compile(r"\n((?!# REMOVE LINE).)*# REMOVE LINE\n")

    def __init__(self):
        self.temp = ""

    def __iadd__(self, other):
        if not isinstance(other, str):
            return NotImplementedError
        else:
            other = textwrap.dedent(other)
            other = other.strip("\n")
            if other != "":
                other += "\n"
            self.temp += other
            return self

    def __str__(self):
        ret = self.temp.replace("# REMOVE NEWLINE\n", "")
        ret = self.regex.sub("\n", ret)
        return ret


def wmake_to_meson(project_root, api_version, wmake_dir, parsed_options):
    dirpath = wmake_dir / "Make"
    optionsdict = parsed_options
    inter, specials = parse_files_file(project_root, api_version, wmake_dir)
    includes, cpp_args = calc_includes_and_flags(project_root, wmake_dir, optionsdict)
    order_depends, dependencies = calc_libs(optionsdict, inter.typ)

    template_part_1 = ""
    for el in specials:
        if el == "precision":
            template_part_1 = """
            dp_add = files('primitives/Vector/doubleVector/doubleVector.C', 'primitives/Tensor/doubleTensor/doubleTensor.C')
            sp_add = files('primitives/Vector/floatVector/floatVector.C', 'primitives/Tensor/floatTensor/floatTensor.C')
            if get_option('WM_PRECISION_OPTION') != 'DP'
                srcfiles += dp_add
            elif get_option('WM_PRECISION_OPTION') != 'SP' and get_option('WM_PRECISION_OPTION') != 'SPDP'
                srcfiles += sp_add
            endif
            """
        elif el == "sunstack1":
            template_part_1 = """
            if host_machine.system() == 'sunos'
                srcfiles += files('dummyPrintStack.C')
            else
                srcfiles += files('printStack.C')
            endif
            """
        elif el == "sunstack2":
            template_part_1 = """
            if host_machine.system() == 'sunos'
                srcfiles += files('printStack/dummyPrintStack.C')
            else
                srcfiles += files('printStack/printStack.C')
            endif
            """
        else:
            raise ValueError(f"Unknown special: {el}")

    template = WhitespaceFixer()

    files_srcs = []
    other_srcs = []
    for el in inter.srcs:
        if isinstance(el, SimpleSourcefile):
            files_srcs.append(el.path)
        elif isinstance(el, FlexgenSourcefile):
            other_srcs.append(f"flexgen.process('<PATH>{el.path}</PATH>')")
        elif isinstance(el, CverSourcefile):
            name = remove_suffix(el.path.parts[-1], ".Cver")
            varname = mangle_name(el.path.parts[-1])
            template += f"""
            {varname} = custom_target(
                '{varname}',
                input: '<PATH>{el.path}</PATH>',
                output : '{name}.C',
                command: [meson.source_root() / 'etc' / 'meson_helpers' / 'set_versions_in_Cver.sh', meson.source_root(), '@INPUT@', '@OUTPUT@'])
            """
            other_srcs.append(varname)
        elif isinstance(el, LyyM4Sourcefile):
            name = remove_suffix(el.path.parts[-1], ".lyy-m4")
            varname = mangle_name(el.path.parts[-1])
            template += f"""
            {varname} = custom_target(
                '{varname}',
                input: '<PATH>{el.path}</PATH>',
                output : '{name}.cc',
                command: [m4lemon, meson.source_root(), '<PATH>{project_root / wmake_dir}</PATH>', lemonbin, '@INPUT@', '@OUTPUT@' ])
            """
            other_srcs.append(varname)
        else:
            raise NotImplementedError

    rec_dirs_srcs = []
    if GROUP_FULL_DIRS:
        files_srcs, rec_dirs_srcs = group_full_dirs(files_srcs)
    rec_dirs_srcs_quoted = [f"'<PATH>{x}</PATH>'" for x in rec_dirs_srcs]
    srcs_quoted = (
        ["lnInclude_hack"] + other_srcs + [f"'<PATH>{x}</PATH>'" for x in files_srcs]
    )

    for include in includes:
        if isinstance(include, NonRecursiveInclude):
            path = include.path
            cpp_args.append(
                f"'-I' + meson.source_root() / '{path.relative_to(project_root)}'"  # grepmarker_relto_inc
            )
        elif isinstance(include, RecursiveInclude):
            path = include.path
            cpp_args.append(
                f"'-I' + recursive_include_dirs / '{path.relative_to(project_root)}'"  # grepmarker_relto_inc
            )
        else:
            raise NotImplementedError

    template += f"""
    srcfiles = {fix_ws_inline(to_meson_array(srcs_quoted), 4, True)}
    """
    if len(rec_dirs_srcs_quoted) != 0:
        template += f"""
        rec_dirs_srcs = {fix_ws_inline(to_meson_array(rec_dirs_srcs_quoted), 8, True)}
        foreach dir : rec_dirs_srcs
            srcfiles += run_command(meson.source_root() / 'etc' / 'meson_helpers' / 'rec_C.sh', dir, check: true).stdout().strip().split('\\n')
        endforeach
        """
    template += f"""
    {fix_ws_inline(template_part_1, 4, False)}
    link_with = {fix_ws_inline(to_meson_array(order_depends), 4, True)}
    dependencies = {fix_ws_inline(to_meson_array(dependencies), 4, True)}
    cpp_args = {fix_ws_inline(to_meson_array(cpp_args), 4, True)}
    """

    if wmake_dir == Path("applications/utilities/surface/surfaceBooleanFeatures"):
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
    elif wmake_dir == Path("applications/utilities/preProcessing/viewFactorsGen"):
        template += textwrap.dedent(
            """
        if cgal_dep.found()
            dependencies += cgal_dep
        else
            cpp_args += '-DNO_CGAL'
        endif
        """
        )
    elif is_subdir("src/OpenFOAM", wmake_dir):
        template += textwrap.dedent(
            """
            dependencies += z_dep
            """
        )
    elif is_subdir("applications/utilities/mesh/manipulation/setSet", wmake_dir):
        template += textwrap.dedent(
            """
            if readline_dep.found()
                cpp_args += '-DHAVE_LIBREADLINE'
                dependencies += readline_dep
            endif
            """
        )
    elif is_subdir(
        "applications/utilities/mesh/manipulation/renumberMesh",
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
    elif is_subdir("src/OSspecific/POSIX", wmake_dir):
        template += textwrap.dedent(
            """
            if fs.is_file('/usr/include/sys/inotify.h')
                cpp_args += '-DFOAM_USE_INOTIFY'
            endif
            """
        )

    build_by_default = not (
        is_subdir("tutorials", wmake_dir) or is_subdir("applications/test", wmake_dir)
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
                {add_line_if("build_by_default: false,", not build_by_default)}
            )
    """

    if inter.typ == TargetType.lib:
        template += f"""
        pkg.generate({inter.varname})
        """

    template = Template(str(template))
    template.make_absolute(project_root / wmake_dir)

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
    parent = str(parent)
    child = str(child)
    if child[-1] != os.sep:
        child += os.sep
    if parent[-1] != os.sep:
        parent += os.sep
    assert os.path.isabs(parent) == os.path.isabs(child)
    return child.startswith(parent)


def get_api_version(project_root):
    for line in (project_root / "META-INFO" / "api-info").read_text().split():
        if line.startswith("api="):
            return remove_prefix(line, "api=").strip()
    raise RuntimeError("Unable to get openfoam version")


def inner_generate_meson_build(project_root, args):
    assert project_root.is_absolute()

    files_written = set()

    def copy_file_to_output(inp, outp):
        outp = project_root / outp
        assert outp not in files_written
        files_written.add(outp)
        shutil.copyfile(Path(__file__).parent / "src" / inp, outp)

    if not (project_root / "bin" / "foamEtcFile").is_file():
        raise ValueError(
            "It looks like project_root does not point to an OpenFOAM repository"
        )

    if "WM_PROJECT_DIR" in os.environ:
        print("Warning: It seems like you sourced 'etc/bashrc'. This is unnecessary.")

    api_version = get_api_version(project_root)

    broken_dirs = [Path(p) for p in src.heuristics.broken_dirs()]
    wmake_dirs = find_all_wmake_dirs(project_root)
    totdesc = BuildDesc(project_root)
    parsed_options = all_parse_options_file(project_root, wmake_dirs)
    all_configure_time_recursively_scanned_dirs = set()

    broken_provides = []
    for wmake_dir in wmake_dirs:
        node, configure_time_recursively_scanned_dirs = wmake_to_meson(
            project_root, api_version, wmake_dir, parsed_options[wmake_dir]
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

    if REGEN_ON_DIR_CHANGE:
        recursive_regen_dirs = ["src", "applications", "tutorials"]
    else:
        recursive_regen_dirs = []
    recursive_regen_dirs_joined = ", ".join([f"'{el}'" for el in recursive_regen_dirs])
    recursive_regen_dirs = [project_root / el for el in recursive_regen_dirs]

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

    if meson.version().version_compare('<0.59.0')
        # We need commit 4ca9a16288f51cce99624a2ef595d879acdc02d8 ".C files are now treated as C++ code"
        error('Minimum meson version requred: 0.59.0')
    endif

    devenv = environment()
    devenv.set('WM_PROJECT_DIR', meson.source_root())
    meson.add_devenv(devenv)

    fs = import('fs')
    pkg = import('pkgconfig')

    cppc = meson.get_compiler('cpp')

    add_project_arguments('-DWM_LABEL_SIZE=' + get_option('WM_LABEL_SIZE'), language : ['c', 'cpp'])
    add_project_arguments('-DWM_ARCH=' + get_option('WM_ARCH'), language : ['c', 'cpp'])
    add_project_arguments('-DWM_' + get_option('WM_PRECISION_OPTION'), language : ['c', 'cpp'])
    add_project_arguments('-DNoRepository', language : ['c', 'cpp'])
    add_project_arguments('-DOPENFOAM={api_version}', language : ['c', 'cpp'])
    add_project_arguments('-DOMPI_SKIP_MPICXX', language : ['c', 'cpp'])
    add_project_arguments('-ftemplate-depth-100', language : ['c', 'cpp'])
    add_project_arguments('-m64', language : ['c', 'cpp'])
    add_project_link_arguments('-Wl,--add-needed', language : ['c', 'cpp'])
    add_project_link_arguments('-Wl,--no-as-needed', language : ['c', 'cpp'])
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

    if not cppc.compiles(files('src/OSspecific/POSIX/signals/comptest.C'))
        error('"src/OSspecific/POSIX/signals/comptest.C" failed to compile. Thus, we refuse to compile OpenFOAM because "src/OSspecific/POSIX/signals/sigFpe.C" will fail to compile. Most likely, you are on a linux machine using a libc other than gnu libc. Currently, only gnu libc is supported on linux machines.')
    endif

    m_dep = cppc.find_library('m')
    dl_dep = cppc.find_library('dl')
    z_dep = cppc.find_library('z')
    fftw3_dep = cppc.find_library('fftw3')
    {textwrap.indent(optional_deps_joined, "    ")}

    thread_dep = dependency('threads')
    boost_system_dep = dependency('boost', modules : ['system'])
    # If I do mpi_dep = cppc.find_library('mpi') instead, and test it on a debian machine with the package mpi-default-dev installed, it fails to find <mpi.h>.
    mpi_dep = dependency('mpi', language: 'cpp')

    lemonbin = executable('lemon', 'wmake/src/lemon.c', native: true)

    # Shamelessly stolen from https://github.com/mesonbuild/meson/blob/master/test%20cases/frameworks/8%20flex/meson.build
    flex = find_program('flex')
    flexgen = generator(flex,
    output : '@PLAINNAME@.yy.cpp',
    arguments : ['--c++', '--full', '-o', '@OUTPUT@', '@INPUT@'])

    m4lemon = find_program('etc' / 'meson_helpers' / 'm4lemon.sh')

    recursive_include_dirs = meson.build_root()
    # lnInclude_hack ensures that `ls recursive_include_dirs/some/dir` would show symlinks to all files shown by `find meson.source_root()/some/dir -name "*.[CHh]"`
    """
    ).strip()
    if LN_INCLUDE_MODEL == "regen_on_reconfigure":
        mainsrc += textwrap.dedent(
            """
        lnInclude_hack = custom_target(
            'lnInclude_hack'
            output: 'fake.h',
            command: [
                meson.source_root() / 'etc' / 'meson_helpers' / 'create_all_symlinks.py',
                meson.source_root(),
                recursive_include_dirs,
                run_command('date', check: true).stdout().split('\\n')[0] # To make sure that this target is rerun if meson is reconfigured. split('\\n')[0] is there because build.ninja would get a bit ugly otherwise.
                ])
        """
        )
    elif LN_INCLUDE_MODEL == "always_regen":
        mainsrc += textwrap.dedent(
            """
        lnInclude_hack = custom_target(
            'lnInclude_hack',
            output: 'fake.h',
            command: [
                meson.source_root() / 'etc' / 'meson_helpers' / 'create_all_symlinks.py',
                meson.source_root(),
                recursive_include_dirs,
                ], build_always_stale: true)
        """
        )
    else:
        raise ValueError
    if recursive_regen_dirs_joined != "":
        mainsrc += textwrap.dedent(
            f"""
        if meson.get_cross_property('hack_to_detect_forks_regen_on_dir_change', 0) == 1
            regen_on_dir_change([{recursive_regen_dirs_joined}], recursive: true)
        else
            warning('Your meson version does not support regen_on_dir_change. Either get use the meson version from https://github.com/volker-weissmann/meson , or run "touch ' + meson.source_root() + '/meson.build" everytime you add a new source file. Otherwise you might get a stale build.')
        endif
        """
        )

    totdesc.set_custom_prefix(project_root / "meson.build", mainsrc)

    if EXPLAIN_CODEGEN:
        print(
            "WARNING: You enabled EXPLAIN_CODEGEN. Attempting to build will not work due to broken meson.build files."
        )
        totdesc.explainatory_helper()
        sys.exit(0)

    # There is a nameclash problem. Without this hacky mitigation
    # here, the build will fail.
    # applications/utilities/mesh/generation/extrude2DMesh/extrude2DMesh/meson.build
    # writes a library to
    # builddir/applications/utilities/mesh/generation/extrude2DMesh/extrude2DMesh/libextrude2DMesh.so
    # . That means that the directory
    # builddir/applications/utilities/mesh/generation/extrude2DMesh/extrude2DMesh/
    # will be created. Later,
    # applications/utilities/mesh/generation/extrude2DMesh/meson.build
    # will try to write an executable to
    # builddir/applications/utilities/mesh/generation/extrude2DMesh/extrude2DMesh
    # but it will fail, because you cannot write to a filepath if this
    # filepath is an existing directory.
    # This could be considered a bug in meson, but meson (probably)
    # will not fix this:
    # https://github.com/mesonbuild/meson/issues/8752
    if "exe_extrude2DMesh" in totdesc.elements:
        totdesc.elements["exe_extrude2DMesh"].ideal_path = Path(
            "applications/utilities/mesh"
        ).parts

    totdesc.set_outpaths()
    totdesc.writeToFileSystem(files_written)
    Path(project_root / "etc/meson_helpers").mkdir(exist_ok=True)
    helper_scripts = [
        "get_version.sh",
        "set_versions_in_Cver.sh",
        "m4lemon.sh",
        "create_all_symlinks.py",
    ]
    if GROUP_FULL_DIRS:
        helper_scripts.append("rec_C.sh")
    for fn in helper_scripts:
        outp = Path("etc/meson_helpers") / fn
        copy_file_to_output(fn, outp)
        os.chmod(project_root / outp, 0o755)

    copy_file_to_output("meson_options.txt", "meson_options.txt")
    copy_file_to_output("comptest.C", "src/OSspecific/POSIX/signals/comptest.C")

    old_meson_build = [
        fp for fp in project_root.rglob("meson.build") if fp not in files_written
    ]
    if args.delete_meson_build:
        for fp in old_meson_build:
            fp.unlink()
    else:
        if len(old_meson_build) > 0:
            print(
                f"WARNING: The follow {len(old_meson_build)} files exists, but they are not used. They were not created by this script (at least not in this run). You might want to delete them manually, or pass --delete-meson-build to delete them automatically."
            )
            for fp in old_meson_build:
                print(f"\t{fp}")
            print("")

    return files_written


def main():
    parser = argparse.ArgumentParser(
        description="Generates meson.build files for an OpenFOAM repository."
    )
    parser.add_argument(
        "project-dir", help="Path to the OpenFOAM repository", type=Path
    )
    parser.add_argument(
        "--delete-meson-build",
        action="store_true",
        help="Delete meson.build files that were not generated by this script in this run.",
    )
    args = parser.parse_args()
    project_root = getattr(args, "project-dir")
    if not project_root.exists():
        print(f"ERROR: '{project_root}' does not exist")
        sys.exit(1)
    project_root = project_root.resolve()
    files_written = inner_generate_meson_build(project_root, args)
    print(
        textwrap.dedent(
            f"""
    Finished creating meson.build files, wrote {len(files_written)} files to disk.
    You can now use openfoam like this:
    cd '{project_root}'
    meson setup some_path
    cd some_path
    ninja
    meson devenv # Launches a subshell
    cd '{project_root}/tutorials/basic/laplacianFoam/flange'
    ./Allrun
    Sourcing 'etc/bashrc' is not necessary."""
        )
    )


if __name__ == "__main__":
    try:
        main()
    except EncountedComplexConfig as e:
        print(
            "\nERROR: Unable to generate meson.build files because we just encountered a known limitation in this script:\n"
        )
        assert len(e.args) == 1
        print(e.args[0])
        print(
            "\nIssue Tracker: https://codeberg.org/Volker_Weissmann/foam_meson/issues"
        )
        sys.exit(1)
