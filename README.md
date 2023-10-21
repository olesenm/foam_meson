# Meson-based alternative Build System

This project is intended to provide an alternative to building OpenFOAM with wmake.

## Example Usage

```bash
git clone https://develop.openfoam.com/Development/openfoam
./generate_meson_build.py openfoam
cd openfoam
meson setup some_path
cd some_path
ninja
meson devenv # Launches a subshell
cd ../tutorials/basic/laplacianFoam/flange
./Allrun
```

Note that `source etc/bashrc` is not needed.

## Things that are not yet implemented

- Openfoam Version v2006 (June 2020) works, but in Openfoam Version v1912 (December 2019), `generate_meson_build.py` crashes.
- Building something that is outside of the main openfoam source tree ([wmake supports this](https://doc.cfd.direct/openfoam/user-guide-v10/compiling-applications#x10-830003.2.7))
- Building the ThirdParty folder
- Using these dependencies:
  - zoltan
  - mgrid
  - ccmio
  - kahip (blocked on https://github.com/KaHIP/KaHIP/pull/135 and https://github.com/mesonbuild/meson/pull/11932)
  - scotch
- ninja install is not tested yet
- Generating Binary Packages for e.g. `apt-get install openfoam`
- Building Doxygen Documentation
- Windows Support
