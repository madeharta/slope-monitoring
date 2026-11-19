#!/bin/bash
set -euo pipefail
umask 077

export LC_ALL=C
export TZ=UTC

echo "=== EFFECTIVE TOOLCHAIN ==="

test "$(uname -m)" = "x86_64"

gcc --version
gfortran --version
make --version
ld --version

gcc -dumpfullversion > /output/gcc-version.txt
gcc -dumpmachine > /output/compiler-target.txt

test "$(cat /output/gcc-version.txt)" = "13.5.0"

cat /etc/os-release > /output/os-release.txt

dpkg-query -W \
    > /output/builder-packages.tsv

echo "TOOLCHAIN_VERIFICATION=PASS"

mkdir /work/source

tar --no-same-owner \
    -xf /input/explorer-source.tar \
    -C /work/source

cd /work/source

cp src/rtklib.h /output/rtklib.h

echo "=== BUILD CONFIGURATION ==="

for APP in convbin rnx2rtkp
do

    DIR="/work/source/app/consapp/$APP/gcc"

    test -f "$DIR/makefile"

    cp "$DIR/makefile" \
        "/output/$APP.makefile"

    make -C "$DIR" \
        -B -n CC=gcc \
        > "/output/$APP.build-plan.txt"

    echo "=== BUILD $APP ==="

    make -C "$DIR" \
        -j2 CC=gcc \
        2>&1 | tee "/output/$APP.build.log"

    test -s "$DIR/$APP"
    test -x "$DIR/$APP"

    install -m 0755 \
        "$DIR/$APP" \
        "/output/$APP"

    readelf -h "/output/$APP" \
        > "/output/$APP.elf-header.txt"

    readelf -d "/output/$APP" \
        > "/output/$APP.dynamic.txt"

    ldd "/output/$APP" \
        > "/output/$APP.dependencies.txt"

    if grep -q 'not found' \
        "/output/$APP.dependencies.txt"
    then
        echo "UNRESOLVED_DEPENDENCY=$APP"
        exit 1
    fi

    echo "BINARY_BUILD_PASS=$APP"

done

echo "=== LICENSE PRESERVATION ==="

cp /work/source/license.txt \
    /output/RTKLIB-LICENSE.txt

echo "=== CLI VERSION PROBE ==="

/output/convbin --version \
    > /output/convbin-version.txt 2>&1

cat /output/convbin-version.txt

echo "=== CLI HELP PROBES ==="

set +e

/output/convbin -h \
    > /output/convbin-help.txt 2>&1

echo "$?" > /output/convbin-help.exitcode

/output/rnx2rtkp -h \
    > /output/rnx2rtkp-help.txt 2>&1

echo "$?" > /output/rnx2rtkp-help.exitcode

set -e

echo "=== BINARY CHECKSUMS ==="

(
    cd /output

    sha256sum convbin rnx2rtkp \
        > BINARY-SHA256SUMS

    sha256sum -c BINARY-SHA256SUMS
)

echo "ISOLATED_BINARY_BUILD=PASS"
