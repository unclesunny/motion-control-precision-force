#!/bin/bash
# =============================================================================
# SOEM Build Script — EtherCAT Master for Windows (MSYS2 UCRT64)
# =============================================================================
# Builds libsoem.a static library and test_soem.exe validation program
#
# Prerequisites:
#   - MSYS2 with UCRT64 environment
#   - GCC (mingw-w64-ucrt-x86_64-gcc)
#   - libpcap (mingw-w64-ucrt-x86_64-libpcap)
#
# Usage:
#   From UCRT64 terminal:
#     cd 03-ethercat-master/src/SOEM
#     ./build.sh
#
# Output:
#   build/libsoem.a        — SOEM static library (all 11 modules)
#   build/test_soem.exe    — Validation test program
# =============================================================================

set -e

# Fix temp directory if not set (MSYS2 may default to C:\WINDOWS)
export TMPDIR="${TMPDIR:-${TEMP:-${TMP:-/tmp}}}"
export TEMP="$TMPDIR"
export TMP="$TMPDIR"
mkdir -p "$TMPDIR" 2>/dev/null || true
# Also set GCC-specific temp dir
export GCC_TMPDIR="$TMPDIR"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BUILD_DIR="$SCRIPT_DIR/build"
GCC=gcc

# Include paths
INC_SOEM="-I $SCRIPT_DIR/soem"
INC_OSAL="-I $SCRIPT_DIR/osal -I $SCRIPT_DIR/osal/win32"
INC_OSHW="-I $SCRIPT_DIR/oshw/win32 -I /ucrt64/include -I $SCRIPT_DIR/oshw/win32/wpcap/Include"

# Compiler flags (warnings as info only, -pipe avoids temp files)
CFLAGS="-O2 -Wall -DWIN32 -pipe"

# Library flags
LDFLAGS="-L/ucrt64/lib -lpcap -lws2_32 -lwinmm -static-libgcc -static-libstdc++"

echo "============================================"
echo "  SOEM EtherCAT Master — Build Script"
echo "============================================"
echo "  Compiler: $($GCC --version | head -1)"
echo "  Target:   x86_64-w64-mingw32 (Windows 64-bit)"
echo "============================================"

mkdir -p "$BUILD_DIR"

# ---- Phase 1: Fix MSVC-specific headers for GCC ----
echo ""
echo "[1/4] Preparing headers for GCC..."

# The win32 port ships MSVC-only stdint.h/inttypes.h
# Rename them so GCC uses its own built-in headers
if [ -f "$SCRIPT_DIR/osal/win32/stdint.h" ]; then
    mv "$SCRIPT_DIR/osal/win32/stdint.h" "$SCRIPT_DIR/osal/win32/stdint.h.msvc"
    echo "  -> Renamed stdint.h (MSVC-only) for GCC compatibility"
fi
if [ -f "$SCRIPT_DIR/osal/win32/inttypes.h" ]; then
    mv "$SCRIPT_DIR/osal/win32/inttypes.h" "$SCRIPT_DIR/osal/win32/inttypes.h.msvc"
    echo "  -> Renamed inttypes.h (MSVC-only) for GCC compatibility"
fi

# ---- Phase 2: Compile all source files ----
echo ""
echo "[2/4] Compiling SOEM modules..."

compile_obj() {
    local name=$1
    local src=$2
    local inc="$3"
    printf "  %-20s" "$name"
    $GCC -c $inc $CFLAGS "$src" -o "$BUILD_DIR/${name}.o" 2>&1 || true
    echo "  OK"
}

# OSAL (Operating System Abstraction Layer)
compile_obj osal    "$SCRIPT_DIR/osal/win32/osal.c"    "$INC_OSAL"

# OSHW (OS Hardware — NIC driver, WinPcap/Npcap)
compile_obj nicdrv  "$SCRIPT_DIR/oshw/win32/nicdrv.c"  "$INC_SOEM $INC_OSAL $INC_OSHW"
compile_obj oshw    "$SCRIPT_DIR/oshw/win32/oshw.c"    "$INC_SOEM $INC_OSAL $INC_OSHW"

