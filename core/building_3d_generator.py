"""
building_3d_generator.py
GPT-4o Vision で図面を解析して建物の3D形状を推定し、
Three.js インタラクティブHTMLを生成する。
"""
import base64
import json


_SYSTEM_PROMPT = """あなたは建築図面を読み取る専門家です。
建築平面図・立面図・矩計図を解析し、建物の3D形状データをJSONで返します。
JSONのみを返し、説明文は一切含めないでください。"""

_USER_PROMPT = """この建築図面（主に平面図）を解析して、建物の3D形状を推定してください。

以下のJSON形式で返してください（数値単位はすべてメートル）:

{
  "building_type": "平面図 or 立面図 or 不明",
  "note": "縮尺・推定根拠のメモ（日本語）",
  "dimensions": {
    "total_width": 数値（建物の幅。南面・北面の長さ）,
    "total_depth": 数値（建物の奥行き。東面・西面の長さ）,
    "eave_height": 数値（軒高。平屋=2.8m、2階建て=6.0m）,
    "ridge_height": 数値（棟高。軒高+屋根高さ）
  },
  "eave_overhang": 数値（軒の出。日本住宅の標準=0.6m。図面から読み取れれば正確な値を使用）,
  "stories": [
    {"label": "1F", "floor_height": 数値（1階天井高さm）},
    {"label": "2F", "floor_height": 数値（2階天井高さm＝軒高-0.5m程度）}
  ],
  "walls": [
    {"label": "南壁", "x": 0, "y": 0, "z": 0, "width": 数値, "height": 数値, "depth": 0.2},
    {"label": "北壁", "x": 0, "y": 奥行き, "z": 0, "width": 数値, "height": 数値, "depth": 0.2},
    {"label": "西壁", "x": 0, "y": 0, "z": 0, "width": 0.2, "height": 数値, "depth": 奥行き},
    {"label": "東壁", "x": 幅, "y": 0, "z": 0, "width": 0.2, "height": 数値, "depth": 奥行き}
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
      "y": 0（南壁の場合。北壁=奥行き値）,
      "z": 数値（床面からの高さm。腰窓=0.9、掃出窓=0、ドア=0、2階窓=3.5）,
      "width": 数値（開口幅m）,
      "height": 数値（開口高さm）
    }
  ],
  "floors": [
    {"label": "基礎", "x": 0, "y": 0, "z": -0.3, "width": 幅, "depth": 奥行き, "height": 0.3}
  ]
}

【平面図の読み方】
- 外壁の外側寸法を total_width / total_depth とする
- 寸法数字（例: 9100, 7200）はmm単位のことが多い → mに換算（÷1000）
- 開口部（窓・ドア）は壁の切れ目として読み取る
- 平面図の形状から屋根タイプを推定: 長方形→寄棟or切妻、傾斜線あり→寄棟

【屋根タイプの判断】
- 三角断面が見える立面図 → 切妻
- 四方に傾斜 / 平面図が多角形 → 寄棟
- 1面のみ傾斜 → 片流れ
- 平面図で屋上テラス → 陸屋根

ルール:
- 図面に寸法値があれば必ずその値を使う（mmはmに換算）
- 図面に寸法がなければ: 2階建て幅10m奥行8m軒高6.0m棟高8.5mで推定
- walls は必ず南北東西の4面を記述
- eave_overhang: 図面に軒出寸法があれば使用、なければ0.6
- stories: 2階建て→2要素、平屋→空配列[]
- JSONのみ返すこと（説明文不要）
"""


