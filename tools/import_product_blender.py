"""Run: blender --background --python tools/import_product_blender.py -- /path/out.blend
Imports supplied tessellated CAD only. Basic materials, no final lighting/screen approval.
"""
import bpy,json,base64,struct,sys
from pathlib import Path
root=Path(__file__).resolve().parents[1]
data=json.loads((root/'assets/models/parts-data.json').read_text(encoding='utf-8'))
if isinstance(data,dict): data=data.get('parts',data.get('meshes',[]))
def unpack(s,fmt):
    raw=base64.b64decode(s)
    return struct.unpack('<'+fmt*(len(raw)//4),raw)
bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.delete(use_global=False)
white=bpy.data.materials.new('White satin resin');white.diffuse_color=(0.80,0.81,0.82,1);white.use_nodes=True
gray=bpy.data.materials.new('Graphite satin resin');gray.diffuse_color=(0.055,0.065,0.075,1);gray.use_nodes=True
for mat in [white,gray]:
    bsdf=mat.node_tree.nodes.get('Principled BSDF');bsdf.inputs['Base Color'].default_value=mat.diffuse_color;bsdf.inputs['Roughness'].default_value=0.30
for part in data:
    p=unpack(part['positions'],'f');idx=unpack(part['indices'],'I')
    # CAD Y-up -> Blender Z-up; convert mm to metres once for all parts.
    verts=[(p[i]*.001,-p[i+2]*.001,p[i+1]*.001) for i in range(0,len(p),3)]
    faces=[tuple(idx[i:i+3]) for i in range(0,len(idx),3)]
    mesh=bpy.data.meshes.new(part['name']);mesh.from_pydata(verts,[],faces);mesh.update()
    ob=bpy.data.objects.new(part['name'],mesh);bpy.context.collection.objects.link(ob)
    ob.data.materials.append(white if part['name'] in ['front','left_knob','right_knob'] else gray)
    if part.get('normals'):
        n=unpack(part['normals'],'f');norms=[(n[i],-n[i+2],n[i+1]) for i in range(0,len(n),3)]
        mesh.normals_split_custom_set_from_vertices(norms)
bpy.context.scene.unit_settings.system='METRIC'
out=Path(sys.argv[sys.argv.index('--')+1]) if '--' in sys.argv else root/'product-import.blend'
bpy.ops.wm.save_as_mainfile(filepath=str(out.resolve()))
print('Imported',len(data),'CAD parts; screen, camera and lighting need finishing.')
