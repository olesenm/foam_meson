#!/usr/bin/env python3

# usuage:
# cd openfoam
# meson/generate_lnInclude.py
# source etc/bashrc
# meson/generate_meson_build.py
# meson setup builddir
# meson compile -C builddir

# TODO: Add guards against executing with the wrong pwd

# If USING_LNINCLUDE = False, then we run into this problem:
# c++: fatal error: cannot execute ‘/usr/lib/gcc/x86_64-pc-linux-gnu/10.2.0/cc1plus’: execv: Argument list too long
USING_LNINCLUDE = True
GROUP_FULL_DIRS = True

from os import path, listdir, walk
import os
import subprocess
import re
from meson_codegen import *
import sys
import textwrap
def from_this_directory():
	os.chdir(path.dirname(sys.argv[0]))
from_this_directory()
os.chdir("..")
assert os.environ["WM_PROJECT_DIR"] != "", "Did you forget sourcing etc/bashrc?"

# what if BOOST_INC_DIR or METIS_INC_DIR or KAHIP_INC_DIR or PTSCOTCH_INC_DIR or SCOTCH_INC_DIR or FFTW_INC_DIR is defined?

# do we actually never need OBJECTS_DIR

# The following should be tested often, because their -I and -l flags are easy to get wrong.
# ninja buoyantBoussinesqPimpleFoam.p/applications_solvers_heatTransfer_buoyantBoussinesqPimpleFoam_buoyantBoussinesqPimpleFoam.cpp.o
# ninja libfieldFunctionObjects.so.p/src_functionObjects_field_PecletNo_PecletNo.cpp.o
# ninja correctBoundaryConditions

# attempting to add a target with one of these names needs to fail immediately to avoid confusing with system libraries
target_blacklist = ["lib_boost_system", "lib_fftw3", "lib_mpi", "lib_z"]

def scan_path(dirpath, stage):
	if dirpath.split("/")[-1] == "codeTemplates":
		return

	for el in listdir(dirpath):
		tot = path.join(dirpath, el)
		if path.isdir(tot):
			scan_path(tot, stage)

	# todo: what about MGridGenGamgAgglomeration?
	# 00-dummy does not build, even with wmake
	if path.isdir(path.join(dirpath, "Make")) and not dirpath.split("/")[-1] in ["MGridGenGamgAgglomeration", "zoltanRenumber", "foamyHexMeshSurfaceSimplify", "MSwindows"]	and not dirpath in [
			"./applications/utilities/mesh/generation/foamyMesh/foamyQuadMesh",
			"./applications/utilities/mesh/generation/foamyMesh/foamyHexMesh",
			"./applications/utilities/mesh/generation/foamyMesh/cellSizeAndAlignmentGrid",
			"./src/functionObjects/randomProcesses/energySpectrum",
			"./src/parallel/decompose/scotchDecomp",
			"./src/parallel/decompose/ptscotchDecomp",
			"./src/parallel/decompose/metisDecomp",
			"./src/parallel/decompose/kahipDecomp",
			"./src/conversion/ccm",
			"./src/Pstream/mpi",
			"./applications/test/tensorFields1",
			"./applications/test/IOField",
			"./applications/test/scalarOps",
			"./applications/test/DynamicList",
			"./applications/test/field1",
			"./applications/test/rigidBodyDynamics/spring",
			"./applications/test/rigidBodyDynamics/reconstructedDistanceFunction",
			"./applications/test/reconstructedDistanceFunction",
			"./applications/utilities/mesh/generation/foamyMesh/foamyHexMeshBackgroundMesh",
			"./applications/test/surfaceMeshConvert",
	] and not "00-dummy" in dirpath and not dirpath.startswith("./applications/utilities/mesh/conversion/ccm"):
		wmake_to_meson(path.join(dirpath, "Make"), stage)

# https://gist.github.com/ChunMinChang/88bfa5842396c1fbbc5b
def commentRemover(text):
    def replacer(match):
        s = match.group(0)
        if s.startswith('/'):
            return " " # note: a space and not an empty string
        else:
            return s
    pattern = re.compile(
        r'//.*?$|/\*.*?\*/|\'(?:\\.|[^\\\'])*\'|"(?:\\.|[^\\"])*"',
        re.DOTALL | re.MULTILINE
    )
    return re.sub(pattern, replacer, text)

