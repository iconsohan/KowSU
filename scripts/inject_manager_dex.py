#!/usr/bin/env python3
"""Inject the custom manager dialog DEX and call it from MainActivity."""

from __future__ import annotations

import argparse
import re
import subprocess
import tempfile
import zipfile
from pathlib import Path


OLD_TELEGRAM = "https://t.me/ffjod1"
NEW_TELEGRAM = "https://t.me/blazemvp69"
MAIN_ACTIVITY = Path("me/weishu/kernelsu/ui/MainActivity.smali")
INVOKE = "    invoke-static {p0}, Lcom/yt/dpmods/dialog;->show(Landroid/app/Activity;)V\n"


def run(*args: str) -> None:
    subprocess.run(args, check=True)


def next_dex_name(names: set[str]) -> str:
    indexes = []
    for name in names:
        match = re.fullmatch(r"classes(?:(\d+))?\.dex", name)
        if match:
            indexes.append(int(match.group(1) or "1"))
    if not indexes:
        raise RuntimeError("APK has no classes.dex")
    return f"classes{max(indexes) + 1}.dex"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apk", required=True, type=Path)
    parser.add_argument("--custom-dex", required=True, type=Path)
    parser.add_argument("--baksmali", required=True, type=Path)
    parser.add_argument("--smali", required=True, type=Path)
    args = parser.parse_args()

    args.apk = args.apk.resolve()
    args.custom_dex = args.custom_dex.resolve()
    with tempfile.TemporaryDirectory(prefix="manager-dex-") as temp:
        root = Path(temp)
        main_dex = root / "classes.dex"
        custom_smali = root / "custom-smali"
        manager_smali = root / "manager-smali"
        patched_custom = root / "classes-custom.dex"
        patched_main = root / "classes-main.dex"

        with zipfile.ZipFile(args.apk) as apk:
            entries = apk.namelist()
            if "classes.dex" not in entries:
                raise RuntimeError("Manager APK does not contain classes.dex")
            if any(name.endswith("/com/yt/dpmods/dialog.smali") for name in entries):
                raise RuntimeError("Unexpected DEX source in APK")
            main_dex.write_bytes(apk.read("classes.dex"))
            new_dex_name = next_dex_name(set(entries))
            if new_dex_name in entries:
                raise RuntimeError(f"Refusing to overwrite {new_dex_name}")

        run("java", "-jar", str(args.baksmali), "disassemble", str(args.custom_dex), "-o", str(custom_smali))
        dialog = custom_smali / "com/yt/dpmods/dialog.smali"
        if not dialog.is_file():
            raise RuntimeError("Custom DEX does not define Lcom/yt/dpmods/dialog;")
        dialog_text = dialog.read_text(encoding="utf-8")
        replacements = dialog_text.count(OLD_TELEGRAM)
        if replacements < 1:
            raise RuntimeError("Original Telegram URL was not found in supplied DEX")
        dialog.write_text(dialog_text.replace(OLD_TELEGRAM, NEW_TELEGRAM), encoding="utf-8")
        run("java", "-jar", str(args.smali), "assemble", str(custom_smali), "-o", str(patched_custom))

        run("java", "-jar", str(args.baksmali), "disassemble", str(main_dex), "-o", str(manager_smali))
        activity = manager_smali / MAIN_ACTIVITY
        if not activity.is_file():
            raise RuntimeError("Manager MainActivity was not found in classes.dex")
        activity_text = activity.read_text(encoding="utf-8")
        method_start = activity_text.find(".method public final onCreate(Landroid/os/Bundle;)V")
        if method_start < 0:
            raise RuntimeError("MainActivity onCreate(Bundle) was not found")
        method_end = activity_text.find(".end method", method_start)
        method = activity_text[method_start:method_end]
        if INVOKE.strip() in method:
            raise RuntimeError("Dialog invocation already exists in onCreate")
        super_call = re.search(r"^\s*invoke-super \{p0, p1\}, .*->onCreate\(Landroid/os/Bundle;\)V\s*$", method, re.M)
        if not super_call:
            raise RuntimeError("Could not identify MainActivity's onCreate super call")
        insert_at = method_start + super_call.end()
        activity_text = activity_text[:insert_at] + "\n" + INVOKE + activity_text[insert_at:]
        activity.write_text(activity_text, encoding="utf-8")
        run("java", "-jar", str(args.smali), "assemble", str(manager_smali), "-o", str(patched_main))

        temp_apk = args.apk.with_suffix(".injected.apk")
        try:
            with zipfile.ZipFile(args.apk) as source, zipfile.ZipFile(temp_apk, "w") as dest:
                for entry in source.infolist():
                    if entry.filename == "classes.dex":
                        data = patched_main.read_bytes()
                    else:
                        data = source.read(entry.filename)
                    dest.writestr(entry, data)
                dest.write(patched_custom, new_dex_name, compress_type=zipfile.ZIP_DEFLATED)
            temp_apk.replace(args.apk)
        finally:
            temp_apk.unlink(missing_ok=True)

    print(f"Injected dialog into classes.dex; custom DEX added as {new_dex_name} ({replacements} Telegram URL occurrences updated).")


if __name__ == "__main__":
    main()
