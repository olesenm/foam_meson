#!/usr/bin/env python
# Note that this script is written by someone with very little experience with containers

# todo do not hardcode 988ec18ecc
# todo: check if the patch is not too large. Sometimes I accidentally include other stuff in the patch

# sudo ./test.sh | tee test.log ; notifyShutdown.py

import os
import json
import textwrap
import subprocess
import shutil
import sys
import argparse
from pathlib import Path
import pidfile


def sane_getout(cmd, cwd=None):
    res = subprocess.run(cmd, check=True, capture_output=True, cwd=cwd)
    print(res.stderr.decode())
    return res.stdout.decode()


def sane_call(cmd, cwd=None):
    sys.stdout.flush()
    sys.stderr.flush()
    subprocess.run(cmd, check=True, cwd=cwd)
    sys.stdout.flush()
    sys.stderr.flush()


def install_deps(distro):
    # todo: install some optional dependencies and try again
    if distro in ["debian", "ubuntu"]:
        return """
        apt update
        apt install -y git clang zlib1g-dev libfftw3-dev mpi-default-dev libboost-system-dev flex python3 ninja-build wget make
        git clone https://github.com/mesonbuild/meson
        cd meson
        git checkout 0.59.0
        cd ..
        """
    elif distro == "opensuse/leap":
        return """
        zypper install --no-confirm meson git gcc-c++ wget zlib-devel fftw3-devel libboost_system1_75_0-devel openmpi-devel flex make
        mpi-selector --set openmpi

        """
    else:
        raise NotImplementedError


def prepare(distro):
    if distro in ["debian", "ubuntu"]:
        return 'source "$HOME/.cargo/env"'
    elif distro == "opensuse/leap":
        return """
                set +u
                source /etc/profile.d/mpi-selector.sh
                set -u
        """
    else:
        raise NotImplementedError


def meson_cmd(distro):
    if distro in ["debian", "ubuntu"]:
        return "../meson/meson.py"
    elif distro == "opensuse/leap":
        return "meson"
    else:
        raise NotImplementedError


def total(distro):
    script = rf"""
    set -euo pipefail
    IFS=$'\n\t'
    {prepare(distro)}
    cd /root/build
    ninja
    {meson_cmd(distro)} devenv bash -c "cd ../openfoam/tutorials/basic/laplacianFoam/flange && ./Allrun"

    expected_output=$(cat << EOF
    --> FOAM FATAL ERROR :
        Could not find mandatory etc entry (mode=ugo)
        'controlDict'
    EOF
    )
    # This find command finds all binaries except for ./lemon and ./meson-private/...
    for el in $(find . \( -name "meson-private" -prune -o -type f -executable ! -name "*.so" \) -not \( -name meson-private -o -name lemon \) ); do
        actual_output=$($el 2>&1 || true)
        # If the binary fails to find/load one of its shared libraries or some symbol is missing, $actual_output is not $expected_output
        if [ "$expected_output" != "$actual_output" ]; then
            echo -e "The binary\n" $el "\nhas a bad output:\n" "$actual_output"
            exit 1
        fi
    done

    echo "test finished"
    cd ..
    rm -r build
    """
    return textwrap.dedent(script)


def container_name(distro):
    return "foam_qa_" + distro.replace("/", "_")


def print_git_status(path):
    print(f"------BEGIN GIT STATUS OF {Path.cwd() / path} -----------")
    sane_call(["git", "rev-parse", "--verify", "HEAD"], cwd=path)
    sane_call(["git", "status"], cwd=path)
    print("--------END GIT STATUS----------------------")


def run_in_container(distro, log_suffix, script):
    with open(
        f"{container_name(distro)}_{log_suffix}.log", "w", encoding="utf-8"
    ) as ofile:
        subprocess.run(
            [
                "podman",
                "exec",
                container_name(distro),
                "bash",
                "-c",
                script,
            ],
            stdout=ofile,
            stderr=ofile,
            check=True,
        )


