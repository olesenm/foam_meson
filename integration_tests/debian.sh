#!/usr/bin/env xonsh
# Note that this script is written by someone with very little experience with docker

$RAISE_SUBPROC_ERROR = True

systemctl start docker
# docker stop foam
# docker rm foam

#docker container run --name foam_debian -di debian
docker start foam_debian

docker cp for_openfoam_commit_hash_0031cb1efa.diff foam_debian:/root

script="""
set -euo pipefail
IFS=$'\n\t'

cd root
#apt update
#apt install -y git g++ zlib1g-dev libfftw3-dev mpi-default-dev libboost-system-dev flex python3 ninja-build
#rm -r openfoam || true
git clone https://github.com/mesonbuild/meson || true
cd meson
git checkout 0.59.0
cd ..
#git clone https://develop.openfoam.com/Development/openfoam.git --depth=1
cd openfoam
rev=$(git rev-parse --verify HEAD)
rev=${rev:0:10}
git apply ../for_openfoam_commit_hash_$rev.diff
#../meson/meson.py setup ../build
cd ../build
ninja

"""

docker exec -it foam_debian bash -c @(script)
