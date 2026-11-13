import bpy, sys, math, json
from mathutils import Vector
from bpy_extras.object_utils import world_to_camera_view
o = sys.argv[sys.argv.index("--") + 1]
bpy.ops.object.select_all(action='SELECT'); bpy.ops.object.delete()
sc = bpy.context.scene

def mat(nombre, color, rugoso=0.6, metal=0.0, alfa=1.0, emite=0.0):
    m = bpy.data.materials.new(nombre); m.use_nodes = True
    b = next(n for n in m.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
    b.inputs["Base Color"].default_value = (*color, 1); b.inputs["Roughness"].default_value = rugoso
    b.inputs["Metallic"].default_value = metal; b.inputs["Alpha"].default_value = alfa
    if emite:
        b.inputs["Emission Color"].default_value = (*color, 1); b.inputs["Emission Strength"].default_value = emite
    return m

def caja(nombre, centro, medidas, material, giro=(0, 0, 0)):
    bpy.ops.mesh.primitive_cube_add(size=1, location=centro, rotation=giro)
    ob = bpy.context.active_object; ob.name = nombre; ob.scale = medidas; ob.data.materials.append(material)
    return ob

M = dict(mesa=mat("mesa", (0.52, 0.44, 0.36), 0.7), azul=mat("azul", (0.03, 0.16, 0.55), 0.9),
         alu=mat("alu", (0.30, 0.31, 0.33), 0.35, 0.9), negro=mat("negro", (0.02, 0.02, 0.025), 0.4),
         lente=mat("lente", (0.01, 0.01, 0.015), 0.1, 0.3), led=mat("led", (1.0, 0.96, 0.88), 0.5, 0, 1, 6.0),
         soporte=mat("soporte", (0.78, 0.79, 0.80), 0.6), cerebro=mat("cerebro", (0.93, 0.66, 0.62), 0.55),
         pi=mat("pi", (0.05, 0.42, 0.22), 0.5), blanco=mat("blanco", (0.80, 0.80, 0.80), 0.5), gafas=mat("gafas", (0.62, 0.63, 0.66), 0.45),
         pantalla=mat("pantalla", (0.10, 0.25, 0.45), 0.3, 0, 1, 0.8), cono=mat("cono", (0.25, 0.60, 1.0), 0.5, 0, 0.07))

caja("mesa", (0.12, 0, -0.02), (1.7, 1.0, 0.04), M["mesa"])
caja("base", (0, 0, 0.002), (0.66, 0.66, 0.004), M["azul"])
L, ALTO, CENTRO = 0.31, 0.58, Vector((0, 0, 0.22))
for sx in (-1, 1):
    for sy in (-1, 1):
        caja("poste", (sx * L, sy * L, ALTO / 2), (0.02, 0.02, ALTO), M["alu"])
for s in (-1, 1):
    caja("travesano", (0, s * L, ALTO - 0.01), (2 * L, 0.02, 0.02), M["alu"])
    caja("travesano", (s * L, 0, ALTO - 0.01), (0.02, 2 * L, 0.02), M["alu"])
    caja("led", (0, s * (L - 0.012), ALTO - 0.024), (2 * L - 0.08, 0.008, 0.003), M["led"])
    caja("led", (s * (L - 0.012), 0, ALTO - 0.024), (0.008, 2 * L - 0.08, 0.003), M["led"])

camaras = []
for sx in (-1, 1):
    for sy in (-1, 1):
        sitio = Vector((sx * 0.285, sy * 0.285, 0.545))
        q = (CENTRO - sitio).to_track_quat('-Z', 'Y')
        cuerpo = caja("camara", sitio + q @ Vector((0, 0, 0.012)), (0.04, 0.04, 0.022), M["negro"]); cuerpo.rotation_euler = q.to_euler()
        bpy.ops.mesh.primitive_cylinder_add(radius=0.015, depth=0.036, location=sitio + q @ Vector((0, 0, -0.018)))
        lente = bpy.context.active_object; lente.rotation_euler = q.to_euler(); lente.data.materials.append(M["lente"])
        # (lo que ve: 45° × 35° con la lente de 6 mm)
        d, a, b = 0.50, math.tan(math.radians(22.7)), math.tan(math.radians(17.4))
        v = [sitio] + [sitio + q @ Vector((ix * a * d, iy * b * d, -d)) for ix, iy in ((-1, -1), (1, -1), (1, 1), (-1, 1))]
        me = bpy.data.meshes.new("cono"); me.from_pydata([tuple(p) for p in v], [], [(0, 1, 2), (0, 2, 3), (0, 3, 4), (0, 4, 1)]); me.update()
        ob = bpy.data.objects.new("cono", me); sc.collection.objects.link(ob); ob.data.materials.append(M["cono"])
        ob.visible_shadow = False
        camaras.append(sitio)

for archivo, material, giro, sitio in (("/home/user/FindTech/entrega/soporte-cerebro/1r_base_y_plato_sin_paredes.stl", M["soporte"], 0, (0, 0, 0.004)),
                                       (o + "/cerebro_generico.stl", M["cerebro"], 0, (0, 0, 0.111))):
    bpy.ops.wm.stl_import(filepath=archivo)
    ob = bpy.context.active_object; ob.scale = (0.001, 0.001, 0.001); ob.location = sitio; ob.data.materials.append(material)
    if "cerebro" in archivo:
        bpy.ops.object.shade_smooth()
for s in (-1, 1):  # (las almohadillas que sujetan la pieza)
    bpy.ops.mesh.primitive_cylinder_add(radius=0.018, depth=0.012, location=(s * 0.066, 0, 0.111), rotation=(0, math.pi / 2, 0))
    bpy.context.active_object.data.materials.append(M["soporte"])

# (la referencia fija para las gafas: un código QR pegado a la base)
caja("qr", (-0.22, -0.24, 0.0045), (0.09, 0.09, 0.001), M["blanco"])
import random; random.seed(4)
for i in range(7):
    for j in range(7):
        esquina = (i < 2 and j < 2) or (i < 2 and j > 4) or (i > 4 and j < 2)
        if esquina or random.random() < 0.45:
            caja("qr_", (-0.22 + (i - 3) * 0.011, -0.24 + (j - 3) * 0.011, 0.0052), (0.011, 0.011, 0.0006), M["negro"])
for s in (-1, 1):  # (una Raspberry Pi 5 por cada dos cámaras, en los postes de atrás)
    caja("pi", (s * L, L + 0.022, 0.30), (0.062, 0.022, 0.09), M["pi"])
caja("switch", (0, L + 0.06, 0.016), (0.12, 0.07, 0.028), M["blanco"])
# (el PC de MRAnalyzer)
caja("pc", (0.68, -0.05, 0.008), (0.32, 0.22, 0.016), M["alu"])
caja("pc_pantalla", (0.68, 0.085, 0.11), (0.32, 0.012, 0.20), M["alu"], (math.radians(-12), 0, 0))
caja("pc_imagen", (0.68, 0.0775, 0.11), (0.30, 0.002, 0.18), M["pantalla"], (math.radians(-12), 0, 0))
# (las gafas, donde estaría quien mira)
ojos = Vector((0.02, -0.66, 0.48)); q = (CENTRO - ojos).to_track_quat('-Z', 'Y')
g = caja("gafas", ojos, (0.19, 0.10, 0.09), M["gafas"]); g.rotation_euler = q.to_euler()
bpy.ops.object.modifier_add(type='BEVEL'); g.modifiers[-1].width = 0.02; g.modifiers[-1].segments = 6
f = caja("gafas_frente", ojos + q @ Vector((0, 0, -0.046)), (0.17, 0.085, 0.004), M["negro"]); f.rotation_euler = q.to_euler()

sc.render.engine = 'CYCLES'; sc.cycles.device = 'CPU'; sc.cycles.samples = 72
try:
    sc.cycles.use_denoising = True
except Exception:
    pass
sc.render.resolution_x, sc.render.resolution_y = 1600, 1040
sc.render.image_settings.file_format = 'JPEG'; sc.render.image_settings.quality = 88
sc.view_settings.view_transform = 'AgX'; sc.view_settings.look = 'AgX - Medium High Contrast'
w = bpy.data.worlds.new("m"); w.use_nodes = True; sc.world = w
w.node_tree.nodes["Background"].inputs[0].default_value = (0.93, 0.94, 0.96, 1); w.node_tree.nodes["Background"].inputs[1].default_value = 0.75
sol = bpy.data.objects.new("sol", bpy.data.lights.new("sol", 'SUN')); sol.data.energy = 2.4; sol.data.angle = 0.3
sol.rotation_euler = (math.radians(48), 0, math.radians(35)); sc.collection.objects.link(sol)
cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam")); sc.collection.objects.link(cam); sc.camera = cam
cam.data.lens = 33
cam.location = (1.05, -1.42, 1.02)
cam.rotation_euler = (Vector((0.10, -0.14, 0.20)) - cam.location).to_track_quat('-Z', 'Y').to_euler()
bpy.context.view_layer.update()
marcas = {"camara": camaras[1], "marco": Vector((L, -L, 0.33)), "luz": Vector((0, L - 0.012, ALTO - 0.024)), "pieza": Vector((0, 0, 0.16)),
          "base": Vector((0.2, -0.22, 0.004)), "qr": Vector((-0.22, -0.24, 0.005)), "pi": Vector((L, L + 0.022, 0.30)),
          "pc": Vector((0.68, 0.08, 0.12)), "gafas": ojos}
json.dump({k: [round(world_to_camera_view(sc, cam, v).x, 4), round(1 - world_to_camera_view(sc, cam, v).y, 4)] for k, v in marcas.items()},
          open(o + "/marcas.json", "w"))
sc.render.filepath = o + "/maqueta.jpg"
bpy.ops.render.render(write_still=True)