def main():
    all_distros = ["debian", "opensuse/leap", "ubuntu"]
    distro_foam_pairs = [
        ("debian", "develop"),
        ("opensuse/leap", "maintenance-v2212"),
        ("ubuntu", "maintenance-v2006"),
    ]

    if os.geteuid() != 0:
        print("This script must be run as root.")
        sys.exit(1)

    parser = argparse.ArgumentParser()
    parser.add_argument("--inner-call", action="store_true")
    parser.add_argument("--use-uncommitted", action="store_true")
    args = parser.parse_args()

    with pidfile.PIDFile(f"/root/test_foam_meson_{args.inner_call}.pid"):
        wd = Path("/root/test_foam_meson_wd/")

        if not args.inner_call:
            if wd.exists():
                shutil.rmtree(wd)
            wd.mkdir()
            if args.use_uncommitted:
                shutil.copytree("/home/volker/Documents/foam_meson", wd / "foam_meson")
            else:
                sane_call(
                    [
                        "git",
                        "clone",
                        "/home/volker/Documents/foam_meson",
                        wd / "foam_meson",
                    ]
                )
                sane_call(["git", "checkout", "develop"], cwd=wd / "foam_meson")
                sane_call(["git", "remote", "remove", "origin"], cwd=wd / "foam_meson")
            with open(wd / "testpipeline.log", "w", encoding="utf-8") as lfile:
                lfile.write(f"Args: {sys.argv}\n")
                lfile.flush()
                subprocess.run(
                    [wd / "foam_meson/src/testpipeline.py", "--inner-call"],
                    stdout=lfile,
                    stderr=lfile,
                    check=True,
                )
            sys.exit(0)

        print(sys.argv)
        os.chdir(wd)
        print_git_status("foam_meson")

        containers = sane_getout(["podman", "ps", "-a", "--format", "{{json .}}"])
        for container in containers.split("\n"):
            if container.strip() == "":
                continue
            container = json.loads(container)
            for name in container["Names"]:
                if name.startswith("foam_qa"):
                    sane_call(["podman", "rm", name])

        for distro in all_distros:
            print(distro)
            sane_call(
                ["podman", "run", "--name", container_name(distro), "-di", distro]
            )
            sane_call(
                [
                    "podman",
                    "cp",
                    wd / "foam_meson",
                    f"{container_name(distro)}:/root/foam_meson",
                ]
            )
            run_in_container(
                distro,
                "install_deps",
                textwrap.dedent(
                    rf"""
            set -euo pipefail
            IFS=$'\n\t'
            cd /root
            {install_deps(distro)}
            cd /root/foam_meson
            git rev-parse --verify HEAD
            git status
            """
                ),
            )

        for build_distro, foam_hash_branch_tag in distro_foam_pairs:
            sane_call(
                ["git", "checkout", foam_hash_branch_tag],
                cwd="/root/openfoam",
            )
            print_git_status("/root/openfoam")

            patches = {}
            for distro in all_distros:
                print(distro)
                sane_call(
                    [
                        "podman",
                        "exec",
                        container_name(distro),
                        "bash",
                        "-c",
                        "rm -rf /root/openfoam || true",
                    ]
                )
                sane_call(
                    [
                        "podman",
                        "cp",
                        "/root/openfoam",
                        f"{container_name(distro)}:/root/openfoam",
                    ]
                )
                run_in_container(
                    distro,
                    f"gen_patch_{foam_hash_branch_tag}",
                    textwrap.dedent(
                        rf"""
                set -euo pipefail
                IFS=$'\n\t'
                cd /root/openfoam
                git rev-parse --verify HEAD
                git status
                {prepare(distro)}
                ../foam_meson/generate_meson_build.py .
                git add -A
                {meson_cmd(distro)} setup ../build
                """
                    ),
                )
                thispatch = sane_getout(
                    [
                        "podman",
                        "exec",
                        container_name(distro),
                        "bash",
                        "-c",
                        "cd /root/openfoam && git diff --staged",
                    ]
                )
                for v in patches.values():
                    assert thispatch == v
                patches[distro] = thispatch

            for distro in [build_distro]:
                script = total(distro)
                run_in_container(
                    distro,
                    f"build_{foam_hash_branch_tag}",
                    script,
                )
        for distro in all_distros:
            sane_call(["podman", "stop", container_name(distro)])

        print("All Test Finished")
        if not args.use_uncommitted:
            sane_call(
                [
                    "git",
                    "remote",
                    "add",
                    "codeberg",
                    "git@codeberg.org:Volker_Weissmann/foam_meson.git",
                ],
                cwd=wd / "foam_meson",
            )
            sane_call(["git", "pull", "codeberg", "trunk"], cwd=wd / "foam_meson")
            sane_call(["git", "checkout", "trunk"], cwd=wd / "foam_meson")
            sane_call(["git", "merge", "develop"], cwd=wd / "foam_meson")
            sane_call(["git", "push"], cwd=wd / "foam_meson")


if __name__ == "__main__":
    main()
