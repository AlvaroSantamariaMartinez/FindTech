"""Genera piezas STL de ejemplo a partir de funciones de distancia con signo (SDF).

    python examples/generate_examples.py

Crea en esta carpeta:
  viga_voladizo.stl   bloque 120x30x30 mm (empotrar x-min, cargar en x-max)
  soporte_L.stl       escuadra en L con taladros (atornillar la base, cargar el brazo)
  puente.stl          bloque 160x30x40 mm (apoyos en los extremos inferiores, carga arriba)
  brida.stl           placa con un taladro central y 4 de fijación
"""
from __future__ import annotations

import os

import numpy as np
from skimage import measure
import trimesh

HERE = os.path.dirname(os.path.abspath(__file__))


def box_sdf(p, lo, hi):
    c = (np.asarray(lo) + np.asarray(hi)) / 2
    e = (np.asarray(hi) - np.asarray(lo)) / 2
    q = np.abs(p - c) - e
    return np.linalg.norm(np.maximum(q, 0), axis=-1) + np.minimum(q.max(-1), 0)


def cyl_sdf(p, center, radius, axis, half_len):
    c = np.asarray(center, float)
    d = p - c
    ax = "xyz".index(axis)
    radial = np.linalg.norm(np.delete(d, ax, axis=-1), axis=-1) - radius
    along = np.abs(d[..., ax]) - half_len
    q = np.stack([radial, along], -1)
    return np.linalg.norm(np.maximum(q, 0), axis=-1) + np.minimum(q.max(-1), 0)


def mesh_from_sdf(sdf_fn, lo, hi, step=1.0) -> trimesh.Trimesh:
    lo = np.asarray(lo, float) - 2 * step + 0.37 * step  # evita nodos justo sobre las caras
    hi = np.asarray(hi, float) + 2 * step
    axes = [np.arange(lo[i], hi[i] + step, step) for i in range(3)]
    P = np.stack(np.meshgrid(*axes, indexing="ij"), -1)
    vals = sdf_fn(P)
    v, f, _, _ = measure.marching_cubes(vals, level=0.0, spacing=(step, step, step))
    m = trimesh.Trimesh(v + lo, f, process=True)
    trimesh.repair.fix_normals(m)
    return m


def main():
    shapes = {
        "viga_voladizo.stl": (lambda p: box_sdf(p, (0, 0, 0), (120, 30, 30)), (0, 0, 0), (120, 30, 30)),
        "puente.stl": (lambda p: box_sdf(p, (0, 0, 0), (160, 30, 40)), (0, 0, 0), (160, 30, 40)),
    }

    def soporte(p):
        base = box_sdf(p, (0, 0, 0), (80, 40, 10))
        brazo = box_sdf(p, (0, 0, 0), (10, 40, 70))
        d = np.minimum(base, brazo)
        for x in (25, 65):  # taladros de la base
            d = np.maximum(d, -cyl_sdf(p, (x, 20, 5), 3.5, "z", 10))
        d = np.maximum(d, -cyl_sdf(p, (5, 20, 58), 4.0, "x", 10))  # taladro del brazo
        return d

    shapes["soporte_L.stl"] = (soporte, (0, 0, 0), (80, 40, 70))

    def brida(p):
        d = cyl_sdf(p, (0, 0, 6), 50, "z", 6)
        d = np.maximum(d, -cyl_sdf(p, (0, 0, 6), 12, "z", 10))
        for ang in np.deg2rad([45, 135, 225, 315]):
            d = np.maximum(d, -cyl_sdf(p, (38 * np.cos(ang), 38 * np.sin(ang), 6), 4, "z", 10))
        return d

    shapes["brida.stl"] = (brida, (-50, -50, 0), (50, 50, 12))

    for name, (fn, lo, hi) in shapes.items():
        m = mesh_from_sdf(fn, lo, hi, step=1.5)
        path = os.path.join(HERE, name)
        m.export(path)
        print(f"{name}: {len(m.faces)} triángulos, estanca={m.is_watertight}, volumen={m.volume:.0f} mm³")


if __name__ == "__main__":
    main()
