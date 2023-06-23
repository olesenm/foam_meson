def scanning_disabled():
    return ["applications/test/00-dummy/dummy", "src/OSspecific/MSwindows"]


def broken_dirs():
    return [
        "applications/test/rigidBodyDynamics/spring",
        "applications/test/coordinateSystem",
        "applications/test/labelRanges",
        "applications/test/boolList",
        "applications/test/matrices/EigenMatrix",
        "applications/test/parallel-nonBlocking",
        # Test-Random.C contains approx.:
        # #ifdef __linux__
        # #include <ieee754.h>
        # #endif
        # ieee754.h is part of the glibc. If a linux machine uses e.g. musl instead of glibc this will not compile.
        "applications/test/Random",
        # I don't know how to build this
        "applications/utilities/mesh/generation/foamyMesh/foamyHexMeshSurfaceSimplify",
    ]
