# Meson-based alternative Build System

This project is intended to provide an alternative to building OpenFOAM with wmake. It is very much WiP.

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

- Building something that is outside of the main openfoam source tree ([wmake supports this](https://doc.cfd.direct/openfoam/user-guide-v10/compiling-applications#x10-830003.2.7))
- Building the ThirdParty folder
- Using these dependencies:
  - zoltan
  - mgrid
  - ccmio
  - kahip
  - scotch
- ninja install is not tested yet
- Generating Binary Packages for e.g. `apt-get install openfoam`
- Building Doxygen Documentation
- Windows Support
