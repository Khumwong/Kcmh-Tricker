#!/usr/bin/env bash
# Compile remote_scripts/StdEventMonitor_faster.cpp -> StdEventMonitor_faster
#
# Runs ON THE SERVER. run_with_stats.py calls this automatically when the binary
# is missing or older than the source; run it by hand to see compiler errors.
#
# Needs a C++17 compiler, ROOT and an EUDAQ2 build/install.
# Env overrides:
#   EUDAQ_PREFIX       root of the eudaq2 tree           (default: /home/sutpct/eudaq2)
#   EUDAQ_INC          dir containing  eudaq/Event.hh     (default: auto-probe)
#   EUDAQ_LIB          dir containing  libeudaq_core.so   (default: auto-probe)
#   ROOT_CONFIG        path to root-config to build with  (default: the ROOT that
#                      EUDAQ core is linked to, else root-config on PATH)
#   CXX               compiler                            (default: g++)
#   MONITOR_BUILD_CMD  full compile command, run verbatim in remote_scripts/
#                      (skips every probe below — use when auto-detect fails)
#
# Args: --force  rebuild even if the binary looks up to date
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
src="$here/StdEventMonitor_faster.cpp"
bin="$here/StdEventMonitor_faster"

[ -f "$src" ] || { echo "build: missing source $src" >&2; exit 2; }

if [ "${1:-}" != "--force" ] && [ -x "$bin" ] && [ "$bin" -nt "$src" ]; then
    echo "build: $bin already up to date"
    exit 0
fi

if [ -n "${MONITOR_BUILD_CMD:-}" ]; then
    echo "build: using MONITOR_BUILD_CMD"
    ( set -x; cd "$here"; eval "$MONITOR_BUILD_CMD" )
    exit $?
fi

prefix="${EUDAQ_PREFIX:-/home/sutpct/eudaq2}"

inc="${EUDAQ_INC:-}"
if [ -z "$inc" ]; then
    for d in "$prefix/include" "$prefix/main/lib/core/include" "$prefix"/*/include; do
        if [ -f "$d/eudaq/Event.hh" ]; then inc="$d"; break; fi
    done
fi
if [ -z "$inc" ]; then
    hit="$(find "$prefix" -type f -path '*/eudaq/Event.hh' -print 2>/dev/null | head -n1 || true)"
    [ -n "$hit" ] && inc="${hit%/eudaq/Event.hh}"
fi
[ -n "$inc" ] && [ -f "$inc/eudaq/Event.hh" ] || {
    echo "build: cannot locate eudaq/Event.hh under $prefix — set EUDAQ_INC" >&2; exit 4; }

# EUDAQ core lib: v2 ships libeudaq_core.so, some installs libEUDAQ.so / libeudaq.so
# (match real shared objects only, not libeudaq_core.rootmap / .pcm)
find_core() {  # $1 = dir
    find "$1" -maxdepth 1 \( -name 'libeudaq_core.so' -o -name 'libeudaq_core.so.*' \
        -o -name 'libeudaq_core.dylib' -o -name 'libEUDAQ.so' -o -name 'libEUDAQ.so.*' \
        -o -name 'libEUDAQ.dylib' -o -name 'libeudaq.so' -o -name 'libeudaq.so.*' \
        -o -name 'libeudaq.dylib' \) -print 2>/dev/null | head -n1
}
lib="${EUDAQ_LIB:-}"
core=""
if [ -n "$lib" ]; then
    core="$(find_core "$lib" || true)"
else
    for d in "$prefix/lib" "$prefix/lib64" "$prefix/bin" "$prefix/build/lib"; do
        core="$(find_core "$d" || true)"
        [ -n "$core" ] && { lib="$d"; break; }
    done
    if [ -z "$core" ]; then
        core="$(find "$prefix" -maxdepth 5 \( -name 'libeudaq_core.so*' \
            -o -name 'libEUDAQ.so*' -o -name 'libeudaq.so*' \) -print 2>/dev/null | head -n1 || true)"
        [ -n "$core" ] && lib="$(dirname "$core")"
    fi
fi
[ -n "$core" ] || {
    echo "build: cannot locate the EUDAQ core lib (libeudaq_core.so / libEUDAQ.so) under $prefix" >&2
    echo "       set EUDAQ_LIB to the dir that holds it" >&2; exit 5; }

# derive the -l name:  libeudaq_core.so.2.6.7 -> eudaq_core
lname="$(basename "$core")"; lname="${lname#lib}"; lname="${lname%%.so*}"; lname="${lname%%.dylib*}"

# Pick root-config. CRITICAL: if this host has more than one ROOT, build against
# the SAME one EUDAQ core is linked to — otherwise two libCore load into the
# process and their static teardown corrupts the heap.
RC="${ROOT_CONFIG:-}"
if [ -z "$RC" ]; then
    ecore="$(ldd "$core" 2>/dev/null | awk 'tolower($0) ~ /libcore/ {print $3; exit}')"
    if [ -n "$ecore" ] && [ -e "$ecore" ]; then
        erp="$(cd "$(dirname "$ecore")/.." 2>/dev/null && pwd || true)"
        [ -n "$erp" ] && [ -x "$erp/bin/root-config" ] && RC="$erp/bin/root-config"
    fi
fi
[ -z "$RC" ] && command -v root-config >/dev/null 2>&1 && RC="root-config"
[ -n "$RC" ] || { echo "build: no root-config found — set ROOT_CONFIG" >&2; exit 3; }

root_libdir="$("$RC" --libdir)"
echo "build: ROOT      $("$RC" --version)  ($root_libdir)  [$RC]"
[ -n "${ecore:-}" ] && echo "build: EUDAQ core -> $ecore"
echo "build: EUDAQ inc $inc"
echo "build: EUDAQ lib $lib  (-l$lname)"
echo "build: CXX       ${CXX:-g++}"

# drop libs we don't use whose stale PCMs spam warnings on some ROOT installs
root_cflags="$("$RC" --cflags)"
root_libs="$("$RC" --libs | sed -E 's/-l(ROOTDataFrame|ROOTNTuple|ROOTNTupleUtil|TreePlayer|MultiProc|ROOTVecOps)( |$)/ /g')"

compile() {  # $1 = extra link flags
    ( set -x
      ${CXX:-g++} -std=c++17 -O2 -g -w -o "$bin.tmp" "$src" \
        -I"$inc" $root_cflags \
        -L"$lib" "-l$lname" $root_libs \
        -Wl,-rpath,"$lib" -Wl,-rpath,"$root_libdir" \
        -lpthread $1 )
}

# GCC < 9 needs -lstdc++fs for <filesystem>; newer toolchains have it built in.
if compile ""; then
    :
elif compile "-lstdc++fs"; then
    :
else
    echo "build: compilation failed" >&2
    rm -f "$bin.tmp"
    exit 6
fi

mv "$bin.tmp" "$bin"
echo "build: wrote $bin"
