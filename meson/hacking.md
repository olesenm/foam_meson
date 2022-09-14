
# The lnInclude Problem:

wmake creates multiple `lnInclude` directories in the source tree, e.g. `src/engine/lnInclude` It takes all .H and .C files in `src/engine` (recursively) and symlinks them into `src/engine/lnInclude`.
^[Note that conflicts exists, e.g. both `src/phaseSystemModels/reactingEuler/multiphaseSystem/BlendedInterfacialModel/blendingMethods/linear/linear.C` and `src/phaseSystemModels/reactingEuler/multiphaseSystem/derivedFvPatchFields/wallBoilingSubModels/partitioningModels/linear/linear.C` exist, leaving us with the question which file `src/phaseSystemModels/reactingEuler/multiphaseSystem/lnInclude/linear.C` should point to. Afaik, it is more or less undefined.]
It then passes e.g `-Isrc/engine/lnInclude` to the compiler.
How can we mirror this with meson? I tried 4 different methods:

## Method 1: Generate the lnInclude directories
The first method mirrors very closely what wmake is doing: Write a script that generates these lnInclude directories and run it using `run_command` at configure time. Why didn't I chose this method?
1. I don't like build artifacts in my source tree.
2. Due to some monumental stupidity on my part, this script took about 80 seconds which is not unacceptably slow, but it would be nice if we could skip those 80 seconds. Why didn't I try to fake it faster? Because I'm stupid and I forgot that you can rewrite stuff. While trying Method 4, I realized that you can rewrite stuff and I it takes 1.8 seconds now.

## Method 2: Include it recursively
The second method is quite simple: Just pass every (recursive) subdir to gcc as an include directory. So instead of `-Isrc/engine/lnInclude` you pass
```
-Isrc/engine/engineMesh/engineMesh -Isrc/engine/engineMesh/fvMotionSolverEngineMesh -Isrc/engine/engineMesh/layerredEngineMesh -Isrc/engine/engineMesh/staticEngineMesh -Isrc/engine/enginePiston -Isrc/engine/engineTime -Isrc/engine/engineTime/crankConRod -Isrc/engine/engineTime/engineTime -Isrc/engine/engineTime/freePiston -Isrc/engine/engineValue -Isrc/engine/ignition -Isrc/engine/include
```
This can be done quite nicely in meson:
```meson
inc_dirs = ['other',  'include',  'dirs']
inc_dirs += run_command('find', 'src/engine', '-type', 'd', check: true).stdout().split('\\n')
executable(..., inc_dirs: inc_dirs, ...)
```
Unfortunately we end up with up to 6000(!) include directories, which is too much for gcc:
```
c++: fatal error: cannot execute ‘/usr/lib/gcc/x86_64-pc-linux-gnu/10.2.0/cc1plus’: execv: Argument list too long
```
Also, meson/ninja get significantly slower if we do this.

## Method 3:
The third method is a bit hacky:
`src/engine/meson.build`:
```meson
lnInc_src_engine = custom_target(output: 'fake.h', command: [meson.source_root() / 'meson' / 'symlink_creator.sh', meson.source_root(), meson.current_source_dir()])
```
`src/surfMesh/meson.build`:
```meson
lnInc_src_surfMesh = custom_target(output: 'fake.h', command: [meson.source_root() / 'meson' / 'symlink_creator.sh', meson.source_root(), meson.current_source_dir()])
```
`src/meson.build`:
```meson
...
srcfiles = [lnInc_src_engine[0], lnInc_src_surfMesh[0], files('some/file.C', 'some/other/file.C')]
executable('exename', srcfiles, ...)
```
This will pass `'-I' + meson.build_root() + '/src/engine'` and `'-I' + meson.build_root() + '/src/surfMesh'` to the compiler. Unfortunately we cannot control the order of those flags so compilation will not work.

## Method 4:
The method I finally settled on:
```meson
lnInclude_hack = custom_target(
            output: 'fake.h',
            command: [
                meson.source_root() / 'meson' / 'create_all_symlinks.py',
                meson.source_root(),
                meson.build_root(),
                run_command('date', check: true).stdout().split('\\n')[0] # To make sure that this target is rerun if meson is reconfigured. split('\\n')[0] is there because build.ninja would get a bit ugly otherwise.
                ])
srcfiles = [lnInclude_hack, files('some/file.C', 'some/other/file.C')]
executable('exename', srcfiles, ...)
```

# Todo
- Compiling other OpenFoam versions
- write readme stuff
- Uninstall mpi, cgal, scotch, kahip, zoltan, mgridgen and check if the build still works
- Run the unit tests
- make sure everything gets installed at the same path as with wmake
- Make sure the OpenFOAM tutorial works
- run verify_data.py
- mv ~/Sync/git/openfoam some\ dir\ with\ spaces ; cd some\ dir\ with\ spaces ; meson setup builddir; ninja -C builddir
- The following should be tested often, because their -I and -l flags are easy to get wrong.
    - ninja buoyantBoussinesqPimpleFoam.p/applications_solvers_heatTransfer_buoyantBoussinesqPimpleFoam_buoyantBoussinesqPimpleFoam.cpp.o
    - ninja libfieldFunctionObjects.so.p/src_functionObjects_field_PecletNo_PecletNo.cpp.o
    - ninja correctBoundaryConditions

## Maybe Never
- Doxygen

## Things that currently (seem to) make no problem
- rg FOAM_MPI
- rg ${ROUNDING_MATH}
- rg {c++LESSWARN}
- rg $(FASTDUALOCTREE_SRC_PATH)

### Windows
`src/Allwmake` contains:
```bash
case "$WM_COMPILER" in
(Mingw* | Nvidia*)
    # Pstream/OpenFOAM cyclic dependency
    # 1st pass: link as Pstream as single .o object
    WM_MPLIB=dummy Pstream/Allwmake libo
    FOAM_LINK_DUMMY_PSTREAM=libo wmake $targetType OpenFOAM

    # 2nd pass: link Pstream.{dll,so} against libOpenFOAM.{dll,so}
    Pstream/Allwmake $targetType $*

    # Force relink libOpenFOAM.{dll,so} against libPstream.{dll,so}
    OpenFOAM/Alltouch 2>/dev/null
    ;;
(*)
    Pstream/Allwmake $targetType $*
    ;;
esac
```


# Scotch Snippet
```
# Why aren't we affected by https://github.com/mesonbuild/meson/issues/10764 ?
cmake_opts = cmake.subproject_options()
cmake_opts.add_cmake_defines({{'CMAKE_POSITION_INDEPENDENT_CODE': true}})
scotch_pro = cmake.subproject('scotch', options: cmake_opts)
scotch_dep = scotch_pro.dependency('scotch')
scotcherrexit_dep = scotch_pro.dependency('scotcherrexit')
ptscotch_dep = scotch_pro.dependency('ptscotch')
ptscotcherrexit_dep = scotch_pro.dependency('ptscotcherrexit')
```
