# Meson-based alternative Build System

## How to build

```bash
meson setup builddir #todo volkers meson fork is needed
meson compile -C builddir
```

Note that `source etc/bashrc` is not needed.

# What works and what does not work, what might work in the future

- It (currently) only supports Linux. Should not be much work to port, but my motivation to work on Windows is about zero.


```
cd openfoam
source etc/bashrc
meson/generate_meson_build.py
```
