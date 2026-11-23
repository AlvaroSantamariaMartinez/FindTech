"""PLUGIN DE EJEMPLO (externo): Optimización Estructural Evolutiva (ESO/BESO "soft-kill").

Este archivo vive FUERA del paquete `toponet` para demostrar cómo se añaden
modelos propios: cualquier `.py` de esta carpeta que registre una clase con
`@register` aparece automáticamente en la WebUI (pulsa "Recargar modelos").

Idea del método: en cada iteración se analiza la pieza con FEM y se "matan"
(se vuelven casi vacíos) los elementos que menos energía de deformación
almacenan, reduciendo el volumen un pequeño porcentaje cada vez hasta llegar al
objetivo. Los elementos muertos pueden "revivir" si su energía filtrada crece
(versión bidireccional, BESO).

Cópialo como plantilla para tus propios modelos.
"""
import numpy as np

from toponet.fem import HexMesh
from toponet.plugins import OptimizerPlugin, Param, register
from toponet.simp import DensityFilter


@register
class ESOExample(OptimizerPlugin):
    id = "beso_ejemplo"
    name = "BESO (plugin de ejemplo)"
    kind = "heurístico"
    description = ("Optimización evolutiva bidireccional: elimina el material que menos trabaja "
                   "un poco en cada iteración. Plugin externo de ejemplo (plugins/eso_ejemplo.py).")
    params = [
        Param("evolution_rate", "float", 0.04, "Tasa de evolución", min=0.01, max=0.1, step=0.01,
              help="Fracción de volumen que se elimina por iteración."),
        Param("max_iter", "int", 60, "Iteraciones máximas", min=10, max=200, step=5),
        Param("rmin", "float", 1.8, "Radio de filtro (vóxeles)", min=1.0, max=4.0, step=0.1),
    ]

    def optimize(self, problem, params, progress):
        dom, passive, design = problem.domain, problem.passive_solid, problem.design
        E0, h = problem.material.E, problem.pitch
        xmin = 1e-3
        mesh = HexMesh(dom, problem.material.nu, problem.fixed)
        filt = DensityFilter(dom, params["rmin"])
        x = dom.astype(float)
        n_dom = dom.sum()
        target = problem.volfrac * n_dom
        vol = float(n_dom)
        prev_alpha = None
        u_prev = None
        for it in range(1, params["max_iter"] + 1):
            vol = max(target, vol * (1 - params["evolution_rate"]))
            E_el = E0 * x[mesh.el_tuple] ** 3
            res = mesh.solve(E_el, h, problem.forces, x0=u_prev)
            u_prev = res.u
            alpha = (x**2) * res.ce  # sensibilidad (energía) con penalización p=3
            alpha = filt.forward(alpha)
            if prev_alpha is not None:  # estabiliza promediando con la iteración anterior
                alpha = 0.5 * (alpha + prev_alpha)
            prev_alpha = alpha
            # umbral por bisección para alcanzar `vol` elementos sólidos
            a_des = alpha[design]
            n_keep = int(round(vol - passive.sum()))
            n_keep = int(np.clip(n_keep, 1, a_des.size))
            thr = np.partition(a_des, a_des.size - n_keep)[a_des.size - n_keep]
            new = np.where(design, np.where(alpha >= thr, 1.0, xmin), x)
            new = np.where(passive, 1.0, new) * dom
            change = np.abs(new - x)[design].mean()
            x = new
            progress(it / params["max_iter"], f"BESO it {it}  volumen {x[dom].mean():.3f}  c={res.compliance:.4g}")
            if vol <= target and change < 1e-3:
                break
        return np.where(x > 0.5, 1.0, 0.0) * dom
