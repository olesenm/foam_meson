In [this issue](https://develop.openfoam.com/Development/openfoam/-/issues/1936) we first talked about meson as an alternative build system.  In [this issue](https://develop.openfoam.com/Development/openfoam/-/issues/1984#note_57979) I presented the first prototype. Now we need to talk about how this project should continue. Please either respond in writing, or we can arrange a Jitsi-Meeting in English or German, whatever you prefer.

Example How to build and run:

```shell
git clone https://develop.openfoam.com/Development/openfoam.git
cd openfoam
git checkout 66908158ae
wget https://codeberg.org/Volker_Weissmann/foam_meson_patches/raw/branch/trunk/for_openfoam_commit_hash_66908158ae.diff
git apply ../for_openfoam_commit_hash_66908158ae.diff
meson setup ../build # Takes about 10 seconds
cd ../build
ninja # Takes hours
meson devenv # Launches a subshell that has some environmental variables (among others: $PATH) set.
cd ../openfoam/tutorials/lagrangian/simpleReactingParcelFoam/verticalChannel
./Allrun

```
(You can replace ../build with any path you like, no matter if its inside of the openfoam folder or not.)

Note that the above is a debug build, i.e. equivalent to setting "WM_COMPILE_OPTION=Debug". If you want a release build, i.e. equivalent to "WM_COMPILE_OPTION=Opt", you need to add a flag like this:
```
meson setup ../build --buildtype=release
```

I generated patches for the openfoam version with the commit hash 66908158ae, but I can generate patches for other versions too, just tell me what versions you need patches for.

# Open Issues

I have not looked at the ThirdParty folder yet, but that can follow.

I know that the OpenFOAM project needs to generate binary packages for different distributions. I have not looked closer at that yet, but that can follow.

The following dependencies are currently never used:
 - zoltan
 - mgrid
 - ccmio
 - kahip
 - scotch
Again, fixing this is possible, but I want to fix this after we know what direction the project is gonna take.

## Build Subfolders seperately

One good thing about wmake is that you can copy e.g. the `applications/solvers/lagrangian/reactingParcelFoam/simpleReactingParcelFoam` folder to some other path outside of the openfoam folder, modify the contents a bit and run `wmake` inside that folder to build it. I think we will have to talk about that more than about any other feature. Currently, my build system offers no similar feature, but I have ideas on how to implement something like that.

## OS Support
I only tested it on my ArchLinux machine, and an Debian machine, with the following additional packages installed:
```sh
apt-get install -y git g++ zlib1g-dev libfftw3-dev mpi-default-dev libboost-system-dev flex
```
I installed meson from source, since the packaged version is too old (we need at least 0.59.0).
Support for other OS's should not be much work.


# Advantages over wmake

While wmake is only used by the openfoam project, meson is used by many different projects and has way more/better documentation that wmake. So if you know how to use meson, you know how to use it in the OpenFOAM project. The meson.build files are very easy to read.

`meson setup` generates a compilation_commands.json file with can be [useful to IDE's](https://openfoamwiki.net/index.php/HowTo_Use_OpenFOAM_with_Visual_Studio_Code). No need for any slow hacks anymore.

A clean compile is (afaik, measurements will follow) about as fast as a clean compile with Allwmake. Incremental builds however, are way faster: (Measurements will follow.) Among other things this is due to the fact that if you change a .so file, but you do not add or remove a symbol from it, meson will not relink the .so files and binaries that are linked to it.

If you just want to build a single binary, you ran run `ninja targetname` and it will build this binary and all of its dependencies. With wmake, you either have to run `./Allwmake` in the top directory, which is slow, or manually go into each directory that is a dependency of this binary and run `wmake` there.

If you add "#include something.C" to a source file, then run `wmake`, then remove that line and the file, `wmake` will fail with
```
make: *** No rule to make target 'something.C', needed by '/home/volker/Sync/git/foam_meson/legacy/build/linux64GccDPInt32Opt/src/parallel/reconstruct/faReconstruct/processorFaMeshes.C.dep'.  Stop.
```
You have to run `wclean` to fix this. The same thing works fine with meson/ninja.

If you build (at least a part of) OpenFOAM, then change `WM_COMPILE_OPTION`, and run `./Allwmake`, it will not recompile the things that were compiled with the old `WM_COMPILE_OPTION`. Ninja will recompile everything that is necessary. (With wmake, I had to delete my build folder many times because I forget if I had always set WM_COMPILE_OPTION correctly.)

If your machine is missing a dependency of OpenFOAM, meson will error during the first few seconds and tell you that you are missing that dependency. With wmake on the other hand, it might compile for hours until you see that some header file cannot be found. (Trying to build OpenFOAM on a machine that uses musl-libc instead of glibc was fun.)

With meson, you can do out-of-tree builds.






# Dont Post this




time meson setup ../build
real	0m 9.91s
user	0m 9.38s
sys	0m 0.41s







If you build openfoam, then you modify something and run `./Allwmake` or `ninja`, it should recompile the things that need to be recompiled, no more and no less. If it does not recompile something that should be recompiled, the old version of the source code will be effective, leading to debugging headaches (this primed me to do this project). If it recompiles something that should not be recompiled, you need to wait longer than necessary. Meson/ninja is better at fulfilling both of these requirements than wmake:










Correct my if I'm mistaken, but here are my thoughts:

There are two possibilities:
1. You want to build OpenFOAM yourself, and add some user-modified binary/library.
2. You want to use the OpenFOAM installed by the package manager (or some other form of binary distribution), and add some user-modified binary/library.

In the first case, I would recommend you just edit it in-tree:
```
git clone https://develop.openfoam.com/Development/openfoam.git
cd openfoam
cd applications/solvers/lagrangian/reactingParcelFoam/
cp -r simpleReactingParcelFoam myParcelFoam
vim myParcelFoam/simpleReactingParcelFoam.C # edit what you want
cd ../../../../
meson setup build
ninja -C build
```

In the second case, I could make something like this work:
```
/path/to/openfoam/binary/installation/create_new_user_build_folder.sh foldername
cd foldername
cp -r /path/to/openfoam-source/applications/solvers/lagrangian/reactingParcelFoam/simpleReactingParcelFoam myParcelFoam
vim myParcelFoam/simpleReactingParcelFoam.C # edit what you want
meson setup build
ninja -C build
```
