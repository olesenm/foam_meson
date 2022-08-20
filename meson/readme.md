# Meson-based alternative Build System

## How to build

```bash
cd openfoam
meson/generate_lnInclude.py
source etc/bashrc
meson/generate_meson_build.py
meson setup builddir
meson compile -C builddir
```

Note that `source etc/bashrc` is only needed for `meson/generate_meson_build.py`, not for `meson setup builddir` or `meson compile -C builddir`.

- `meson compile -C builddir` needs to be executed if you change a `*.C` or `*.H` file.
- `rm -r builddir; meson setup builddir` needs to be executed if you change something about your OS.
- `meson/generate_meson_build.py` needs to be executed if you change `.../Make/options` or `.../Make/files`.
- `meson/generate_lnInclude.py` needs to be executed if you add a new `*.C` or `*.H` file.


# What works and what does not work

- It (currently) only supports Linux. Should not be much work to port, but my motivation to work on Windows is about zero.
