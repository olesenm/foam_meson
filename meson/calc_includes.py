#!/usr/bin/env python3

# todo: ignore .ccls-cache

from pathlib import Path
import pdb
import re
from meson_codegen import remove_prefix, remove_suffix
import pickle  # todo: remove pickle
import yaml

# src/lagrangian/
topdir = "."  # todo: change this to "." and maybe ignore gitignore

with open("meson/data.yaml", "r") as stream:
    yamldata = yaml.safe_load(stream)

# source_file_endings = ["hpp", "cpp", "hxx", "cxx", "H", "C", "h", "c"]
# fps = []
# for ending in source_file_endings:
#     for fp in Path(topdir).rglob("*." + ending):
#         if "lnInclude" in fp.parts:
#             continue
#         if str(fp) in [
#             # This 3 files are dead code. Todo: Submit PR
#             "src/conversion/vtk/adaptor/foamVtkVtuAdaptor.H",
#             "src/conversion/vtk/adaptor/foamVtkTools.H",
#             "src/conversion/vtk/adaptor/foamVtkToolsTemplates.C",
#             "src/conversion/vtk/adaptor/foamVtkVtuAdaptorTemplates.C",
#             "applications/solvers/combustion/PDRFoam/PDRFoamAutoRefine.C",
#         ]:
#             continue
#         if str(fp).startswith("etc/codeTemplates/"):
#             continue
#         flag = False
#         for el in yamldata["broken_dirs"]:
#             if str(fp).startswith(el + "/"):
#                 flag = True
#         for el in yamldata["ignored_dirs"]:
#             if str(fp).startswith(el + "/"):
#                 flag = True
#         if flag:
#             continue
#         fps.append(fp)
# pickle.dump(fps, open("temp.pickle", "wb"))
fps = pickle.load(open("temp.pickle", "rb"))

# https://stackoverflow.com/questions/241327/remove-c-and-c-comments-using-python
def comment_remover(text):
    def replacer(match):
        s = match.group(0)
        if s.startswith("/"):
            return " "  # note: a space and not an empty string
        else:
            return s

    pattern = re.compile(
        r'//.*?$|/\*.*?\*/|\'(?:\\.|[^\\\'])*\'|"(?:\\.|[^\\"])*"',
        re.DOTALL | re.MULTILINE,
    )
    return re.sub(pattern, replacer, text)


regex1 = re.compile(
    '^[ \t]*#include [ \t]*"[a-zA-Z0-9_/\-\.]+.([hHcC]|[hc]xx|[hc]pp)"[ \t]*$'
)
regex2 = re.compile(
    "^[ \t]*#include [ \t]*<[a-zA-Z0-9_/\-]+.([hHcC]|[hc]xx|[hc]pp)?>[ \t]*$"
)
for sourcefile in fps:
    content = open(sourcefile).read()
    content = comment_remover(content)
    for line in content.split("\n"):
        if "#include " in line:
            if line in [
                "    #include INCLUDE_FILE(CREATE_TIME)",
                "    #include INCLUDE_FILE(CREATE_MESH)",
                "    #include INCLUDE_FILE(CREATE_CONTROL)",
                "            #include INCLUDE_FILE(CREATE_FIELDS)",
                "            #include INCLUDE_FILE(CREATE_FIELDS_2)",
                "            #include INCLUDE_FILE(CREATE_FIELDS_3)",
                "#include CLOUD_INCLUDE_FILE(CLOUD_BASE_TYPE)",
                '    fprintf(out,"#include \\"%s\\"\\n", incName); lineno++;',
            ]:
                continue
            if regex2.match(line):
                continue
            if not regex1.match(line):
                raise NotImplemented
            line = line.strip()
            line = remove_prefix(line, "#include ")
            line = line.strip()
            line = remove_prefix(line, '"')
            line = remove_suffix(line, '"')
            if line.split("/")[0] in ["CGAL", "libccmio"]:
                continue
            if line in ["scotch_64.h", "bzlib.h", "zlib.h", "lzma.h"]:
                continue
            part = line
            while part.startswith("../"):
                part = part[3:]
            ar = [el for el in fps if str(el) == part or str(el).endswith("/" + part)]
            if len(ar) == 0:
                print("length 0:", line)
                # pdb.set_trace()
                pass
            elif len(ar) > 1:
                print(
                    "{} matches for {} included by {}".format(len(ar), line, sourcefile)
                )
    # exit(1)

print("finished")
