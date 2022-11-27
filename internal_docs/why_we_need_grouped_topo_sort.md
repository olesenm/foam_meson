# The reason we need grouped_topo_sort

Suppose you want a shared library and a binary that depends on it. You might write a shell-script:
```sh
gcc foo.c -shared -o libfoo.so
gcc main.c libfoo.so
```
This will work, but if you swap the order of the commands this will obviously not work.
If instead of writing a shell-script, you write a `build.ninja` file, you may specify those two targets in any order you like. You tell ninja which targets depend on which targets and ninja will figure out the correct order to build the targets. Any working order is called "topological order" and figuring it out is called topological sorting. Topological sorting is possible exactly if there is no cycle in the dependency graph.

If there are cycles in the dependency graph, the software is unbuildable anyway, no matter what ninja, meson or any build system does. So we can assume that there are never cycles in the dependency graph.

Unlike ninja, meson does not give you the freedom two specify the targets in any order you want. This will work:
```meson
lib_foo = library('foo', 'foo.c')
main = executable('main', 'main.c', link_with: [lib_foo])
```
But this will fail to build:
```meson
main = executable('main', 'main.c', link_with: [lib_foo])
lib_foo = library('foo', 'foo.c')
```
Since my project code-generates meson.build files, we need to write them down in topological order.
This in itself would be easy, as e.g. [the graphlib library](https://docs.python.org/3/library/graphlib.html#graphlib.TopologicalSorter) can do topological sorting and is fast enough that we do not have to think about performance.
Unfortunately there is an additional complication if we want pretty-looking `meson.build` files:
Meson allows you to split your configuration across multiple `meson.build` files using the `subdir` command.
For example this:
```
$ cat root/meson.build
lineA
subdir('somedir')
lineC
subdir('otherdir')
line G
$ cat root/somedir/meson.build
lineB
$ cat root/otherdir/meson.build
lineD
subdir('nested')
lineF
$ cat root/otherdir/nested/meson.build
lineE
```
does the same as this
```
$ cat root/meson.build
lineA
lineB
lineC
lineD
lineE
lineF
lineG
```
Now, let's say we have two directories called `foo` and `bar`, and three targets called `a`, `b` and `c` with this dependency graph:
```
c depends on b
b depends on a
```
This graph contains no cycles and the only topological order is: `a`, `b`, `c`.

It is crucial for you to understand the following: It is e.g. impossible to put both `a` and `c` into `foo` and `b` into `bar`, but it is possible to put `a` and `b` into `foo` and `c` into `bar`.

Generally, some target-directory maps are impossible to build. I call a target-directory mapping that is possible to build "grouped-toposortable". Note that here, "directory" refers to the directory of the `meson.build` file that contains the target, not the directory that contains the source files or the generated ".so"-files.

`generate_meson_build.py` first chooses a so-called `ideal_path` for every target. This is the subdirectory we would like the target to go into, because we want the `meson.build` files to look pretty. It is possible that this target-directory mapping is not "grouped-toposortable".
Then we pass this ideal target-directory mapping alongside the dependency graph to a rust binary called `grouped_topo_sort`. This binary will return a list of changes to the target-directory mapping that will make this mapping grouped-toposortable. It will attempt to make as few changes as possible. Note that because this is a tricky problem and I'm not good at graph theory the previous sentence contains the word "attempt. It might be possible to make the mapping grouped-toposortable with fewer changes than the binary outputs. Also note that while the binary currently takes about a second to run, this might increase drastically in the future if the dependency graph or the ideal target-directory mapping changes. (The binary contains an algorithm with a time complexity worse than O(n!). Currently n=8 or n=0 depending on the Openfoam version.)