def hashtagCommentRemover(text):
	# ret = []
	# for line in text.split("\n"):
	# 	ret.append(line)
	pattern = re.compile(
        r'#.*\n',
	)
	return re.sub(pattern, "\n", text)

# print(hashtagCommentRemover(
# """
# test
# # abc # 321
# test
# """))
# exit(1)

def find_subdirs(dirpath, el, varname="incdirs", include_directories=False):
	assert el[-1] != "/"
	mesonsrc = ""
	fp = el
	if not path.exists(dirpath + "/../" + fp):
		print("warning, path does not exists")
		return ""
	includeDir = dirpath+"/../"+  ("/".join(el.split("/")[:-1]))
	#print(dirpath, el, includeDir, fp)
	if include_directories:
		mesonsrc += varname + " += include_directories('" + fp + "')\n"
	else:
		mesonsrc += varname + " += '" + fp + "'\n"
	return mesonsrc
	for entries in walk(includeDir, topdown=False):
		flag = False
		for fp in entries[2]:
			if fp.endswith(".hpp") or fp.endswith(".cpp") or fp.endswith(".C") or fp.endswith(".H"):
				flag = True
		if flag:
			dp = remove_prefix(entries[0], dirpath)
			if include_directories:
				mesonsrc += varname + " += include_directories('" + "/".join(dp.split("/")[2:]) + "')\n"
			else:
				mesonsrc += varname + " += '" + "/".join(dp.split("/")[2:]) + "'\n"
	return mesonsrc

def substitute(vardict, cur):
	while True:
		old = cur
		for el in vardict:
			cur = cur.replace(el, vardict[el])
		if cur == old:
			break
	return cur

ROOT_PATH = os.getcwd()
PROJECT_ROOT = Path(ROOT_PATH)

def are_all_files_included(srcfiles, dirname):
	reclist = set()
	for f in Path(dirname).glob('**/*.C'):
		if "lnInclude" in str(f): #hacky
			continue
		if str(f) not in srcfiles:
			return False, None
		reclist.add(str(f))
	return True, reclist

def group_full_dirs(srcfiles):
	recdirs = []
	totreclist = set()
	for el in srcfiles:
		if not el.endswith(".C"):
			continue
		contflag = False
		for rdir in recdirs:
			if el.startswith(rdir):
				contflag = True
		if contflag:
			continue
		dirn = os.path.dirname(el)
		flag, reclist = are_all_files_included(srcfiles, dirn)
		if flag:
			new_flag = True
			test_dirn = dirn
			while new_flag:
				test_dirn = os.path.dirname(test_dirn)
				new_flag, new_reclist = are_all_files_included(srcfiles, test_dirn)
				if new_flag:
					dirn = test_dirn
					reclist = new_reclist
		if flag:
			recdirs.append(dirn)
			totreclist.update(reclist)

	for dirn in recdirs:
		srcfiles.append("run_command(meson.source_root() + '/meson/rec_C.sh', '<PATH>" + dirn + "</PATH>').stdout().strip().split('\\n')")

	ret = []
	for el in srcfiles:
		if el not in totreclist:
			ret.append(el)
	return ret

