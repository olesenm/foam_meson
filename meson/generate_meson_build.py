#!/usr/bin/env python3

# todo: Doxygen

# todo: unisntall cgal and kahip and check if the build still works

# todo doc reference
# If INCLUDE_METHOD = "SINGLE", then we run into this problem:
# c++: fatal error: cannot execute ‘/usr/lib/gcc/x86_64-pc-linux-gnu/10.2.0/cc1plus’: execv: Argument list too long

# BUILD_LN
# PREBUILD_LN
# SINGLE
INCLUDE_METHOD = "BUILD_LN"
GROUP_FULL_DIRS = True
EXPLAIN_CODEGEN = False
CACHE_TOTDESC = False  # Only enable this if you are know what you are doing

from os import path, listdir, walk
import os
import subprocess
from meson_codegen import *
from scan_wmake import *
import sys
import textwrap
import yaml
import pdb
import cProfile


def from_this_directory():
    os.chdir(path.dirname(sys.argv[0]))


ROOT_PATH = os.getcwd()
PROJECT_ROOT = Path(ROOT_PATH)

from_this_directory()
os.chdir("..")
assert os.environ["WM_PROJECT_DIR"] != "", "Did you forget sourcing etc/bashrc?"

lnIncludes_to_be_generated = set([])


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


sys.excepthook = info

# todo

# what if BOOST_INC_DIR or METIS_INC_DIR or KAHIP_INC_DIR or PTSCOTCH_INC_DIR or SCOTCH_INC_DIR or FFTW_INC_DIR is defined?

# do we actually never need OBJECTS_DIR

# The following should be tested often, because their -I and -l flags are easy to get wrong.
# ninja buoyantBoussinesqPimpleFoam.p/applications_solvers_heatTransfer_buoyantBoussinesqPimpleFoam_buoyantBoussinesqPimpleFoam.cpp.o
# ninja libfieldFunctionObjects.so.p/src_functionObjects_field_PecletNo_PecletNo.cpp.o
# ninja correctBoundaryConditions

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

# todo: If you add a new file and touch meson.build this function will not be run. Is this ok?
def group_full_dirs(files_srcs):
    ret_files = []
    ret_dirs = []
    in_ret = {el: False for el in files_srcs}
    for fp in files_srcs:
        if(fp.suffix == ".C"):
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

