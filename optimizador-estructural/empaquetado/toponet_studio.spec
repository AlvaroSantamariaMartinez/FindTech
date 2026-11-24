# -*- mode: python ; coding: utf-8 -*-
"""Receta de PyInstaller para el ejecutable de TopoNet Studio.

    cd optimizador-estructural
    pyinstaller empaquetado/toponet_studio.spec --noconfirm

Genera `dist/TopoNetStudio/` (carpeta con el ejecutable `TopoNetStudio` /
`TopoNetStudio.exe` y sus librerías). Se usa el modo "carpeta" (onedir) y no
"un solo archivo" porque PyTorch es muy grande: así el programa arranca en
segundos en lugar de descomprimir ~1 GB en cada inicio.
"""
import glob
import importlib.util
import os
import sys

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))  # noqa: F821 (SPECPATH lo define PyInstaller)
sys.path.insert(0, ROOT)  # para que collect_submodules("toponet") encuentre el paquete

# ---------------------------------------------------------------- librerías nativas
binaries = []
# fTetWild: solo el núcleo compilado (sin el __init__ que importa PyVista/VTK)
spec = importlib.util.find_spec("pytetwild")
if spec and spec.submodule_search_locations:
    for f in glob.glob(os.path.join(spec.submodule_search_locations[0], "PyfTetWildWrapper*")):
        if f.endswith((".so", ".pyd")):
            binaries.append((f, "pytetwild"))
# gmsh (respaldo del mallador): gmsh.py busca la librería junto a sí mismo
try:
    import gmsh  # noqa: E402

    if getattr(gmsh, "libpath", None):
        binaries.append((gmsh.libpath, "."))
except Exception as e:  # pragma: no cover
    print("AVISO: gmsh no disponible para empaquetar:", e)

# ---------------------------------------------------------------- datos
datas = [
    (os.path.join(ROOT, "webui", "static"), os.path.join("webui", "static")),
    (os.path.join(ROOT, "guia"), "guia"),
]
for f in glob.glob(os.path.join(ROOT, "plugins", "*.py")):
    datas.append((f, "plugins"))
for f in glob.glob(os.path.join(ROOT, "examples", "*.stl")):
    datas.append((f, "examples"))
for f in glob.glob(os.path.join(ROOT, "checkpoints", "*")):
    if not f.endswith("_state.pt"):
        datas.append((f, "checkpoints"))
datas += collect_data_files("trimesh")
datas += collect_data_files("skfem")

# ---------------------------------------------------------------- módulos
hiddenimports = (
    collect_submodules("toponet")
    + collect_submodules("webui")
    + collect_submodules("skfem")
    + collect_submodules("pyamg")
    + collect_submodules("uvicorn")
    # los plugins incluidos se importan dinámicamente: hay que nombrarlos
    + ["toponet.plugins.simp_baseline", "toponet.plugins.neural_unet", "toponet.physics.advanced",
       "toponet.physics.tetmesh", "fatpack", "multipart", "python_multipart", "skimage.measure", "skimage.measure._marching_cubes_lewiner",
       "scipy.spatial", "scipy.sparse.linalg", "gmsh", "fast_simplification", "httpx"]
)
excludes = ["tkinter", "matplotlib", "pyvista", "vtk", "vtkmodules", "IPython", "jupyter", "pandas",
            "pytetwild", "torchvision", "torchaudio"]

a = Analysis(  # noqa: F821
    [os.path.join(ROOT, "toponet_studio.py")],
    pathex=[ROOT],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=excludes,
    noarchive=False,
)
pyz = PYZ(a.pure)  # noqa: F821
exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="TopoNetStudio",
    console=True,  # ventana de consola: muestra la URL, el progreso de entrenamiento y los errores
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name="TopoNetStudio", upx=False)  # noqa: F821