lib_paths = {}
def wmake_to_meson(dirpath, stage):
	#print(dirpath)
	assert(dirpath.split("/")[-1] == "Make")
	thisdir = path.normpath(path.join(dirpath, ".."))
	statements, optionsdict, specials = parse_file(path.join(dirpath, "options"))
	template = ""
	incdirs = []
	if USING_LNINCLUDE:
		incdirs.append("'<PATH>" + str(PROJECT_ROOT / "src/OpenFOAM/lnInclude"  ) +"</PATH>'")
	else:
		incdirs.append("run_command(meson.source_root() + '/meson/rec_dirs.sh', '<PATH>" + str(PROJECT_ROOT / "src/OpenFOAM" ) +"</PATH>').stdout().strip().split('\\n')")
	incdirs.append("'<PATH>" + str(PROJECT_ROOT / thisdir) +"</PATH>'")
	inckey = None
	if "$(EXE_INC)" in optionsdict:
		inckey = "$(EXE_INC)"
	elif "$(LIB_INC)" in optionsdict:
		inckey = "$(LIB_INC)"

	if inckey is not None:
		for el in optionsdict[inckey].split(" "):
			el = el.lstrip()
			if el == "":
				continue
			if not el.startswith("-I"):
				continue
			if "$" in el:
				print(dirpath, "warning: unresolved variable in ", el)
				continue
			el = remove_prefix(el, "-I")
			if el.endswith("lnInclude"):
				recdir = os.path.normpath(str(PROJECT_ROOT / thisdir / el / ".."))
				if USING_LNINCLUDE:
					if path.exists(str(PROJECT_ROOT / thisdir / el)):
						incdirs.append("'<PATH>" + str(PROJECT_ROOT / thisdir / el) + "</PATH>'")
					else:
						print("warning in "+dirpath+"/options :", str(PROJECT_ROOT / thisdir / el), "does not exist")
				else:
					if path.exists(recdir):
						incdirs.append("run_command(meson.source_root() + '/meson/rec_dirs.sh', '<PATH>" + recdir + "</PATH>').stdout().strip().split('\\n')")
					else:
						print("warning in "+dirpath+"/options :", recdir, "does not exist")

			else:
				totpath = dirpath + "/../" + el
				if path.exists(totpath):
					incdirs.append("'<PATH>" + str(PROJECT_ROOT / thisdir / el) + "</PATH>'")
				else:
					print("warning in "+dirpath+"/options :", totpath, "does not exist")
	if USING_LNINCLUDE:
		if path.exists(dirpath + "/../" + "lnInclude"):
			incdirs.append("'<PATH>" + str(PROJECT_ROOT / thisdir / "lnInclude") + "</PATH>'")
	else:
		incdirs.append("run_command(meson.source_root() + '/meson/rec_dirs.sh', '<PATH>" + str(PROJECT_ROOT / thisdir) + "</PATH>').stdout().strip().split('\\n')")

	order_depends = []
	dependencies = []
	libkey = None
	if "$(EXE_LIBS)" in optionsdict:
		libkey = "$(EXE_LIBS)"
	elif "$(LIB_LIBS)" in optionsdict:
		libkey = "$(LIB_LIBS)"
	if libkey is not None and stage == 1:
		for el in optionsdict[libkey].split(" "):
			el = el.lstrip()
			if el == "":
				continue
			if "$" in el:
				print("warning: unresolved variable in ", el)
				continue
			if el.endswith("libOSspecific.o"):
				order_depends.append("lib_OSspecific")
				continue
			if el == "-pthread":
				dependencies.append("thread_dep")
				continue
			if el.startswith("-L"):
				continue
			if el.startswith("-Wl,") and el.endswith(path.sep + "openmpi"):
				# on my machine: el == "-Wl,/usr/lib/openmpi"
				continue
			if el in ["-Wl,-rpath", "-Wl,--enable-new-dtags"]:
				# I don't really know what these flags do, but I think we would notice it if it would be necessary.
				continue
			if not el.startswith("-l"):
				print("warning in ",dirpath,": not starting with -l: ", el)
				continue

			el = remove_prefix(el, "-l")
			if el == "boost_system":
				dependencies.append("boost_system_dep")
			elif el == "fftw3":
				dependencies.append("fftw3_dep")
			elif el == "mpi":
				dependencies.append("mpi_dep")
			elif el == "z":
				dependencies.append("z_dep")
			else:
				order_depends.append("lib_"+el)
	order_provides = None
	group_srcs = []
	srcfiles = []
	gen_sources = []
	try:
		template_end = ""
		vardict = {}
		#todo: set the CORRECT WM_LABEL_SIZE and WM_DP and OPENFOAM here
		preprocessed = subprocess.check_output("cpp -traditional-cpp -DOPENFOAM=2006 -DWM_DP -DWM_LABEL_SIZE=32 " + path.join(dirpath, "files"), shell=True).decode()
		preprocessed = hashtagCommentRemover(preprocessed)
		for line in preprocessed.split("\n"):
			if line.rstrip() == "":
				continue
			if line.startswith("EXE"):
				line = remove_prefix(line, "EXE")
				line = remove_prefix(line, "=")
				if line.startswith("$(FOAM_APPBIN)"):
					line = remove_prefix(line, "$(FOAM_APPBIN)/")
				elif line.startswith("$(FOAM_USER_APPBIN)"):
					line = remove_prefix(line, "$(FOAM_USER_APPBIN)/")
				else:
					line = remove_prefix(line, "$(PWD)/")
				line = line.rstrip()
				provides = ("exe_" + line).replace("-", "_")
				template_end += provides + " = executable('" + line + "', srcfiles, include_directories: incdirs, link_with: link_with, dependencies: dependencies, install: true)\n"
				assert order_provides is None
				order_provides = provides
			elif line.startswith("LIB"):
				line = remove_prefix(line, "LIB")
				line = remove_prefix(line, "=")
				if line.startswith("$(FOAM_LIBBIN)/"):
					line = remove_prefix(line, "$(FOAM_LIBBIN)/")
				elif line.startswith("$(FOAM_MPI_LIBBIN)/"):
					line = remove_prefix(line, "$(FOAM_MPI_LIBBIN)/")
				else:
					line = remove_prefix(line, "$(FOAM_USER_LIBBIN)/")
				line = line.rstrip()
				if line == "":
					continue
				line = "/".join(line.split("/")[:-1] + [remove_prefix(line.split("/")[-1], "lib")])
				if stage == 1:
					assert line not in lib_paths, line + "--------------" + dirpath + "--------" + repr(lib_paths)
				lib_paths[line] = dirpath
				line = line.split("/")[-1]
				provides = ("lib_" + line).replace("-", "_")
				template_end += provides + " = library('" + line + "', srcfiles, include_directories: incdirs, link_with: link_with, dependencies: dependencies, install: true)\n"
				assert order_provides is None
				order_provides = provides
			elif "=" in line:
				ar = line.split("=")
				assert len(ar) == 2 , line
				vardict["$("+ar[0].rstrip()+")"] = ar[1].lstrip().rstrip()
			elif " " not in line.rstrip():
				if line.endswith(".lyy-m4"):
					group_srcs.append(str(PROJECT_ROOT / thisdir/ line.rstrip()))
					line = substitute(vardict, line)
					name = line
					for c in "$", ".", "(", ")", "/", "_", "-":
						name = name.replace(c, "_")
					template += name + "_cpp = custom_target('" + name + "_cpp', input: '" + line + "', output : '" + remove_suffix(line.split("/")[-1], ".lyy-m4") + ".cc', \n command: [m4lemon, meson.source_root(), '<PATH>" + str(PROJECT_ROOT / thisdir)  + "</PATH>', lemonbin, '@INPUT@', '@OUTPUT@' ])\n"
					gen_sources.append(name + "_cpp")
				elif line.endswith(".L"):
					gen_sources.append("flexgen.process('<PATH>" + line.rstrip() + "</PATH>')")
					group_srcs.append(str(PROJECT_ROOT / thisdir/ line.rstrip()))
				elif line == "global/global.Cver":
					gen_sources.append("global_cpp")
				elif line.endswith(".hpp") or line.endswith(".H") or line.endswith(".cpp") or line.endswith(".C") or line.endswith(".cc") or line.endswith(".cxx"):
					srcfiles.append(os.path.normpath(str(PROJECT_ROOT / thisdir/ line.rstrip())))
					group_srcs.append(str(PROJECT_ROOT / thisdir/ line.rstrip()))
				else:
					raise ValueError(line)
			else:
				raise ValueError(line)
		assert template_end.count("\n") == 1

		for i in range(len(srcfiles)):
			srcfiles[i] = substitute(vardict, srcfiles[i])
		for i in range(len(gen_sources)):
			gen_sources[i] = substitute(vardict, gen_sources[i])
		for i in range(len(group_srcs)):
			group_srcs[i] = substitute(vardict, group_srcs[i])

		if GROUP_FULL_DIRS:
			srcfiles = group_full_dirs(srcfiles)

		if "executable" in template_end:
			order_depends.append('lib_OpenFOAM')
			dependencies += ["m_dep", "dl_dep"]

		for i in range(len(srcfiles)):
			if not srcfiles[i].startswith("run_command("):
				srcfiles[i] = "'<PATH>" + srcfiles[i] + "</PATH>'"

		if USING_LNINCLUDE:
			incdirs.append("'<PATH>"+ str(ROOT_PATH) + "/src/OSspecific/POSIX/lnInclude</PATH>'")
		else:
			incdirs.append("run_command(meson.source_root() + '/meson/rec_dirs.sh', '<PATH>" + str(ROOT_PATH) + "/src/OSspecific/POSIX</PATH>').stdout().strip().split('\\n')")

		if "CGAL" in specials:
			dependencies.append("cgal_dep")
			dependencies.append("mpfr_dep")
			dependencies.append("gmp_dep")

		addspace = "\n    " if len(incdirs) > 0 else ""
		template += "incdirs = include_directories(\n    " + ",\n    ".join(incdirs) + addspace + ")\n"
		addspace = "\n    " if len(gen_sources) > 0 else ""
		template += "srcfiles = [ files(\n    " + ",\n    ".join(srcfiles) + "),\n    " + ",\n    ".join(gen_sources) + addspace + "]\n"
		addspace = "\n    " if len(order_depends) > 0 else ""
		template += "link_with = [\n    " + ",\n    ".join(order_depends) + addspace + "]\n"
		addspace = "\n    " if len(dependencies) > 0 else ""
		template += "dependencies = [\n    " + ",\n    ".join(dependencies) + addspace + "]\n"

		template += template_end

		if "CGAL" in specials:
			template = textwrap.indent(template, "  ")
			template = "if cgal_dep.found() and mpfr_dep.found() and gmp_dep.found()\n" + template + "endif\n"
	except Exception as ex:
		print("unable to parse:", dirpath, repr(ex))
		raise ex

	#template = handle_special_cases(thisdir, template)
	template = Template(template)
	template.make_absolute(PROJECT_ROOT / thisdir)

	template.assert_absolute()
	template.cleanup()
	assert order_provides not in target_blacklist
	totdesc.add_template(order_provides, order_depends, template, largest_commons_prefix(group_srcs))