def wmake_to_meson(PROJECT_ROOT, used_lnIncludes, wmake_dir, preprocessed, parsed_options):
    dirpath = wmake_dir / "Make"
    optionsdict, specials = parsed_options
    inter = parse_files_file(PROJECT_ROOT, wmake_dir, preprocessed)
    includes = calc_includes(PROJECT_ROOT, wmake_dir, optionsdict)
    order_depends, dependencies = calc_libs(optionsdict, inter.typ)
    if "CGAL" in specials:
        dependencies.append("cgal_dep")
        dependencies.append("mpfr_dep")
        dependencies.append("gmp_dep")

    files_srcs = []
    srcs = []
    template = ""
    for el in inter.srcs:
        match el:
            case SimpleSourcefile(x):
                files_srcs.append(x)
            case FoamConfigSourcefile():
                srcs.append("foamConfig_cpp")
            case FlexgenSourcefile(x):
                srcs.append(f"flexgen.process('<PATH>{x}</PATH>')")
            case LyyM4Sourcefile(x):
                name = remove_suffix(x.parts[-1], ".lyy-m4")
                varname = x.parts[-1]
                for c in "$", ".", "(", ")", "/", "_", "-":
                    varname = varname.replace(c, "_")
                varname + "_cpp"
                template += (
                    f"{varname} = custom_target('{varname}', input: '<PATH>{x}</PATH>', output : '{name}.cc', \n command: [m4lemon, meson.source_root(), '<PATH>{PROJECT_ROOT / wmake_dir}</PATH>', lemonbin, '@INPUT@', '@OUTPUT@' ])\n"
                )
                srcs.append(varname)
            case _:
                raise NotImplemented

    rec_dirs_srcs = []
    if GROUP_FULL_DIRS:
        files_srcs, rec_dirs_srcs = group_full_dirs(files_srcs)

    rec_dirs_srcs = [f"'<PATH>{x}</PATH>'" for x in rec_dirs_srcs]
    rec_dirs_srcs_joined = ",\n    ".join(rec_dirs_srcs)
    # todo: rebuild build.ninja if the rec_dirs directories get touched

    files_srcs = [f"'<PATH>{x}</PATH>'" for x in files_srcs]

    files_srcs_joined = ",\n    ".join(files_srcs)
    srcs.append(f"files({files_srcs_joined})")
    srcs_joined = ",\n    ".join(srcs)
    assert("$" not in srcs_joined)
    template +=f"""srcfiles = [lnInclude_hack, \n    {srcs_joined}]
    rec_dirs_srcs = [{rec_dirs_srcs_joined}]
    foreach dir : rec_dirs_srcs
        srcfiles += run_command(meson.source_root() + '/meson/rec_C.sh', dir, check: true).stdout().strip().split('\\n')
    endforeach
    """

    addspace = "\n    " if len(order_depends) > 0 else ""
    template += (
        "link_with = [\n    " + ",\n    ".join(order_depends) + addspace + "]\n"
    )
    addspace = "\n    " if len(dependencies) > 0 else ""
    template += (
        "dependencies = [\n    " + ",\n    ".join(dependencies) + addspace + "]\n"
    )

    #pdb.set_trace()
    #includes
    cpp_args = []
    for include in includes:
        match include:
            case NonRecursiveInclude(path):
                if path.exists():
                    cpp_args.append(f"'-I' + meson.source_root() / '{path.relative_to(PROJECT_ROOT)}'")
                else:
                    print(f"Warning: {path} does not exist")
            case RecursiveInclude(path):
                if path.exists():
                    cpp_args.append(f"'-I' + meson.build_root() / '{path.relative_to(PROJECT_ROOT)}'")
                else:
                    print(f"Warning: {path} does not exist")
            case _:
                raise NotImplemented

    addspace = "\n    " if len(cpp_args) > 0 else ""
    template += (
        "cpp_args = [\n    " + ",\n    ".join(cpp_args) + addspace + "]\n"
    )

    if wmake_dir == PROJECT_ROOT / "applications/utilities/surface/surfaceBooleanFeatures":
        order_depends.append("lib_PolyhedronReader")
        template += """
        if cgal_dep.found()
            cpp_args += '-I' + meson.source_root() / 'applications/utilities/surface/surfaceBooleanFeatures/PolyhedronReader'
            link_with += lib_PolyhedronReader
            dependencies += cgal_dep
        else
            cpp_args += '-DNO_CGAL'
        endif
        """

    if inter.typ == TargetType.exe:
        template += (
            inter.varname
            + " = executable('"
            + remove_prefix(inter.varname, "exe_")
            + "', srcfiles, link_with: link_with, dependencies: dependencies, install: true, implicit_include_directories: false, cpp_args: cpp_args)\n"
        )
    elif inter.typ == TargetType.lib:
        template += (
            inter.varname
            + " = library('"
            + remove_prefix(inter.varname, "lib_")
            + "', srcfiles, link_with: link_with, dependencies: dependencies, install: true, implicit_include_directories: false, cpp_args: cpp_args)\n"
        )


    if "CGAL" in specials:
        template = textwrap.indent(template, "  ")
        template = (
            "if cgal_dep.found() and mpfr_dep.found() and gmp_dep.found()\n"
            + template
            + "endif\n"
        )

    template = Template(template)
    template.make_absolute(PROJECT_ROOT / wmake_dir)

    template.assert_absolute()
    template.cleanup()
    assert inter.varname not in target_blacklist
    return Node(
        provides=inter.varname,
        ddeps=order_depends,
        template=template,
        outpath=wmake_dir.relative_to(PROJECT_ROOT).parts,
        debuginfo="This recipe originated from " + str(dirpath),
    )