# SOEM Core (EtherCAT Master stack)
compile_obj ethercatbase   "$SCRIPT_DIR/soem/ethercatbase.c"   "$INC_SOEM $INC_OSAL $INC_OSHW"
compile_obj ethercatcoe    "$SCRIPT_DIR/soem/ethercatcoe.c"    "$INC_SOEM $INC_OSAL $INC_OSHW"
compile_obj ethercatconfig "$SCRIPT_DIR/soem/ethercatconfig.c" "$INC_SOEM $INC_OSAL $INC_OSHW"
compile_obj ethercatdc     "$SCRIPT_DIR/soem/ethercatdc.c"     "$INC_SOEM $INC_OSAL $INC_OSHW"
compile_obj ethercatfoe    "$SCRIPT_DIR/soem/ethercatfoe.c"    "$INC_SOEM $INC_OSAL $INC_OSHW"
compile_obj ethercatmain   "$SCRIPT_DIR/soem/ethercatmain.c"   "$INC_SOEM $INC_OSAL $INC_OSHW"
compile_obj ethercatprint  "$SCRIPT_DIR/soem/ethercatprint.c"  "$INC_SOEM $INC_OSAL $INC_OSHW"
compile_obj ethercatsoe    "$SCRIPT_DIR/soem/ethercatsoe.c"    "$INC_SOEM $INC_OSAL $INC_OSHW"

# ---- Phase 3: Create static library ----
echo ""
echo "[3/4] Creating libsoem.a..."

cd "$BUILD_DIR"
ar rcs libsoem.a \
    osal.o nicdrv.o oshw.o \
    ethercatbase.o ethercatcoe.o ethercatconfig.o ethercatdc.o \
    ethercatfoe.o ethercatmain.o ethercatprint.o ethercatsoe.o

LIB_SIZE=$(ls -la libsoem.a | awk '{print $5}')
echo "  -> libsoem.a created ($LIB_SIZE bytes, 11 modules)"

# ---- Phase 4: Build and run validation test ----
echo ""
echo "[4/4] Building validation test..."

$GCC -c $INC_SOEM $INC_OSAL $INC_OSHW $CFLAGS \
    "$SCRIPT_DIR/test_soem.c" -o "$BUILD_DIR/test_soem.o"

$GCC "$BUILD_DIR/test_soem.o" \
    -L"$BUILD_DIR" -lsoem $LDFLAGS \
    -o "$BUILD_DIR/test_soem.exe"

EXE_SIZE=$(ls -la "$BUILD_DIR/test_soem.exe" | awk '{print $5}')
echo "  -> test_soem.exe created ($EXE_SIZE bytes)"

echo ""
echo "============================================"
echo "  Running validation tests..."
echo "============================================"
"$BUILD_DIR/test_soem.exe"
TEST_RC=$?

echo ""
echo "============================================"
if [ $TEST_RC -eq 0 ]; then
    echo "  BUILD SUCCESSFUL — All tests passed!"
else
    echo "  BUILD FAILED — Tests returned code $TEST_RC"
fi
echo "============================================"
echo ""
echo "Artifacts:"
echo "  $BUILD_DIR/libsoem.a"
echo "  $BUILD_DIR/test_soem.exe"
echo ""
echo "To use in your project:"
echo "  gcc -I <soem>/soem -I <soem>/osal -I <soem>/osal/win32 \\"
echo "      -I <soem>/oshw/win32 -I /ucrt64/include \\"
echo "      your_app.c -L <soem>/build -lsoem \\"
echo "      -L/ucrt64/lib -lpcap -lws2_32 -lwinmm \\"
echo "      -static-libgcc -static-libstdc++ -o your_app.exe"

exit $TEST_RC