def parse_file(fp):
	with open(fp) as infile:
		lines = infile.read()
	specials = []
	lines = commentRemover(lines)
	if "include $(GENERAL_RULES)/CGAL" in lines:
		lines = lines.replace("include $(GENERAL_RULES)/CGAL", "")
		specials.append("CGAL")


	reldir = "/".join(fp.split("/")[:-2])
	vardict = { "$(LIB_SRC)": path.relpath("src", reldir),
    			"${LIB_SRC}": path.relpath("src", reldir),
				"$(FOAM_UTILITIES)": path.relpath("applications/utilities", reldir),
				"$(FOAM_SOLVERS)": path.relpath("applications/solvers", reldir),
				"POSIX_SRC_HACK": path.relpath("src/OSspecific/POSIX", reldir),
				"$(KAHIP_INC_DIR)": path.relpath("src/dummyThirdParty/kahipDecomp/lnInclude", reldir),
				#"$(OBJECTS_DIR)": path.relpath("build/linux64GccDPInt32Opt/src/OpenFOAM", reldir), #todo: we should not rely on build/...
			    #"$(FOAM_LIBBIN)": path.relpath("platforms/linux64GccDPInt32Opt/lib", reldir), #todo: we should not rely on platforms/...
			    "$(GENERAL_RULES)": "wmake/rules/General",
			   }
	with open("makefile", "w") as makeout:
		for key in vardict:
			makeout.write(key[2:-1]+"="+vardict[key]+"\n")
		makeout.write(lines)
		makeout.write("\nprint_stuff:\n\techo $(LIB_INC)\n\techo $(EXE_INC)\n\techo $(LIB_LIBS)\n\techo $(EXE_LIBS)\n")
	vars = subprocess.check_output("make -s print_stuff", shell=True).decode().split("\n")
	if vars[0] != "":
		vardict["$(LIB_INC)"] = vars[0]
	if vars[1] != "":
		vardict["$(EXE_INC)"] = vars[1]
	if vars[2] != "":
		vardict["$(LIB_LIBS)"] = vars[2]
	if vars[3] != "":
		vardict["$(EXE_LIBS)"] = vars[3]
	return [], vardict, specials