def analyze_drawing_3d(img_bytes: bytes, api_key: str) -> dict:
    """
    GPT-4o Vision で図面を解析して建物3Dデータを返す。
    Returns: dict（エラー時は {"error": "...", "_raw_gpt_response": "..."} ）
    """
    raw = ""
    finish_reason = ""
    try:
        from openai import OpenAI
        from core.logger import log_gpt_call, log_error
        if img_bytes is None:
            return {"error": "図面画像がありません（drawing_raw_bytesがNone）", "_raw_gpt_response": ""}
        client = OpenAI(api_key=api_key)
        img_mime = "image/png"
        try:
            from PIL import Image as _PILImg
            import io as _io_inner
            _pil = _PILImg.open(_io_inner.BytesIO(img_bytes)).convert("RGB")
            w, h = _pil.size
            if max(w, h) > 1500:
                scale = 1500 / max(w, h)
                _pil = _pil.resize((int(w * scale), int(h * scale)))
            _jbuf = _io_inner.BytesIO()
            _pil.save(_jbuf, format="JPEG", quality=88)
            img_clean = _jbuf.getvalue()
            img_mime = "image/jpeg"
        except Exception:
            img_clean = img_bytes
        b64 = base64.b64encode(img_clean).decode("utf-8")
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": _USER_PROMPT},
                        {"type": "image_url", "image_url": {"url": f"data:{img_mime};base64,{b64}", "detail": "high"}},
                    ],
                },
            ],
            max_tokens=4000,
            temperature=0.2,
        )
        finish_reason = response.choices[0].finish_reason or ""
        raw_content = response.choices[0].message.content
        raw = (raw_content or "").strip()
        _raw_for_log = f"[finish_reason={finish_reason}] {raw}"

        log_gpt_call(
            func_name="building_3d_generator.analyze_drawing_3d",
            model="gpt-4o",
            system_prompt=_SYSTEM_PROMPT[:200],
            user_message_summary="図面画像 + 3D形状JSON生成プロンプト",
            response_text=raw,
            tokens_prompt=response.usage.prompt_tokens if response.usage else None,
            tokens_completion=response.usage.completion_tokens if response.usage else None,
            tokens_total=response.usage.total_tokens if response.usage else None,
        )

        if not raw:
            default = {
                "building_type": "不明（GPT空応答）",
                "note": f"GPTが空の応答を返しました(finish_reason={finish_reason})。デフォルト値を使用。",
                "dimensions": {"total_width": 10, "total_depth": 8, "eave_height": 5.5, "ridge_height": 8.0},
                "eave_overhang": 0.6,
                "stories": [{"label": "1F", "floor_height": 2.4}],
                "walls": [
                    {"label": "南壁", "x": 0, "y": 0, "z": 0, "width": 10, "height": 5.5, "depth": 0.2},
                    {"label": "北壁", "x": 0, "y": 8, "z": 0, "width": 10, "height": 5.5, "depth": 0.2},
                    {"label": "西壁", "x": 0, "y": 0, "z": 0, "width": 0.2, "height": 5.5, "depth": 8},
                    {"label": "東壁", "x": 10, "y": 0, "z": 0, "width": 0.2, "height": 5.5, "depth": 8},
                ],
                "roof": {"type": "寄棟", "eave_height": 5.5, "ridge_height": 8.0},
                "openings": _faces_to_openings(faces or {}, total_width, total_depth, eave_height),
                "floors": [{"label": "基礎", "x": 0, "y": 0, "z": -0.3, "width": 10, "depth": 8, "height": 0.3}],
                "_raw_gpt_response": _raw_for_log,
                "_pipeline": "direct_fallback",
            }
            return default

        if raw.startswith("```"):
            parts = raw.split("```")
            raw = parts[1] if len(parts) > 1 else raw
            if raw.startswith("json"):
                raw = raw[4:]
        result = json.loads(raw.strip())
        result["_raw_gpt_response"] = _raw_for_log
        return result
    except json.JSONDecodeError as e:
        log_error("JSONパースエラー: building_3d_generator.analyze_drawing_3d", e, "GPT")
        return {"error": f"JSONパースエラー: {e}\nfinish_reason={finish_reason}\nraw={repr(raw[:200])}", "_raw_gpt_response": raw}
    except Exception as e:
        log_error("エラー: building_3d_generator.analyze_drawing_3d", e, "GPT")
        return {"error": f"{type(e).__name__}: {e}", "_raw_gpt_response": raw}




def _faces_to_openings(faces: dict, bw: float, bd: float, eave_h: float) -> list:
    """
    GPTが返した faces dict (南/北/東/西) から 3D用 openings リストを生成する。
    各面の窓・ドアを均等分布で配置。位置は近似（図面から正確な座標は取得しない）。
    """
    openings = []
    face_cfgs = {
        "south": {"wall": "south", "span": bw},
        "north": {"wall": "north", "span": bw},
        "east":  {"wall": "east",  "span": bd},
        "west":  {"wall": "west",  "span": bd},
    }
    for face_name, cfg in face_cfgs.items():
        face_data = faces.get(face_name)
        if not face_data or not isinstance(face_data, dict):
            continue
        ops = face_data.get("openings") or []
        if not ops:
            continue
        span = cfg["span"]
        n = len(ops)
        spacing = span / (n + 1)
        for i, op in enumerate(ops):
            ow = float(op.get("width") or 1.0)
            oh = float(op.get("height") or 1.2)
            op_type = op.get("type", "窓")
            # 高さ: ドアは地面から、窓は軒高の約40%
            oz = 0.1 if op_type == "ドア" else round(eave_h * 0.40, 2)
            # 平面図から正確なx_from_leftがあればそれを優先、なければ均等分布
            if op.get("x_from_left") is not None:
                pos = round(float(op["x_from_left"]), 2)
            else:
                pos = round(spacing * (i + 1) - ow / 2, 2)
            openings.append({
                "face":   face_name,
                "x":      pos,          # 面の左端からのオフセット
                "z":      oz,           # 地面からの高さ
                "width":  round(ow, 2),
                "height": round(oh, 2),
                "type":   op_type,
            })
    return openings


