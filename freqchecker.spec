# -*- mode: python ; coding: utf-8 -*-
import os
from PyInstaller.utils.hooks import collect_all

# SPECPATH is the directory containing this spec file, so the spec is
# reproducible on any machine instead of hardcoding C:/Users/... paths.
_base = SPECPATH

datas = [
    (os.path.join(_base, 'fonts'), 'fonts'),
    (os.path.join(_base, 'assets'), 'assets'),
]
binaries = []
hiddenimports = ['PySide6.QtCore', 'PySide6.QtGui', 'PySide6.QtWidgets', 'PySide6.QtSvg', 'icons', 'fx_theme', 'numpy']
tmp_ret = collect_all('sounddevice')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
try:
    import soundfile  # noqa: F401
    tmp_ret = collect_all('soundfile')
    datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
except ImportError:
    pass


a = Analysis(
    [os.path.join(_base, 'app.py')],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['matplotlib', 'scipy', 'PIL', 'tkinter', 'pandas', 'torch', 'librosa', 'PySide6.Qt3DAnimation', 'PySide6.Qt3DCore', 'PySide6.Qt3DExtras', 'PySide6.Qt3DInput', 'PySide6.Qt3DLogic', 'PySide6.Qt3DRender', 'PySide6.QtQuick', 'PySide6.QtQuickWidgets', 'PySide6.QtQuick3D', 'PySide6.QtQml', 'PySide6.QtMultimedia', 'PySide6.QtMultimediaWidgets', 'PySide6.QtWebEngineCore', 'PySide6.QtWebEngineWidgets', 'PySide6.QtWebEngineQuick', 'PySide6.QtPdf', 'PySide6.QtPdfWidgets', 'PySide6.QtSensors', 'PySide6.QtPositioning', 'PySide6.QtNfc', 'PySide6.QtBluetooth', 'PySide6.QtNetworkAuth', 'PySide6.QtSpatialAudio', 'PySide6.QtCharts', 'PySide6.QtDataVisualization', 'PySide6.QtDesigner', 'PySide6.QtHelp', 'PySide6.QtLocation', 'PySide6.QtRemoteObjects', 'PySide6.QtScxml', 'PySide6.QtSql', 'PySide6.QtTest', 'PySide6.QtUiTools', 'PySide6.QtVirtualKeyboard', 'PySide6.QtWebChannel', 'PySide6.QtWebSockets'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='freqchecker',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=[os.path.join(_base, 'assets', 'app-icon.ico')],
)