mainsrc = """
project('OpenFOAM', 'c', 'cpp',
  default_options : ['warning_level=0', 'b_lundef=false', 'b_asneeded=false'])

add_project_arguments('-DWM_LABEL_SIZE='+get_option('WM_LABEL_SIZE'), language : 'cpp')
add_project_arguments('-Wfatal-errors', language : 'cpp')
add_project_arguments('-DWM_DP', language : 'cpp')
add_project_arguments('-DNoRepository', language : 'cpp')
add_project_arguments('-DOPENFOAM=2006', language : 'cpp')
add_project_arguments('-DOMPI_SKIP_MPICXX', language : 'cpp')
add_project_arguments('-ftemplate-depth-100', language : 'cpp')
add_project_arguments('-m64', language : ['c', 'cpp'])
add_project_link_arguments('-Wl,--add-needed', language : 'cpp')
if get_option('debug')
  add_project_arguments('-DFULLDEBUG', language : ['c', 'cpp'])
  add_project_arguments('-fdefault-inline', language : ['c', 'cpp'])
  add_project_arguments('-finline-functions', language : 'c')
else
  add_project_arguments('-frounding-math', language : 'cpp')
endif

global_cpp = custom_target('global.cpp',
  output : 'global.cpp',
  input : 'src/OpenFOAM/global/global.Cver',
  command : [meson.source_root() / 'meson' / 'set_versions_in_global_Cver.sh', meson.source_root(), '@OUTPUT@'])
  #todo: what if src/bashrc is the wrong script to source?

cppc = meson.get_compiler('cpp')
m_dep = cppc.find_library('m')
dl_dep = cppc.find_library('dl')
z_dep = cppc.find_library('z')

cgal_dep = cppc.find_library('CGAL', required: false)
mpfr_dep = cppc.find_library('mpfr', required: false)
gmp_dep = cppc.find_library('gmp', required: false)

boost_system_dep = dependency('boost', modules : ['system'])
fftw3_dep = dependency('fftw3')
mpi_dep = dependency('mpi')
thread_dep = dependency('threads')

if not cgal_dep.found()
  # applications/utilities/surface/surfaceBooleanFeatures is the only directory that needs this flag, but a global argument seems nicer
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
"""

