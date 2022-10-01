# Meson-based alternative Build System

## How to build

```bash
cd /some/path
git clone https://github.com/Volker-Weissmann/meson
cd /some/other/path
git clone https://develop.openfoam.com/Development/openfoam
cd openfoam
/some/path/meson/meson.py setup builddir
cd builddir
ninja
```

Note that `source etc/bashrc` is not needed.

# What works and what does not work, what might work in the future

- It (currently) only supports Linux. Should not be much work to port, but my motivation to work on Windows is about zero.


```
cd openfoam
source etc/bashrc
meson/generate_meson_build.py
```
