# 10. Referencias, ejercicios y siguientes pasos

## 10.1 Ejercicios (de menos a más)

**Física y FEM**

1. Verifica la convergencia de la flecha de la viga en voladizo con 20, 40 y 80
   elementos de longitud. Dibuja la tensión máxima en el empotramiento: ¿converge?
2. Cambia el material de PLA a aluminio en la WebUI sin cambiar la carga. ¿Cambia la
   topología? ¿Qué métricas cambian y en qué proporción? (Pista: cap. 2.8.)

**Optimización clásica**

3. En el soporte en L, optimiza con $r_{min}$ = 1.2, 1.5, 2.5. Compara el número de
   barras, la flexibilidad y el % de miembros finos.
4. Desactiva la proyección Heaviside. ¿Cuánto material gris queda? ¿Cómo afecta el
   umbral a la rigidez medida?
5. Implementa la restricción de **simetría** en SIMP (promedia $x$ con su reflejo tras
   cada actualización) y crea un plugin "SIMP simétrico".

**Red neuronal**

6. Ablación: entrena sin los canales 7–8 (pon `feats[7:9] = 0` en `build_features`
   para el entrenamiento y la inferencia). Compara el gap de flexibilidad.
7. Curva de escalado: entrena con 160, 320 y 640 muestras. Dibuja el gap de
   flexibilidad frente al tamaño del dataset (escala logarítmica). ¿Merece la pena
   generar más?
