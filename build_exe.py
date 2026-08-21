"""
build_exe.py - Automated PyInstaller packaging for standalone freqchecker.exe.
"""

import os
import sys
import subprocess
import shutil

def build():
    print("=" * 60)
    print("  Optimized Standalone Build: freqchecker.exe")
    print("=" * 60)

    base_dir = os.path.abspath(os.path.dirname(__file__))
    dist_dir = os.path.join(base_dir, "dist")
    build_dir = os.path.join(base_dir, "build")

    # 1. Run unit test suite before compiling
    print("Running automated test suite verification...")
    test_res = subprocess.run([sys.executable, "test_diagnostic.py"], cwd=base_dir)
    if test_res.returncode != 0:
        print("[!] Unit tests failed. Aborting build to ensure binary integrity.")
        sys.exit(test_res.returncode)
    print("[+] All unit tests passed successfully.\n")

    if os.path.exists(dist_dir):
        print(f"Cleaning dist: {dist_dir}")
        shutil.rmtree(dist_dir, ignore_errors=True)
    if os.path.exists(build_dir):
        print(f"Cleaning build: {build_dir}")
        shutil.rmtree(build_dir, ignore_errors=True)

    excluded = [
        "matplotlib", "scipy", "PIL", "tkinter", "pandas", "torch", "librosa",
        "PySide6.Qt3DAnimation", "PySide6.Qt3DCore", "PySide6.Qt3DExtras",
        "PySide6.Qt3DInput", "PySide6.Qt3DLogic", "PySide6.Qt3DRender",
        "PySide6.QtQuick", "PySide6.QtQuickWidgets", "PySide6.QtQuick3D",
        "PySide6.QtQml", "PySide6.QtMultimedia", "PySide6.QtMultimediaWidgets",
        "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtWebEngineQuick",
        "PySide6.QtPdf", "PySide6.QtPdfWidgets", "PySide6.QtSensors", "PySide6.QtPositioning",
        "PySide6.QtNfc", "PySide6.QtBluetooth", "PySide6.QtNetworkAuth", "PySide6.QtSpatialAudio",
        "PySide6.QtCharts", "PySide6.QtDataVisualization", "PySide6.QtDesigner",
        "PySide6.QtHelp", "PySide6.QtLocation", "PySide6.QtRemoteObjects", "PySide6.QtScxml",
        "PySide6.QtSql", "PySide6.QtTest", "PySide6.QtUiTools", "PySide6.QtVirtualKeyboard",
        "PySide6.QtWebChannel", "PySide6.QtWebSockets"
    ]

    cmd = [
        sys.executable,
        "-m", "PyInstaller",
        "--name=freqchecker",
        "--windowed",
        "--onefile",
        "--clean",
        "--noconfirm",
        "--collect-all=sounddevice",
        "--add-data=" + os.path.join(base_dir, "fonts") + os.pathsep + "fonts",
        "--hidden-import=PySide6.QtCore",
        "--hidden-import=PySide6.QtGui",
        "--hidden-import=PySide6.QtWidgets",
        "--hidden-import=PySide6.QtSvg",
        "--hidden-import=icons",
        "--hidden-import=fx_theme",
        "--hidden-import=numpy",
    ]

    import importlib.util
    if importlib.util.find_spec("soundfile") is not None:
        cmd.append("--collect-all=soundfile")

    for ex in excluded:
        cmd.append(f"--exclude-module={ex}")

    cmd.append(os.path.join(base_dir, "app.py"))

    print("Running PyInstaller to compile freqchecker.exe...")
    res = subprocess.run(cmd, cwd=base_dir)

    if res.returncode == 0:
        exe_path = os.path.join(dist_dir, "freqchecker.exe")
        target_bundle_exe = os.path.join(base_dir, "freqchecker.exe")
        if os.path.exists(exe_path):
            try:
                shutil.copy2(exe_path, target_bundle_exe)
            except Exception as e:
                print(f"[!] Warning: Could not copy executable to base folder (file may be locked): {e}")

            size_mb = os.path.getsize(exe_path) / (1024 * 1024)
            print("=" * 60)
            print(f"  BUILD COMPLETE: Standalone freqchecker.exe created successfully!")
            print(f"  Executable in dist:   {exe_path}")
            if os.path.exists(target_bundle_exe):
                print(f"  Executable in folder: {target_bundle_exe}")
            print(f"  File Size:            {size_mb:.2f} MB")
            print("=" * 60)
        else:
            print("Executable not found after build.")
    else:
        print(f"Build failed with exit code: {res.returncode}")
        sys.exit(res.returncode)

if __name__ == "__main__":
    build()