def build_3d_from_annotations(annotations: list, roof_type: str = "寄棟", faces: dict = None) -> dict:
    """
    DrawingAnalyzerが抽出したannotationsから建物3Dデータを構築する。
    GPTへの追加APIコール不要。STEP2の正確な抽出値を使用。
    """
    if not annotations:
        return {"error": "DrawingAnalyzerの解析データがありません。先にSTEP2の図面解析を実行してください。"}

    widths  = [a for a in annotations if a.get("category") == "width"]
    heights = [a for a in annotations if a.get("category") == "height"]

    def _val(items, *keywords):
        for kw in keywords:
            for item in items:
                lbl = item.get("label", "")
                if kw in lbl:
                    try:
                        return float(item["value"])
                    except Exception:
                        pass
        return None

    total_width = _val(widths, "南面幅", "南", "幅")
    total_depth = _val(widths, "東面幅", "西面幅", "北面幅", "奥行")
    if total_width is None and widths:
        try:
            total_width = max(float(w.get("value", 0) or 0) for w in widths)
        except Exception:
            pass
    total_width = total_width or 10.0
    total_depth = total_depth or round(total_width * 0.8, 2)

    eave_height  = _val(heights, "軒高", "eave") or 5.5
    ridge_height = _val(heights, "棟高", "ridge")
    if ridge_height is None or ridge_height <= eave_height:
        ridge_height = round(eave_height + 3.0, 2)

    # 1F天井高（annotationsに記載があれば使用、なければ推定）
    floor1_h = _val(heights, "1F", "1階天井", "天井高") or round(eave_height * 0.55, 2)
    stories = [
        {"label": "1F", "floor_height": floor1_h},
    ] if eave_height > 4.0 else []  # 2階建ての場合のみ

    note_parts = []
    for a in (widths + heights):
        note_parts.append(f"{a.get('label','')}={a.get('value','')}{a.get('unit','m')}")
    note = "DrawingAnalyzer抽出値: " + " / ".join(note_parts[:6])

    return {
        "building_type": "立面図",
        "note": note,
        "dimensions": {
            "total_width":   total_width,
            "total_depth":   total_depth,
            "eave_height":   eave_height,
            "ridge_height":  ridge_height,
        },
        "eave_overhang": 0.6,
        "stories": stories,
        "walls": [
            {"label": "南壁", "x": 0,           "y": 0,           "z": 0, "width": total_width, "height": eave_height, "depth": 0.2},
            {"label": "北壁", "x": 0,           "y": total_depth, "z": 0, "width": total_width, "height": eave_height, "depth": 0.2},
            {"label": "西壁", "x": 0,           "y": 0,           "z": 0, "width": 0.2,         "height": eave_height, "depth": total_depth},
            {"label": "東壁", "x": total_width, "y": 0,           "z": 0, "width": 0.2,         "height": eave_height, "depth": total_depth},
        ],
        "roof": {
            "type":         roof_type,
            "eave_height":  eave_height,
            "ridge_height": ridge_height,
        },
        "openings": [],
        "floors": [
            {"label": "基礎", "x": 0, "y": 0, "z": -0.3, "width": total_width, "depth": total_depth, "height": 0.3}
        ],
        "_pipeline":          "annotations_v1",
        "_raw_gpt_response":  f"DrawingAnalyzer annotations ({len(annotations)}件): {note}",
    }