8. Añade al generador un tipo de problema propio (p. ej. "brida con 4 tornillos y
   carga central") y comprueba que la red mejora en ese tipo de pieza.
9. Implementa la **pérdida física** del cap. 7.3 y ajusta el modelo 5 épocas con ella.
10. Sustituye la U-Net por una con **atención** en el cuello de botella o por un
    **operador neuronal de Fourier** y compara.

**Sistema**

11. Crea un plugin que ejecute TopoNet con TTA y 30 iteraciones de refinamiento con
    $r_{min}$ = 2 ("modo calidad").
12. Extiende `analysis.py` con una comprobación de **voladizos para impresión 3D**
    (vóxeles sin soporte debajo con ángulo > 45°).
13. Añade **múltiples casos de carga** a la API y a SIMP (suma ponderada de flexibilidades).

## 10.2 Hoja de ruta para mejorar tu modelo

```
Nivel 1 (este repositorio) ─ U-Net 3D supervisada + rasgos físicos + híbrido con SIMP
   │
   ├─► más datos y más diversos (STL reales como dominios)          ← mayor impacto
   ├─► resolución mayor (48–64) con GPU; curriculum de resoluciones
   ├─► pérdida física (flexibilidad diferenciable) en fine-tuning
   ├─► restricciones de tensión en SIMP → etiquetas que ya optimizan resistencia
   │
Nivel 2 ─ modelos generativos (difusión condicionada, TopoDiff) → varias propuestas
   │       por problema, el usuario elige
Nivel 3 ─ representaciones sin vóxeles (GNN sobre tetraedros, campos implícitos)
           y reparametrización neuronal para resoluciones arbitrarias
```

## 10.3 Bibliografía comentada

### Optimización topológica (clásica)

* **Bendsøe, M.P. & Kikuchi, N. (1988).** Generating optimal topologies in structural
  design using a homogenization method. *Computer Methods in Applied Mechanics and
  Engineering*, 71, 197–224. — El artículo fundacional.
* **Bendsøe, M.P. & Sigmund, O. (2003).** *Topology Optimization: Theory, Methods and
  Applications.* Springer. — El libro de referencia. Capítulo 1 imprescindible.
* **Sigmund, O. (2001).** A 99 line topology optimization code written in Matlab.
  *Structural and Multidisciplinary Optimization*, 21, 120–127. — La mejor
  introducción práctica que existe (2D).
* **Andreassen, E., Clausen, A., Schevenels, M., Lazarov, B.S. & Sigmund, O. (2011).**
  Efficient topology optimization in MATLAB using 88 lines of code. *SMO*, 43, 1–16.
  — Versión vectorizada, filtros de densidad.
* **Liu, K. & Tovar, A. (2014).** An efficient 3D topology optimization code written
  in Matlab. *SMO*, 50, 1175–1196. — `top3d`: el equivalente 3D, base de nuestro `simp.py`.
* **Bruns, T.E. & Tortorelli, D.A. (2001).** Topology optimization of non-linear
  elastic structures and compliant mechanisms. *CMAME*, 190, 3443–3459; **Bourdin, B.
  (2001).** Filters in topology optimization. *IJNME*, 50, 2143–2158. — Filtro de densidad.
* **Guest, J.K., Prévost, J.H. & Belytschko, T. (2004).** Achieving minimum length
  scale in topology optimization using nodal design variables and projection
  functions. *IJNME*, 61, 238–254.
* **Wang, F., Lazarov, B.S. & Sigmund, O. (2011).** On projection methods, convergence
  and robust formulations in topology optimization. *SMO*, 43, 767–784. — Proyección tanh.
* **Svanberg, K. (1987).** The method of moving asymptotes — a new method for
  structural optimization. *IJNME*, 24, 359–373. — MMA, para restricciones múltiples.
* **Xie, Y.M. & Steven, G.P. (1993).** A simple evolutionary procedure for structural
  optimization. *Computers & Structures*, 49, 885–896. — ESO.
* **Huang, X. & Xie, Y.M. (2007).** Convergent and mesh-independent solutions for the
  bi-directional evolutionary structural optimization method. *Finite Elements in
  Analysis and Design*, 43, 1039–1049. — BESO (nuestro plugin de ejemplo).
* **Le, C., Norato, J., Bruns, T., Ha, C. & Tortorelli, D. (2010).** Stress-based
  topology optimization for continua. *SMO*, 41, 605–620. — Restricciones de tensión.
* **Aage, N., Andreassen, E., Lazarov, B.S. & Sigmund, O. (2017).** Giga-voxel
  computational morphogenesis for structural design. *Nature*, 550, 84–86.

### Elementos finitos y solvers

* **Hughes, T.J.R. (2000).** *The Finite Element Method: Linear Static and Dynamic
  Finite Element Analysis.* Dover.
* **Zienkiewicz, O.C., Taylor, R.L. & Zhu, J.Z.** *The Finite Element Method: Its
  Basis and Fundamentals.* Butterworth-Heinemann.
* **Vaněk, P., Mandel, J. & Brezina, M. (1996).** Algebraic multigrid by smoothed
  aggregation for second and fourth order elliptic problems. *Computing*, 56, 179–196.
* **Amir, O., Aage, N. & Lazarov, B.S. (2014).** On multigrid-CG for efficient topology
  optimization. *SMO*, 49, 815–829.

### Redes neuronales y optimización topológica

* **Woldseth, R.V., Aage, N., Bærentzen, J.A. & Sigmund, O. (2022).** On the use of
  artificial neural networks in topology optimisation. *SMO*, 65, 294. — **Léelo
  primero:** revisión crítica de qué funciona y qué no.
* **Sosnovik, I. & Oseledets, I. (2019).** Neural networks for topology optimization.
  *Russian Journal of Numerical Analysis and Mathematical Modelling*, 34(4). — Red que
  acelera SIMP a partir de iteraciones intermedias.
* **Banga, S., Gehani, H., Bhilare, S., Patel, S. & Kara, L. (2018).** 3D topology
  optimization using convolutional neural networks. arXiv:1808.07440.
* **Yu, Y., Hur, T., Jung, J. & Jang, I.G. (2019).** Deep learning for determining a
  near-optimal topological design without any iteration. *SMO*, 59, 787–799.
* **Zhang, Y., Peng, B., Zhou, X., Xiang, C. & Wang, D. (2019).** A deep convolutional
  neural network for topology optimization with strong generalization ability.
  arXiv:1901.07761. — Campos físicos como entrada.
* **Nie, Z., Lin, T., Jiang, H. & Kara, L.B. (2021).** TopologyGAN: Topology
  optimization using generative adversarial networks based on physical fields over
  the initial domain. *Journal of Mechanical Design*, 143(3). — Idea de nuestros canales 7–8.
* **Mazé, F. & Ahmed, F. (2023).** Diffusion models beat GANs on topology optimization.
  *AAAI*. — TopoDiff.
* **Hoyer, S., Sohl-Dickstein, J. & Greydanus, S. (2019).** Neural reparameterization
  improves structural optimization. arXiv:1909.04240.
* **Chandrasekhar, A. & Suresh, K. (2021).** TOuNN: Topology optimization using neural
  networks. *SMO*, 63, 1135–1149.

### Aprendizaje profundo (general)

* **Ronneberger, O., Fischer, P. & Brox, T. (2015).** U-Net: Convolutional networks for
  biomedical image segmentation. *MICCAI*.
* **Çiçek, Ö. et al. (2016).** 3D U-Net: Learning dense volumetric segmentation from
  sparse annotation. *MICCAI*.
* **He, K., Zhang, X., Ren, S. & Sun, J. (2016).** Deep residual learning for image
  recognition. *CVPR*.
* **Wu, Y. & He, K. (2018).** Group normalization. *ECCV*.
* **Milletari, F., Navab, N. & Ahmadi, S.-A. (2016).** V-Net: Fully convolutional
  neural networks for volumetric medical image segmentation. *3DV*. — Pérdida Dice.
* **Kingma, D.P. & Ba, J. (2015).** Adam: A method for stochastic optimization. *ICLR*.
* **Loshchilov, I. & Hutter, F. (2017).** SGDR: Stochastic gradient descent with warm
  restarts. *ICLR*; **(2019)** Decoupled weight decay regularization. *ICLR*. — Coseno y AdamW.
* **Raissi, M., Perdikaris, P. & Karniadakis, G.E. (2019).** Physics-informed neural
  networks. *Journal of Computational Physics*, 378, 686–707.
* **Li, Z. et al. (2021).** Fourier neural operator for parametric partial differential
  equations. *ICLR*.

### Física realista (capítulo 11)

* **Gustafsson, T. & McBain, G.D. (2020).** scikit-fem: A Python package for finite
  element assembly. *Journal of Open Source Software*, 5(52), 2369.
* **Hu, Y., Schneider, T., Wang, B., Zorin, D. & Panozzo, D. (2020).** Fast tetrahedral
  meshing in the wild. *ACM Transactions on Graphics*, 39(4). — fTetWild.
* **Geuzaine, C. & Remacle, J.-F. (2009).** Gmsh: a 3-D finite element mesh generator
  with built-in pre- and post-processing facilities. *IJNME*, 79, 1309–1331.
* **Bleyer, J. (2018–2024).** *Numerical Tours of Computational Mechanics with FEniCS*.
  Zenodo / comet-fenicsx. — Pandeo lineal 3D y elasticidad ortótropa.
* **Knyazev, A.V. (2001).** Toward the optimal preconditioned eigensolver: Locally
  Optimal Block Preconditioned Conjugate Gradient method. *SIAM J. Sci. Comput.*, 23(2),
  517–541. — LOBPCG.
* **Timoshenko, S.P. & Gere, J.M. (1961).** *Theory of Elastic Stability.* McGraw-Hill.
  — Pandeo de columnas y pandeo lateral-torsional.
* **Basquin, O.H. (1910).** The exponential law of endurance tests. *Proc. ASTM*, 10;
  **Goodman, J. (1899).** *Mechanics Applied to Engineering.* — Fatiga.
* **Brewer, J.C. & Lagace, P.A. (1988).** Quadratic stress criterion for initiation of
  delamination. *Journal of Composite Materials*, 22, 1141–1155.
* **Ahn, S.-H., Montero, M., Odell, D., Roundy, S. & Wright, P.K. (2002).** Anisotropic
  material properties of fused deposition modeling ABS. *Rapid Prototyping Journal*, 8(4).

### Geometría

* **Lorensen, W.E. & Cline, H.E. (1987).** Marching cubes: A high resolution 3D surface
  construction algorithm. *SIGGRAPH*.
* **Taubin, G. (1995).** A signal processing approach to fair surface design. *SIGGRAPH*.

### Libros y cursos para profundizar en redes neuronales

* Goodfellow, I., Bengio, Y. & Courville, A. (2016). *Deep Learning.* MIT Press
  (gratis en deeplearningbook.org).
* Prince, S.J.D. (2023). *Understanding Deep Learning.* MIT Press (gratis en udlbook.github.io).
* Documentación y tutoriales oficiales de PyTorch.

---
← [9. WebUI y plugins](09-webui-y-plugins.md) · [Índice](README.md)
