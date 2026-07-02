"""
building_3d_generator.py
GPT-4o Vision で図面を解析して建物の3D形状を推定し、
Three.js インタラクティブHTMLを生成する。
"""
import base64
import json


_SYSTEM_PROMPT = """あなたは建築図面を読み取る専門家です。
建築立面図・平面図・矩計図を解析し、建物の3D形状データをJSONで返します。
JSONのみを返し、説明文は一切含めないでください。"""

_USER_PROMPT = """この建築図面を解析して、建物の3D形状を推定してください。

以下のJSON形式で返してください（数値単位はすべてメートル）:

{
  "building_type": "立面図 or 平面図 or 不明",
  "note": "縮尺・推定根拠のメモ（日本語）",
  "dimensions": {
    "total_width": 数値（建物全幅）,
    "total_depth": 数値（建物奥行き。立面図のみの場合は幅の0.8倍で推定）,
    "eave_height": 数値（軒高。一般的な2階建て=5.5m、平屋=3m）,
    "ridge_height": 数値（棟高。軒高+屋根高さ）
  },
  "walls": [
    {"label": "南壁", "x": 0, "y": 0, "z": 0, "width": 数値, "height": 数値, "depth": 0.2, "color": "#c8b89a"},
    {"label": "北壁", "x": 0, "y": 奥行き, "z": 0, "width": 数値, "height": 数値, "depth": 0.2, "color": "#c8b89a"},
    {"label": "西壁", "x": 0, "y": 0, "z": 0, "width": 0.2, "height": 数値, "depth": 奥行き, "color": "#b8a888"},
    {"label": "東壁", "x": 幅, "y": 0, "z": 0, "width": 0.2, "height": 数値, "depth": 奥行き, "color": "#b8a888"}
  ],
  "roof": {
    "type": "切妻 or 寄棟 or 片流れ or 陸屋根",
    "eave_height": 数値,
    "ridge_height": 数値
  },
  "openings": [
    {
      "type": "窓 or ドア or 玄関",
      "x": 数値（建物左端からの水平距離m）,
      "y": 0（南壁の場合）,
      "z": 数値（床面からの高さm。腰窓=0.9、掃出窓=0、ドア=0）,
      "width": 数値（開口幅m）,
      "height": 数値（開口高さm）
    }
  ],
  "floors": [
    {"label": "基礎", "x": 0, "y": 0, "z": -0.3, "width": 幅, "depth": 奥行き, "height": 0.3}
  ]
}

ルール:
- 図面に寸法値があれば必ずその値を使う（縮尺から換算）
- 図面に寸法がなければ: 2階建て幅10m奥行8m軒高5.5m棟高8mで推定
- walls は必ず南北東西の4面を記述
- openings の z は床面からの高さ（1階腰窓=0.9m、掃出窓=0m、ドア=0m、2階窓=3.5m）
- floors の color フィールドは省略（コード側で設定）
- 屋根typeは図面の形状から正確に判断: 三角断面=切妻、四方流れ=寄棟、1面のみ=片流れ
- JSONのみ返すこと（説明文不要）
"""


def analyze_drawing_3d(img_bytes: bytes, api_key: str) -> dict:
    """
    GPT-4o Vision で図面を解析して建物3Dデータを返す。
    Returns: dict（エラー時は {"error": "..."} ）
    """
    raw = ""
    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key)
        b64 = base64.b64encode(img_bytes).decode("utf-8")
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": _USER_PROMPT},
                        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}", "detail": "high"}},
                    ],
                },
            ],
            max_tokens=2500,
            temperature=0.2,
        )
        raw = response.choices[0].message.content.strip()
        _raw_for_log = raw  # ログ用（markdownストリップ前）
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        result = json.loads(raw.strip())
        result["_raw_gpt_response"] = _raw_for_log  # ログ用
        return result
    except json.JSONDecodeError as e:
        return {"error": f"JSONパースエラー: {e}", "raw": raw}
    except Exception as e:
        return {"error": str(e)}