def generate_building_3d_html(building: dict, canvas_height: int = 620) -> str:
    """建物3DデータからThree.js インタラクティブHTMLを生成する。"""
    bj = json.dumps(building, ensure_ascii=False)

    html = r"""<!DOCTYPE html>
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
    padding:6px 12px;border-radius:8px;font-size:11px;max-width:360px}
  #tbadge{position:absolute;top:10px;right:10px;
    background:rgba(0,80,160,.85);color:#7df;
    padding:5px 12px;border-radius:8px;font-size:12px}
</style>
</head>
<body>
<div id="container">
  <div id="info">&#x1F5B1; ドラッグ: 回転  ホイール: ズーム  部位クリック: 詳細</div>
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
  if(w<=0||h<=0||d<=0)return null;
  const geo=new THREE.BoxGeometry(w,h,d);
  const col=parseInt((color||'#888888').replace('#',''),16);
  const mat=new THREE.MeshLambertMaterial({color:col,side:THREE.FrontSide});
  const mesh=new THREE.Mesh(geo,mat);
  mesh.position.set(x+w/2,y+h/2,z+d/2);
  mesh.castShadow=true;mesh.receiveShadow=true;
  mesh.userData={label:label||'',dimText:dimText||''};
  scene.add(mesh);
  if(label){
    const edges=new THREE.EdgesGeometry(geo);
    // edges removed: walls are opaque, edge lines not needed
    clickable.push(mesh);
  }
  return mesh;}
const dim=BUILDING.dimensions||{};
const _BW=dim.total_width||10,_BD=dim.total_depth||8,_EH=dim.eave_height||5.5,_RH=dim.ridge_height||8;
const BW=Math.min(Math.max(_BW,2),40),BD=Math.min(Math.max(_BD,2),40);
const EH=Math.min(Math.max(_EH,2.0),8.0);
const RH=Math.min(Math.max(_RH,EH+0.5),EH+6.0);
const OH=Math.min(Math.max(BUILDING.eave_overhang||0.6,0.2),1.5);
const OX=-BW/2,OZ=-BD/2;
// 外壁
const walls=BUILDING.walls||[];
if(walls.length===0){
  addBox(OX,0,OZ,BW,EH,0.2,'#c8b89a','南壁','幅'+BW+'m × 高'+EH+'m');
  addBox(OX,0,OZ+BD-0.2,BW,EH,0.2,'#c8b89a','北壁','幅'+BW+'m × 高'+EH+'m');
  addBox(OX,0,OZ+0.2,0.2,EH,BD-0.4,'#c0b090','西壁','奥行'+BD+'m × 高'+EH+'m');
  addBox(OX+BW-0.2,0,OZ+0.2,0.2,EH,BD-0.4,'#c0b090','東壁','奥行'+BD+'m × 高'+EH+'m');
}else{
  walls.forEach(w=>{
    addBox(OX+(w.x||0),w.z||0,OZ+(w.y||0),w.width||BW,w.height||EH,w.depth||0.2,
      w.color||'#c8b89a',w.label||'壁','幅'+(w.width||0).toFixed(1)+'m × 高'+(w.height||0).toFixed(1)+'m');});}
// 基礎・床
const floors=BUILDING.floors||[];
if(floors.length===0){addBox(OX,-0.3,OZ,BW,0.3,BD,'#888888','基礎',BW+'m × '+BD+'m');}
else{floors.forEach(f=>{addBox(OX+(f.x||0),(f.z||-0.3),OZ+(f.y||0),f.width||BW,f.height||0.3,f.depth||BD,'#888888',f.label||'基礎','');});}
// 階境（1F/2F区切り帯）
const stories=BUILDING.stories||[];
stories.forEach(s=>{
  const sh=parseFloat(s.floor_height||s.height||0);
  if(sh>0.5&&sh<EH-0.1){
    addBox(OX-0.05,sh,OZ-0.05,BW+0.1,0.1,BD+0.1,'#9a8870',s.label||'階境','高さ'+sh.toFixed(2)+'m');
  }
});
// 屋根
const roof=BUILDING.roof||{};
const rEH=Math.min(Math.max(roof.eave_height||EH,2),8);
const _rRH_raw=roof.ridge_height||RH;
const rRH=_rRH_raw>rEH?_rRH_raw:rEH+2.5;
const rtype=roof.type||'寄棟';
if(rtype==='陸屋根'){
  addBox(OX-OH,rEH,OZ-OH,BW+OH*2,0.3,BD+OH*2,'#666666','屋根（陸屋根）',BW+'m × '+BD+'m');
}else{
  const matR=new THREE.MeshLambertMaterial({color:0x3a4d5c,side:THREE.DoubleSide});
  const matG=new THREE.MeshLambertMaterial({color:0x2d3d4a,side:THREE.DoubleSide});
  const addQuad=(p1,p2,p3,p4,label,dimT,mat)=>{
    const geo=new THREE.BufferGeometry();
    const v=new Float32Array([
      p1[0],p1[1],p1[2], p2[0],p2[1],p2[2], p3[0],p3[1],p3[2],
      p1[0],p1[1],p1[2], p3[0],p3[1],p3[2], p4[0],p4[1],p4[2]]);
    geo.setAttribute('position',new THREE.BufferAttribute(v,3));
    geo.computeVertexNormals();
    const m=new THREE.Mesh(geo,mat||matR);
    m.userData={label:label||'屋根',dimText:dimT||''};
    scene.add(m);if(label)clickable.push(m);};
  const addTri3=(p1,p2,p3,mat)=>{
    const geo=new THREE.BufferGeometry();
    geo.setAttribute('position',new THREE.BufferAttribute(new Float32Array([p1[0],p1[1],p1[2],p2[0],p2[1],p2[2],p3[0],p3[1],p3[2]]),3));
    geo.computeVertexNormals();
    scene.add(new THREE.Mesh(geo,mat||matG));};
  const roofLabel='屋根（'+rtype+'）',roofDim='軒高'+rEH+'m 棟高'+rRH+'m 軒の出'+OH+'m';
  const midZ=OZ+BD/2,midX=OX+BW/2;
  if(rtype==='片流れ'){
    addQuad([OX-OH,rEH,OZ-OH],[OX+BW+OH,rEH,OZ-OH],[OX+BW+OH,rRH,OZ+BD+OH],[OX-OH,rRH,OZ+BD+OH],roofLabel,roofDim);
    addTri3([OX-OH,rEH,OZ-OH],[OX-OH,rEH,OZ+BD+OH],[OX-OH,rRH,OZ+BD+OH],matG);
    addTri3([OX+BW+OH,rEH,OZ-OH],[OX+BW+OH,rRH,OZ+BD+OH],[OX+BW+OH,rEH,OZ+BD+OH],matG);
  }else if(rtype==='寄棟'){
    const ridgeX1=OX+BW*0.25,ridgeX2=OX+BW*0.75;
    addQuad([OX-OH,rEH,OZ-OH],[OX+BW+OH,rEH,OZ-OH],[ridgeX2,rRH,midZ],[ridgeX1,rRH,midZ],roofLabel,roofDim);
    addQuad([ridgeX1,rRH,midZ],[ridgeX2,rRH,midZ],[OX+BW+OH,rEH,OZ+BD+OH],[OX-OH,rEH,OZ+BD+OH],roofLabel,roofDim);
    addTri3([OX-OH,rEH,OZ-OH],[OX-OH,rEH,OZ+BD+OH],[ridgeX1,rRH,midZ],matG);
    addTri3([OX+BW+OH,rEH,OZ-OH],[ridgeX2,rRH,midZ],[OX+BW+OH,rEH,OZ+BD+OH],matG);
  }else{
    addQuad([OX-OH,rEH,OZ-OH],[OX+BW+OH,rEH,OZ-OH],[OX+BW+OH,rRH,midZ],[OX-OH,rRH,midZ],roofLabel,roofDim);
    addQuad([OX-OH,rRH,midZ],[OX+BW+OH,rRH,midZ],[OX+BW+OH,rEH,OZ+BD+OH],[OX-OH,rEH,OZ+BD+OH],roofLabel,roofDim);
    addTri3([OX-OH,rEH,OZ-OH],[OX-OH,rEH,OZ+BD+OH],[OX-OH,rRH,midZ],matG);
    addTri3([OX+BW+OH,rEH,OZ-OH],[OX+BW+OH,rRH,midZ],[OX+BW+OH,rEH,OZ+BD+OH],matG);
  }
  // 軒天（軒裏）
  addBox(OX-OH,rEH-0.06,OZ-OH,BW+OH*2,0.06,OH,'#d4c8b0','軒天（南）','');
  addBox(OX-OH,rEH-0.06,OZ+BD,BW+OH*2,0.06,OH,'#d4c8b0','軒天（北）','');
  addBox(OX-OH,rEH-0.06,OZ,OH,0.06,BD,'#d4c8b0','軒天（西）','');
  addBox(OX+BW,rEH-0.06,OZ,OH,0.06,BD,'#d4c8b0','軒天（東）','');
  // 鼻隠し（破風・fascia）
  addBox(OX-OH,rEH-0.32,OZ-OH-0.05,BW+OH*2,0.28,0.05,'#7a6345','鼻隠し（南）','');
  addBox(OX-OH,rEH-0.32,OZ+BD+OH,BW+OH*2,0.28,0.05,'#7a6345','鼻隠し（北）','');
  addBox(OX-OH-0.05,rEH-0.32,OZ-OH,0.05,0.28,BD+OH*2,'#7a6345','鼻隠し（西）','');
  addBox(OX+BW+OH,rEH-0.32,OZ-OH,0.05,0.28,BD+OH*2,'#7a6345','鼻隠し（東）','');
}
// 開口部（窓枠+ガラス）各面対応
const openings=BUILDING.openings||[];
const FW=0.07,GT=0.12;  // FW=枠幅, GT=ガラス厚
const glassMat=new THREE.MeshBasicMaterial({color:0x88ccff,transparent:true,opacity:0.38,side:THREE.DoubleSide});
function addGlassBox(x,y,z,w,h,d,label,dim){
  const geo=new THREE.BoxGeometry(w,h,d);
  const m=new THREE.Mesh(geo,glassMat);
  m.position.set(x+w/2,y+h/2,z+d/2);
  m.userData={label:label||'窓',dimText:dim||''};
  scene.add(m);clickable.push(m);}
openings.forEach(op=>{
  const face=op.face||'south';
  const ow=Math.max(op.width||1,0.3),oh_=Math.max(op.height||1.2,0.3);
  const oz_=op.z||1.5;
  const fc=op.type==='窓'?'#b0b8c8':op.type==='ドア'?'#8b7355':'#6a9a7a';
  const dimT='幅'+ow.toFixed(1)+'m × 高'+oh_.toFixed(1)+'m';
  const pos=op.x||0;  // 面の左端からのオフセット
  if(face==='south'){
    // 南壁: z=OZ, X方向にpx展開
    const px=OX+pos;
    addGlassBox(px,oz_,OZ-GT/2,ow,oh_,GT,op.type,dimT);
    addBox(px-FW,oz_-FW,OZ-0.08,ow+FW*2,FW,0.07,fc,'','');
    addBox(px-FW,oz_+oh_,OZ-0.08,ow+FW*2,FW,0.07,fc,'','');
    addBox(px-FW,oz_,OZ-0.08,FW,oh_,0.07,fc,'','');
    addBox(px+ow,oz_,OZ-0.08,FW,oh_,0.07,fc,'','');
  }else if(face==='north'){
    const px=OX+pos;
    addGlassBox(px,oz_,OZ+BD-GT/2,ow,oh_,GT,op.type,dimT);
    addBox(px-FW,oz_-FW,OZ+BD+0.01,ow+FW*2,FW,0.07,fc,'','');
    addBox(px-FW,oz_+oh_,OZ+BD+0.01,ow+FW*2,FW,0.07,fc,'','');
    addBox(px-FW,oz_,OZ+BD+0.01,FW,oh_,0.07,fc,'','');
    addBox(px+ow,oz_,OZ+BD+0.01,FW,oh_,0.07,fc,'','');
  }else if(face==='east'){
    // 東壁: x=OX+BW, Z方向にpos展開（widthがZ方向）
    const pz=OZ+pos;
    addGlassBox(OX+BW-GT/2,oz_,pz,GT,oh_,ow,op.type,dimT);
    addBox(OX+BW+0.01,oz_-FW,pz-FW,0.07,FW,ow+FW*2,fc,'','');
    addBox(OX+BW+0.01,oz_+oh_,pz-FW,0.07,FW,ow+FW*2,fc,'','');
    addBox(OX+BW+0.01,oz_,pz-FW,0.07,oh_,FW,fc,'','');
    addBox(OX+BW+0.01,oz_,pz+ow,0.07,oh_,FW,fc,'','');
  }else if(face==='west'){
    const pz=OZ+pos;
    addGlassBox(OX-GT/2,oz_,pz,GT,oh_,ow,op.type,dimT);
    addBox(OX-0.08,oz_-FW,pz-FW,0.07,FW,ow+FW*2,fc,'','');
    addBox(OX-0.08,oz_+oh_,pz-FW,0.07,FW,ow+FW*2,fc,'','');
    addBox(OX-0.08,oz_,pz-FW,0.07,oh_,FW,fc,'','');
    addBox(OX-0.08,oz_,pz+ow,0.07,oh_,FW,fc,'','');
  }else{
    // フォールバック: 南壁扱い
    const px=OX+(op.x||0);
    addGlassBox(px,oz_,OZ-GT/2,ow,oh_,GT,op.type,dimT);
  }
});
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