totdesc = BuildDesc(PROJECT_ROOT)
scan_path(".", 1)
# import pickle
# with open("outtemp", "wb") as pfile:
# 	pickle.dump(totdesc, pfile)

#totdesc = pickle.load(open("outtemp", "rb"))

totdesc.set_custom_prefix(PROJECT_ROOT / "meson.build", mainsrc)

# Without these fixes, grouping cannot be done

totdesc.elements["lib_lagrangianTurbulence"].ideal = Path("src").parts
totdesc.elements["lib_lagrangianIntermediate"].ideal = Path("src").parts
totdesc.elements["lib_lagrangianSpray"].ideal = Path("src").parts
totdesc.elements["lib_coalCombustion"].ideal = Path("src").parts
totdesc.elements["lib_turbulenceModels"].ideal = Path("src").parts
totdesc.elements["lib_snappyHexMesh"].ideal = Path("src").parts
totdesc.elements["lib_compressibleTurbulenceModels"].ideal = Path("src").parts
totdesc.elements["lib_turbulenceModelSchemes"].ideal = Path("src").parts
totdesc.elements["lib_radiationModels"].ideal = Path("src").parts
totdesc.elements["lib_compressibleTurbulenceModels"].ideal = Path("src").parts
totdesc.elements["lib_liquidPropertiesFvPatchFields"].ideal = Path("src").parts
totdesc.elements["lib_geometricVoF"].ideal = Path("src").parts

generated_files = totdesc.writeToFileSystem()

lib_dirlist = set()
for fp,targets in generated_files.items():
	if any(e.startswith("lib_") for e in targets):
		lib_dirlist.add(os.path.relpath(fp, ROOT_PATH))
dirlist = set([str(Path(*fp.parts[:-1])) for fp in generated_files])

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
# Check if we are on windows in src/OSspecific/meson.buil
# 
# Make a meson branch