def main():
    hardcoded = [
        "src/mesh/blockMesh",
        "src/parallel/decompose/decompositionMethods",
        "src/parallel/decompose/kahipDecomp",
        "src/parallel/decompose/metisDecomp",
        "src/parallel/decompose/scotchDecomp",
        "src/parallel/decompose/ptscotchDecomp",
        "src/TurbulenceModels/phaseIncompressible",
        "src/TurbulenceModels/phaseCompressible",
        "src/thermophysicalModels/thermophysicalProperties",
        "src/OpenFOAM",
        "src/OSspecific/POSIX",
        "src/fvOptions",
        "src/regionFaModels",
        "src/faOptions",
    ]  # Found using rg wmakeLnInclude
    for el in hardcoded:
        lnIncludes_to_be_generated.add(str(PROJECT_ROOT) + "/" + el + "/lnInclude")
    for el in Path(".").rglob("Make"):
        el = remove_suffix(str(el), "/Make")
        lnIncludes_to_be_generated.add(str(PROJECT_ROOT) + "/" + el + "/lnInclude")

    global used_lnIncludes
    mainsrc = """
    project('OpenFOAM', 'c', 'cpp',
    default_options : ['warning_level=0', 'b_lundef=false', 'b_asneeded=false'])

    cmake = import('cmake')
    fs = import('fs')

    cppc = meson.get_compiler('cpp')

    add_project_arguments('-DWM_LABEL_SIZE='+get_option('WM_LABEL_SIZE'), language : ['c', 'cpp'])
    add_project_arguments('-DWM_ARCH='+get_option('WM_ARCH'), language : ['c', 'cpp'])
    add_project_arguments('-DWM_DP', language : ['c', 'cpp'])
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
    command : [meson.source_root() / 'meson' / 'set_versions_in_foamConfig_Cver.sh', meson.source_root(), '@OUTPUT@'])
    #todo: what if src/bashrc is the wrong script to source?

    # todo: what is the difference between cppc.find_library(...) and dependency(...) ?

    m_dep = cppc.find_library('m')
    dl_dep = cppc.find_library('dl')
    z_dep = cppc.find_library('z')

    mpfr_dep = cppc.find_library('mpfr', required: false)
    gmp_dep = cppc.find_library('gmp', required: false)
    kahip_dep = cppc.find_library('kahip', required: false)
    metis_dep = cppc.find_library('metis', required: false)

    boost_system_dep = dependency('boost', modules : ['system'])
    fftw3_dep = dependency('fftw3')
    mpi_dep = dependency('mpi')
    thread_dep = dependency('threads')
    cgal_dep = dependency('CGAL', required: false)

    #scotch_pro = cmake.subproject('scotch')
    #scotch_dep = scotch_pro.dependency('scotch', include_type: 'system') #todo: is 'system' correct?

    if not cgal_dep.found()
        # applications/utilities/surface/surfaceBooleanFeatures and applications/utilities/surface/surfaceBooleanFeatures/PolyhedronReader are the only directories that needs this flag, but a global argument seems nicer
        add_project_arguments('-DNO_CGAL', language : 'cpp')
    endif

    lemonbin = executable('lemon', 'wmake/src/lemon.c', native: true)

    # Todo: make sure that the generators are only run once

    # Shamelessly stolen from https://github.com/mesonbuild/meson/blob/master/test%20cases/frameworks/8%20flex/meson.build
    flex = find_program('flex')
    flexgen = generator(flex,
    output : '@PLAINNAME@.yy.cpp',
    arguments : ['--c++', '--full', '-o', '@OUTPUT@', '@INPUT@'])

    m4bin = find_program('m4')
    m4gen = generator(m4bin,
    output : '@PLAINNAME@.lyy',
    arguments : ['@INPUT@', '>', '@OUTPUT@']
    )

    lemongen = generator(lemonbin,
    output : '@BASENAME@.cc',
    arguments : ['-Twmake/etc/lempar.c', '-d.', '-ecc', '-Dm4', '@OUTPUT@', '@INPUT@'])

    m4lemon = find_program('meson/m4lemon.sh')

    lnInclude_hack = custom_target(
            output: 'fake.h', #todo: rename
            command: [
                meson.source_root() / 'meson' / 'create_all_symlinks.py',
                meson.source_root(),
                meson.build_root(),
                run_command('date', check: true).stdout().split('\\n')[0] # To make sure that this target is rerun if meson is reconfigured. split('\\n')[0] is there because build.ninja would get a bit ugly.
                ])

    reconfigure_dirs = []
    foreach dir : ['src', 'applications', 'tutorials']
        reconfigure_dirs += run_command('find', meson.source_root() / dir, '-type', 'd', check: true).stdout().split('\\n')
    endforeach
    """
    with open("meson/data.yaml", "r") as stream:
        yamldata = yaml.safe_load(stream)

    wmake_dirs = find_all_wmake_dirs(PROJECT_ROOT, yamldata)
    totdesc = BuildDesc(PROJECT_ROOT)
    used_lnIncludes = set(
        [
            str(PROJECT_ROOT / "src" / "OpenFOAM" / "lnInclude"),
            str(PROJECT_ROOT / "src" / "OSspecific" / "POSIX" / "lnInclude"),
        ]
    )
    preprocessed = all_preprocess_files_file(wmake_dirs)
    parsed_options = all_parse_options_file(wmake_dirs)

    for wmake_dir in wmake_dirs:
        node = wmake_to_meson(
            PROJECT_ROOT, used_lnIncludes, wmake_dir, preprocessed[wmake_dir], parsed_options[wmake_dir]
        )
        totdesc.add_node(node)

    # for path in lnIncludes_to_be_generated:
    #     path = os.path.normpath(path)
    #     path = remove_suffix(path, "/lnInclude")
    #     assert os.path.exists(path)
    #     if not os.path.exists(path):
    #         print(f"warning: {path} does not exist")
    #         continue
    #     name = "lnInc_" + mangle_name(remove_prefix(path, str(PROJECT_ROOT) + "/"))
    #     # linkpaths = run_command(meson.source_root() + '/meson/rec_CH.sh', '<PATH>.</PATH>', check: true).stdout().strip().split('\\n')
    #     # linknames = []
    #     # foreach fp : linkpaths
    #     #     name = fs.name(fp)
    #     #     if not (name in linknames)
    #     #         linknames += name
    #     #     else
    #     #         warning('multiple symlinks want to be created at the same location: ' + name)
    #     #     endif
    #     # endforeach
    #     # {name} = custom_target(
    #     #     #input: linkpaths,
    #     #     output: linknames,
    #     #     command: [meson.source_root() / 'meson' / 'symlink_creator.sh', meson.source_root(), meson.current_source_dir()])
    #     temp = f"""
    #     {name} = custom_target(
    #         build_always_stale: true, #todo
    #         output: 'fake.h', # we can remove all the [0]'s
    #         command: [meson.source_root() / 'meson' / 'symlink_creator.sh', meson.source_root(), meson.current_source_dir()])
    #     """
    #     template = Template(temp)
    #     template.make_absolute(Path(path))
    #     template.assert_absolute()
    #     template.cleanup()
    #     totdesc.add_template(
    #         name,
    #         [],
    #         template,
    #         path,
    #         None,
    #     )

    totdesc.set_custom_prefix(PROJECT_ROOT / "meson.build", mainsrc)

    if EXPLAIN_CODEGEN:
        print(
            "WARNING: You enabled EXPLAIN_CODEGEN. Attempting to build will not work due to broken meson.build files."
        )
        totdesc.explainatory_helper()
        return

    # todo special
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

    # Without these fixes, grouping cannot be done

    totdesc.elements["lib_lagrangianTurbulence"].outpath = Path("src").parts
    totdesc.elements["lib_lagrangianIntermediate"].outpath = Path("src").parts
    totdesc.elements["lib_lagrangianSpray"].outpath = Path("src").parts
    totdesc.elements["lib_coalCombustion"].outpath = Path("src").parts
    totdesc.elements["lib_turbulenceModels"].outpath = Path("src").parts
    totdesc.elements["lib_snappyHexMesh"].outpath = Path("src").parts
    totdesc.elements["lib_compressibleTurbulenceModels"].outpath = Path("src").parts
    totdesc.elements["lib_turbulenceModelSchemes"].outpath = Path("src").parts
    totdesc.elements["lib_radiationModels"].outpath = Path("src").parts
    totdesc.elements["lib_compressibleTurbulenceModels"].outpath = Path("src").parts
    totdesc.elements["lib_liquidPropertiesFvPatchFields"].outpath = Path("src").parts
    totdesc.elements["lib_geometricVoF"].outpath = Path("src").parts

    generated_files = totdesc.writeToFileSystem()


if __name__ == "__main__":
    main()
    # cProfile.run('main()')

# TODO:
# 4 spaces for indentation, no tabs. We do not use tabs.
# no trailing space in code files. Avoids spurious (and noisy) file changes.
#
# For example, take a look at the src/Allwmake file lines 28-45. There you will find some ad hoc handling of linking Pstream/OpenFOAM using a double pass for mingw cross-compilation.
#
# solve the src/OpenFOAM/db/IOstreams/gzstream/version problem
#
# if possible, check that it works on a second system and/or a second installation directory. To ensure we don't have hard-code paths lurking.
#
# Check if we are on windows in src/OSspecific/meson.build
#
# Make a meson branch
#
# TODO: make sure everything gets installed at the same path as with wmake

# todo: mv ~/Sync/git/openfoam some\ dir\ with\ spaces ; cd some\ dir\ with\ spaces ; meson setup builddir; ninja -C builddir

# make sure build.ninja is rebuild if a .C file is added

# https://develop.openfoam.com/Development/openfoam/-/issues/1994

# todo: make whispace in **/meson.build look nice
