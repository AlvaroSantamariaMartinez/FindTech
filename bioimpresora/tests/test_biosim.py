import numpy as np
import pytest

from biosim.config import ParametrosProceso
from biosim.geometria import MAT_A, MAT_B, ORGANOS, generar
from biosim.ia.red import RedNeuronal
from biosim.materiales import MATERIAL_A, MATERIAL_B
from biosim.planificador import planificar
from biosim.simulador import simular


@pytest.mark.parametrize("organo", list(ORGANOS))
def test_geometrias_tienen_ambos_materiales(organo):
    g = generar(organo)
    assert (g.mat == MAT_A).any() and (g.mat == MAT_B).any()


def test_caudal_crece_con_presion_y_umbral():
    q = [MATERIAL_B.caudal_mm3_s(p, 0.125, 6.0) for p in (40, 80, 160)]
    assert q[0] < q[1] < q[2]
    assert MATERIAL_A.caudal_mm3_s(1.0, 0.125, 6.0) == 0.0  # por debajo del esfuerzo umbral


def test_cada_voxel_se_deposita_una_vez():
    g = generar("vaso")
    plan = planificar(g, ParametrosProceso())
    assert np.array_equal(np.isfinite(plan.t_dep), g.mat > 0)
    assert plan.instantes_colision == 0


def test_paralelo_evita_colisiones():
    plan = planificar(generar("parche_cardiaco"), ParametrosProceso(estrategia="paralelo"))
    assert plan.instantes_colision == 0
    assert plan.holgura_min_mm >= 0


def test_seguimiento_fuerza_secuencial():
    p = ParametrosProceso(modo_uv="seguimiento", estrategia="paralelo").validar()
    assert p.estrategia == "secuencial"


def test_mas_uv_mas_curado_menos_viabilidad():
    lo = simular("vaso", ParametrosProceso(intensidad_uv_mw_cm2=8)).metricas
    hi = simular("vaso", ParametrosProceso(intensidad_uv_mw_cm2=60)).metricas
    assert hi["conversion_media"] > lo["conversion_media"]
    assert hi["viabilidad"] < lo["viabilidad"]


def test_metricas_en_rango():
    m = simular("lobulo_hepatico", ParametrosProceso()).metricas
    for k in ("fidelidad_iou", "viabilidad", "fraccion_curada", "conversion_media"):
        assert 0.0 <= m[k] <= 1.0


def test_red_aprende_funcion_simple_y_gradiente():
    rng = np.random.default_rng(0)
    X = rng.uniform(-1, 1, (512, 2))
    Y = (X[:, :1] ** 2 + np.sin(2 * X[:, 1:]))
    red = RedNeuronal([2, 32, 32, 1], semilla=0)
    red.entrenar(X[:400], Y[:400], X[400:], Y[400:], epocas=200, verbose=False)
    assert ((red.predecir(X[400:]) - Y[400:]) ** 2).mean() < 0.01
    # gradiente respecto a la entrada vs diferencias finitas
    x = X[:3]
    _, g = red.gradiente_entrada(x, np.ones(1))
    eps = 1e-5
    for j in range(2):
        d = np.zeros_like(x)
        d[:, j] = eps
        num = (red.predecir(x + d) - red.predecir(x - d))[:, 0] / (2 * eps)
        assert np.allclose(num, g[:, j], atol=1e-4)
