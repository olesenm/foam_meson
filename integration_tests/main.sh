#!/usr/bin/env xonsh
# Note that this script is written by someone with very little experience with docker

$RAISE_SUBPROC_ERROR = True

systemctl start docker
# docker stop foam
# docker rm foam

# docker container run --name foam -di alpine

docker cp patch_for_8993af73ac.diff foam:/root

script="""
set -euo pipefail
IFS=$'\n\t'

cd root

echo "https://dl-cdn.alpinelinux.org/alpine/edge/testing" >> /etc/apk/repositories
apk add git meson bash g++ zlib-dev fftw-dev openmpi-dev boost-dev flex-dev cgal-dev
rm -r openfoam || true
git clone https://develop.openfoam.com/Development/openfoam.git --depth=1
cd openfoam
rev=$(git rev-parse --verify HEAD)
rev=${rev:0:10}
git apply ../patch_for_$rev.diff
meson setup ../build
cd ../build
ninja

"""

docker exec -it foam sh -c @(script)

#docker rm @(container[:12])