def generate_building_3d_html(building: dict, canvas_height: int = 620) -> str:
    """建物3DデータからThree.js インタラクティブHTMLを生成する。"""
    bj = json.dumps(building, ensure_ascii=False)

    html = """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  *{box-sizing:border-box;margin:0;padding:0}
  body{background:#12121e;overflow:hidden;font-family:sans-serif}
  #container{width:100%;position:relative}
  canvas{display:block}
  #info{position:absolute;top:10px;left:50%;transform:translateX(-50%);
    background:rgba(0,0,0,.72);color:#fff;padding:7px 18px;
    border-radius:20px;font-size:13px;pointer-events:none;white-space:nowrap;
    border:1px solid rgba(255,255,255,.15)}
  #popup{position:absolute;display:none;background:rgba(10,10,30,.95);color:#fff;
    padding:12px 18px;border-radius:10px;font-size:14px;
    border:1px solid #4af;pointer-events:none;min-width:160px;z-index:10}
  #popup .part{font-size:18px;font-weight:bold;color:#4af;margin-bottom:4px}
  #popup .dim{font-size:15px;color:#afa}
  #note{position:absolute;bottom:10px;left:10px;
    background:rgba(0,0,0,.6);color:#aaa;
    padding:6px 12px;border-radius:8px;font-size:11px;max-width:320px}
  #tbadge{position:absolute;top:10px;right:10px;
    background:rgba(0,80,160,.85);color:#7df;
    padding:5px 12px;border-radius:8px;font-size:12px}
</style>
</head>
<body>
<div id="container">
  <div id="info">🖱 ドラッグ: 回転  ホイール: ズーム  部位クリック: 詳細</div>
  <div id="tbadge"></div>
  <div id="popup"><div class="part" id="p-part"></div><div class="dim" id="p-dim"></div></div>
  <div id="note"></div>
</div>
<script src="https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js"></script>
<script>
const BUILDING=BLDG_JSON;
const CH=CANVAS_H;
const container=document.getElementById('container');
container.style.height=CH+'px';
const W=container.clientWidth||window.innerWidth||800,H=CH;
const renderer=new THREE.WebGLRenderer({antialias:true});
renderer.setSize(W,H);renderer.setPixelRatio(Math.min(devicePixelRatio,2));
renderer.shadowMap.enabled=true;
container.appendChild(renderer.domElement);
const scene=new THREE.Scene();
scene.background=new THREE.Color(0x12121e);
const camera=new THREE.PerspectiveCamera(45,W/H,0.1,500);
let theta=-0.6,phi=1.1,radius=22;
const target=new THREE.Vector3(0,2,0);
function upCam(){
  camera.position.set(
    target.x+radius*Math.sin(phi)*Math.sin(theta),
    target.y+radius*Math.cos(phi),
    target.z+radius*Math.sin(phi)*Math.cos(theta));
  camera.lookAt(target);}
upCam();
scene.add(new THREE.AmbientLight(0xffffff,0.55));
const dl=new THREE.DirectionalLight(0xfff8e7,0.9);
dl.position.set(10,20,10);dl.castShadow=true;scene.add(dl);
const fl=new THREE.DirectionalLight(0xc8d8ff,0.3);
fl.position.set(-10,5,-10);scene.add(fl);
scene.add(new THREE.GridHelper(40,20,0x334,0x223));
const clickable=[];
function addBox(x,y,z,w,h,d,color,label,dimText){
  const geo=new THREE.BoxGeometry(w,h,d);
  const col=parseInt(color.replace('#',''),16);
  const mat=new THREE.MeshLambertMaterial({color:col,transparent:true,opacity:0.88,side:THREE.DoubleSide});
  const mesh=new THREE.Mesh(geo,mat);
  mesh.position.set(x+w/2,y+h/2,z+d/2);
  mesh.castShadow=true;mesh.receiveShadow=true;
  mesh.userData={label,dimText};
  scene.add(mesh);
  const edges=new THREE.EdgesGeometry(geo);
  mesh.add(new THREE.LineSegments(edges,new THREE.LineBasicMaterial({color:0xffffff,transparent:true,opacity:0.2})));
  clickable.push(mesh);return mesh;}
const dim=BUILDING.dimensions||{};
const _BW=dim.total_width||10,_BD=dim.total_depth||8,_EH=dim.eave_height||3,_RH=dim.ridge_height||6;
const BW=Math.min(_BW,40),BD=Math.min(_BD,40);
const EH=Math.min(Math.max(_EH,2.0),8.0);
const RH=Math.min(Math.max(_RH,EH+0.5),EH+5.0);
const OX=-BW/2,OZ=-BD/2;
const walls=BUILDING.walls||[];
if(walls.length===0){
  const wc='#c8b89a';
  addBox(OX,0,OZ,BW,EH,0.2,wc,'南壁','幅'+BW+'m × 高'+EH+'m');
  addBox(OX,0,OZ+BD-0.2,BW,EH,0.2,wc,'北壁','幅'+BW+'m × 高'+EH+'m');
  addBox(OX,0,OZ,0.2,EH,BD,wc,'西壁','奥行'+BD+'m × 高'+EH+'m');
  addBox(OX+BW-0.2,0,OZ,0.2,EH,BD,wc,'東壁','奥行'+BD+'m × 高'+EH+'m');
}else{
  walls.forEach(w=>{
    const wc=w.color||'#c8b89a';
    addBox(OX+(w.x||0),w.z||0,OZ+(w.y||0),w.width||BW,w.height||EH,w.depth||0.2,wc,w.label||'壁',
      '幅'+(w.width||0).toFixed(1)+'m × 高'+(w.height||0).toFixed(1)+'m');});}
const floors=BUILDING.floors||[];
if(floors.length===0){addBox(OX,-0.3,OZ,BW,0.3,BD,'#888888','基礎',BW+'m × '+BD+'m');}
else{floors.forEach(f=>{addBox(OX+(f.x||0),(f.z||-0.3),OZ+(f.y||0),f.width||BW,f.height||0.3,f.depth||BD,'#888888',f.label||'基礎','');});}  // 色はGPT任せにせず固定
const roof=BUILDING.roof||{};
const rEH=roof.eave_height||EH;const _rRH_raw=roof.ridge_height||RH;const rRH=_rRH_raw>rEH?_rRH_raw:rEH+2.5;const rtype=roof.type||'切妻';
if(rtype==='陸屋根'){addBox(OX-0.2,rEH,OZ-0.2,BW+0.4,0.3,BD+0.4,'#666666','屋根（陸屋根）',BW+'m × '+BD+'m');}
else{
  const matR=new THREE.MeshLambertMaterial({color:0x445566,side:THREE.DoubleSide});
  const matG=new THREE.MeshLambertMaterial({color:0x334455,side:THREE.DoubleSide});
  const addQuad=(p1,p2,p3,p4,label,dimT,mat)=>{
    const geo=new THREE.BufferGeometry();
    const v=new Float32Array([
      p1[0],p1[1],p1[2], p2[0],p2[1],p2[2], p3[0],p3[1],p3[2],
      p1[0],p1[1],p1[2], p3[0],p3[1],p3[2], p4[0],p4[1],p4[2]]);
    geo.setAttribute('position',new THREE.BufferAttribute(v,3));
    geo.computeVertexNormals();
    const m=new THREE.Mesh(geo,mat||matR);
    m.userData={label:label||'屋根',dimText:dimT||''};
    scene.add(m);clickable.push(m);};
  const addTri3=(p1,p2,p3,mat)=>{
    const geo=new THREE.BufferGeometry();
    geo.setAttribute('position',new THREE.BufferAttribute(new Float32Array([p1[0],p1[1],p1[2],p2[0],p2[1],p2[2],p3[0],p3[1],p3[2]]),3));
    geo.computeVertexNormals();
    scene.add(new THREE.Mesh(geo,mat||matG));};
  const roofLabel='屋根（'+rtype+'）',roofDim='軒高'+rEH+'m 棟高'+rRH+'m';
  const midZ=OZ+BD/2,midX=OX+BW/2;
  if(rtype==='片流れ'){
    // 片流れ: 南軒低・北軒高の1面スロープ
    addQuad([OX,rEH,OZ],[OX+BW,rEH,OZ],[OX+BW,rRH,OZ+BD],[OX,rRH,OZ+BD],roofLabel,roofDim);
    // 東西の台形妻面
    addQuad([OX,rEH,OZ],[OX,rEH,OZ+BD],[OX,rRH,OZ+BD],[OX,rEH,OZ],'妻面（西）','',matG);
    addQuad([OX+BW,rEH,OZ],[OX+BW,rRH,OZ+BD],[OX+BW,rEH,OZ+BD],[OX+BW,rEH,OZ],'妻面（東）','',matG);
  } else if(rtype==='寄棟'){
    // 寄棟: 南北スロープ（台形）+ 東西スロープ（三角形）+ 棟（短い中央ライン）
    const ridgeX1=OX+BW*0.25,ridgeX2=OX+BW*0.75;
    // 南スロープ（台形）
    addQuad([OX,rEH,OZ],[OX+BW,rEH,OZ],[ridgeX2,rRH,midZ],[ridgeX1,rRH,midZ],roofLabel,roofDim);
    // 北スロープ（台形）
    addQuad([ridgeX1,rRH,midZ],[ridgeX2,rRH,midZ],[OX+BW,rEH,OZ+BD],[OX,rEH,OZ+BD],roofLabel,roofDim);
    // 西スロープ（三角形）
    addTri3([OX,rEH,OZ],[OX,rEH,OZ+BD],[ridgeX1,rRH,midZ],matG);
    // 東スロープ（三角形）
    addTri3([OX+BW,rEH,OZ],[ridgeX2,rRH,midZ],[OX+BW,rEH,OZ+BD],matG);
  } else {
    // 切妻（デフォルト）: 南北スロープ + 東西妻面
    addQuad([OX,rEH,OZ],[OX+BW,rEH,OZ],[OX+BW,rRH,midZ],[OX,rRH,midZ],roofLabel,roofDim);
    addQuad([OX,rRH,midZ],[OX+BW,rRH,midZ],[OX+BW,rEH,OZ+BD],[OX,rEH,OZ+BD],roofLabel,roofDim);
    addTri3([OX,rEH,OZ],[OX,rEH,OZ+BD],[OX,rRH,midZ],matG);
    addTri3([OX+BW,rEH,OZ],[OX+BW,rRH,midZ],[OX+BW,rEH,OZ+BD],matG);
  }}
const openings=BUILDING.openings||[];
openings.forEach(op=>{
  const col=op.type==='窓'?0x88ccff:op.type==='ドア'?0x886644:0x44aa88;
  const geo=new THREE.PlaneGeometry(op.width||1,op.height||1);
  const mat=new THREE.MeshBasicMaterial({color:col,transparent:true,opacity:0.65,side:THREE.DoubleSide});
  const m=new THREE.Mesh(geo,mat);
  m.position.set(OX+(op.x||0)+(op.width||1)/2,(op.z||0)+(op.height||1)/2,OZ+(op.y||0)+0.05);
  m.userData={label:op.type||'開口部',dimText:'幅'+(op.width||0)+'m × 高'+(op.height||0)+'m'};
  scene.add(m);clickable.push(m);});
document.getElementById('tbadge').textContent=BUILDING.building_type||'';
document.getElementById('note').textContent=BUILDING.note||'';
const ray=new THREE.Raycaster(),m2=new THREE.Vector2();
const popup=document.getElementById('popup');
let dsx=0,dsy=0;
container.addEventListener('click',e=>{
  if(Math.abs(e.clientX-dsx)>6||Math.abs(e.clientY-dsy)>6)return;
  const r=container.getBoundingClientRect();
  m2.x=((e.clientX-r.left)/r.width)*2-1;
  m2.y=-((e.clientY-r.top)/r.height)*2+1;
  ray.setFromCamera(m2,camera);
  const hits=ray.intersectObjects(clickable);
  if(hits.length>0){
    const ud=hits[0].object.userData;
    document.getElementById('p-part').textContent=ud.label||'';
    document.getElementById('p-dim').textContent=ud.dimText||'';
    popup.style.display='block';
    popup.style.left=Math.min(e.clientX+14,W-180)+'px';
    popup.style.top=Math.max(e.clientY-20,5)+'px';
  }else{popup.style.display='none';}});
let drag=false,px=0,py=0;
container.addEventListener('mousedown',e=>{drag=true;dsx=px=e.clientX;dsy=py=e.clientY;});
window.addEventListener('mouseup',()=>drag=false);
window.addEventListener('mousemove',e=>{
  if(!drag)return;
  theta-=(e.clientX-px)*0.012;
  phi=Math.max(0.15,Math.min(Math.PI*0.48,phi-(e.clientY-py)*0.012));
  px=e.clientX;py=e.clientY;upCam();});
container.addEventListener('wheel',e=>{
  radius=Math.max(3,Math.min(80,radius+e.deltaY*0.04));upCam();e.preventDefault();},{passive:false});
window.addEventListener('resize',()=>{
  const nw=container.clientWidth,nh=container.clientHeight;
  camera.aspect=nw/nh;camera.updateProjectionMatrix();renderer.setSize(nw,nh);});
(function animate(){requestAnimationFrame(animate);renderer.render(scene,camera);})();
</script></body></html>"""

    html = html.replace("BLDG_JSON", bj).replace("CANVAS_H", str(canvas_height))
    return html
