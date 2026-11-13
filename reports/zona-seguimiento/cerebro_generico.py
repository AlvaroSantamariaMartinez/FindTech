"""La forma genérica de cerebro de la maqueta (no es de ningún paciente). Uso: python cerebro_generico.py salida.stl"""
import sys

import numpy as np
import trimesh

s = trimesh.creation.icosphere(subdivisions=5)
x, y, z = s.vertices[:, 0], s.vertices[:, 1], s.vertices[:, 2]
r = 1 + 0.012 * np.sin(9 * x + 1) * np.sin(11 * y) * np.sin(8 * z + 2) + 0.010 * np.sin(17 * x) * np.sin(13 * y + 1) * np.sin(15 * z)
r = r - 0.07 * np.exp(-(x / 0.07) ** 2) * (z > -0.2)
v = np.stack([0.068 * x * (1 - 0.15 * y) / 1.15, 0.092 * y, np.where(z > 0, 0.080, 0.055) * z], 1) * r[:, None]
trimesh.Trimesh(v * 1000, s.faces).export(sys.argv[1])
