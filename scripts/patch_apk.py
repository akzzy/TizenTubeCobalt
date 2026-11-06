#!/usr/bin/env python3
"""
TizenTube Cobalt APK Patcher
----------------------------
This utility patches an existing TizenTube Cobalt release APK (e.g. v2.0.3)
to redirect the userscript loader to a custom endpoint (such as a Cloudflare Worker),
without requiring a full 10-hour Chromium compilation from scratch.

Note:
If using a custom domain on Cloudflare (e.g. http(s)://t.yourdomain.com),
ensure the hostname is <= 16 characters so it fits within the native Blink
CSP whitelist string table without relocating ELF symbols.
For longer hostnames (like *.workers.dev), build using the GitHub Actions workflow (.github/workflows/build_apk.yaml).
"""

import os
import sys
import zipfile
import shutil
import tempfile
import urllib.request
import subprocess

OFFICIAL_RELEASE_URLS = {
    "arm64": "https://github.com/reisxd/TizenTubeCobalt/releases/download/v2.0.3/cobalt-arm64.apk",
    "arm": "https://github.com/reisxd/TizenTubeCobalt/releases/download/v2.0.3/cobalt-arm.apk",
}

OLD_LOAD_URL = b"https://cdn.jsdelivr.net/npm/@foxreis/tizentube/dist/userScript.js?v="
OLD_CHECK_URL = b"https://cdn.jsdelivr.net/npm/@foxreis/tizentube/dist/userScript.js"
OLD_CSP_HOST = b"cdn.jsdelivr.net\x00"

def patch_apk(input_apk_path, output_apk_path, new_worker_url, new_host=None):
    if not os.path.isfile(input_apk_path):
        print(f"Error: Input APK not found at {input_apk_path}")
        return False

    temp_dir = tempfile.mkdtemp(prefix="tt_patch_")
    try:
        print(f"Extracting {input_apk_path}...")
        with zipfile.ZipFile(input_apk_path, 'r') as zin:
            zin.extractall(temp_dir)

        # Find libchrobalt.so in extracted directory
        lib_found = False
        for root, _, files in os.walk(temp_dir):
            for file in files:
                if file == "libchrobalt.so":
                    lib_path = os.path.join(root, file)
                    lib_found = True
                    print(f"Patching {lib_path}...")
                    with open(lib_path, "rb") as f:
                        data = bytearray(f.read())

                    # 1. Patch loader URL
                    pos_load = data.find(OLD_LOAD_URL)
                    if pos_load != -1:
                        # Pad replacement URL with &x=... to keep identical length
                        target_len = len(OLD_LOAD_URL)
                        prefix = new_worker_url.encode('utf-8')
                        if not prefix.endswith(b'?v='):
                            if b'?' in prefix:
                                prefix += b'&v='
                            else:
                                prefix += b'?v='

                        if len(prefix) <= target_len:
                            # Pad query param
                            pad_len = target_len - len(prefix)
                            if pad_len > 0:
                                # Insert dummy param before v=
                                base, v = prefix.rsplit(b'v=', 1)
                                dummy = b"x=" + b"0" * (pad_len - 3) + b"&" if pad_len >= 3 else b""
                                padded = base + dummy + b"v="
                                padded = padded.ljust(target_len, b'&')
                            else:
                                padded = prefix
                            data[pos_load:pos_load + target_len] = padded
                            print(f"  Successfully patched loader URL at offset {pos_load}")
                        else:
                            print(f"  Warning: Custom URL length ({len(prefix)}) exceeds buffer ({target_len})")

                    # 2. Patch check URL
                    pos_check = data.find(OLD_CHECK_URL)
                    if pos_check != -1:
                        target_len = len(OLD_CHECK_URL)
                        clean_url = new_worker_url.encode('utf-8')
                        if len(clean_url) <= target_len:
                            pad_len = target_len - len(clean_url)
                            dummy = (b"?x=" + b"0" * (pad_len - 4)) if pad_len >= 4 else b""
                            padded = (clean_url + dummy).ljust(target_len, b'&')
                            data[pos_check:pos_check + target_len] = padded
                            print(f"  Successfully patched check URL at offset {pos_check}")

                    # 3. Patch CSP if custom host is supplied
                    if new_host:
                        new_host_bytes = new_host.encode('utf-8') + b'\x00'
                        pos_csp = data.find(OLD_CSP_HOST)
                        if pos_csp != -1 and len(new_host_bytes) <= len(OLD_CSP_HOST):
                            padded_host = new_host_bytes.ljust(len(OLD_CSP_HOST), b'\x00')
                            data[pos_csp:pos_csp + len(OLD_CSP_HOST)] = padded_host
                            print(f"  Successfully patched CSP allowlist at offset {pos_csp}")

                    with open(lib_path, "wb") as f:
                        f.write(data)

        if not lib_found:
            print("Error: libchrobalt.so not found inside APK!")
            return False

        # Remove old META-INF signatures
        meta_inf = os.path.join(temp_dir, "META-INF")
        if os.path.exists(meta_inf):
            shutil.rmtree(meta_inf)

        # Repackage APK
        print(f"Repackaging APK to {output_apk_path}...")
        with zipfile.ZipFile(output_apk_path, 'w', compression=zipfile.ZIP_DEFLATED) as zout:
            for root, _, files in os.walk(temp_dir):
                for file in files:
                    full_path = os.path.join(root, file)
                    rel_path = os.path.relpath(full_path, temp_dir)
                    zout.write(full_path, rel_path)

        print(f"APK successfully created at: {output_apk_path}")
        print("Note: Remember to sign the APK using apksigner or uber-apk-signer before installing.")
        return True

    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python patch_apk.py <input_apk> <output_apk> [worker_url] [csp_host]")
        print("Example: python patch_apk.py cobalt-arm64.apk custom-arm64.apk https://tizentube.akzzymk45.workers.dev/userScript.js")
        sys.exit(1)

    in_apk = sys.argv[1]
    out_apk = sys.argv[2]
    url = sys.argv[3] if len(sys.argv) > 3 else "https://tizentube.akzzymk45.workers.dev/userScript.js"
    host = sys.argv[4] if len(sys.argv) > 4 else None
    patch_apk(in_apk, out_apk, url, host)

