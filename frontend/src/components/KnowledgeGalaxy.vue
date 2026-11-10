<script setup>
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { Orbit, Maximize2, Sun, Moon, Expand } from '@lucide/vue'
import SearchField from './ui/SearchField.vue'
import { STYLE_PRESETS } from '../vendor/galaxy-view/render/stylePresets'
import { COLOR_THEMES } from '../vendor/galaxy-view/render/colorThemes'
import { seedPosition } from '../vendor/galaxy-view/data/seed'
import { TIERS } from '../vendor/galaxy-view/quality/tiers'

const props = defineProps({
 nodes:{type:Array,default:()=>[]},edges:{type:Array,default:()=>[]},chartTitle:{type:String,default:'课程知识星系'},
 showDetails:{type:Boolean,default:true},showRelationFilter:{type:Boolean,default:true},layoutMode:{type:String,default:'graph'},
 profileLayout:{type:Boolean,default:false},topicClusters:{type:Array,default:()=>[]},height:{type:Number,default:620},emptyText:{type:String,default:'暂无课程知识'},
})
const emit=defineEmits(['node-select','reset'])
const stage=ref(null),host=ref(null),query=ref(''),selected=ref(null),hovered=ref(-1),labels=ref([])
const ready=ref(false),failure=ref(''),rotate=ref(true),scope=ref('knowledge'),light=ref(false)
const relationFilter=ref('all'),focusOnly=ref(false),depth=ref(1),presetId=ref('deepfield'),colorMode=ref(props.profileLayout?'mastery':'topic')
const canvasHeight=computed(()=>Math.min(720,Math.max(580,props.height)))
const palette={mastered:{color:'#7fd0a0',name:'稳定掌握'},developing:{color:'#78b8e7',name:'正在形成'},weak:{color:'#ffc35c',name:'需要巩固'},conflict:{color:'#ec8f9a',name:'证据冲突'},unknown:{color:'#c1b7d6',name:'暂无证据'}}
const dataNodes=computed(()=>props.nodes.filter(n=>n.id&&n.name&&(scope.value==='all'||!['course','chapter','source'].includes(n.nodeType))))
const dataIds=computed(()=>new Set(dataNodes.value.map(n=>String(n.id))))
const dataEdges=computed(()=>props.edges.filter(e=>dataIds.value.has(String(e.source))&&dataIds.value.has(String(e.target))&&String(e.source)!==String(e.target)&&(relationFilter.value==='all'||e.relationType===relationFilter.value)))
const matches=computed(()=>query.value.trim()?dataNodes.value.filter(n=>n.name.toLowerCase().includes(query.value.trim().toLowerCase())).slice(0,8):[])
const currentPreset=computed(()=>STYLE_PRESETS.find(p=>p.id===presetId.value)||STYLE_PRESETS[0])
const topicKeys=computed(()=>[...new Set(dataNodes.value.map(topicKey))])
function topicKey(n){return n.chapterId||n.chapter?.id||n.chapter?.title||n.topicClusterIds?.[0]||n.categoryName||'课程知识'}
let renderer,director,layout,THREE,modules,observer,frame,lastTime=0,lastLabelUpdate=0,mounted=true
let graphData={nodes:[],links:[]},indexById=new Map(),firstNeighbors=new Set(),allNeighbors=new Set()
let graphCenter,graphRadius=200,pointerDown=null,removeEvents=()=>{}
const localMode=()=>focusOnly.value||props.layoutMode==='relationship_projection'
function colorsFor(node){
 if(colorMode.value==='mastery')return new THREE.Color((palette[node.masteryBand]||palette.unknown).color)
 const colors=COLOR_THEMES.find(t=>t.id===currentPreset.value.theme)?.colors||COLOR_THEMES[0].colors
 return new THREE.Color(colors[Math.max(0,topicKeys.value.indexOf(topicKey(node)))%colors.length])
}
function applyLook(){
 if(!renderer)return
 const p=currentPreset.value
 renderer.setColorFn(colorsFor);renderer.setSizeMode(p.look.sizeBy);renderer.setNodeScale(p.look.nodeSize*1.6)
 renderer.setBloomParams(p.bloom);renderer.setLinkCurve(p.look.linkCurve)
 renderer.setStarfieldEnabled(p.starfield);renderer.setSpace(p.space);renderer.twinkleFreq=p.look.twinkle
 renderer.applyTokens(light.value?{...modules.DAYLIGHT,background:0xfcfbf8}:modules.DEEP_SPACE,p.bloom.strength)
 renderer.setNebulaTint(COLOR_THEMES.find(t=>t.id===p.theme)?.colors[0]||'#46d4dc',COLOR_THEMES.find(t=>t.id===p.theme)?.colors[7]||'#9a7fe0')
 updateFocus()
}
function updateFocus(){
 if(!renderer)return
 firstNeighbors=new Set();allNeighbors=new Set()
 const idx=indexById.get(String(selected.value?.id))
 if(idx!=null){
  firstNeighbors.add(idx)
  graphData.links.forEach(e=>{if(e.source===idx)firstNeighbors.add(e.target);if(e.target===idx)firstNeighbors.add(e.source)})
  allNeighbors=new Set(firstNeighbors)
  if(depth.value===2)graphData.links.forEach(e=>{if(firstNeighbors.has(e.source))allNeighbors.add(e.target);if(firstNeighbors.has(e.target))allNeighbors.add(e.source)})
  const tier1=[],tier2=[]
  graphData.links.forEach((e,i)=>{if(e.source===idx||e.target===idx)tier1.push(i);else if(depth.value===2&&allNeighbors.has(e.source)&&allNeighbors.has(e.target))tier2.push(i)})
  renderer.setSelectedLinks(tier1,tier2)
  renderer.setFocus(i=>i===idx?1.5:firstNeighbors.has(i)?1:allNeighbors.has(i)?.5:localMode()?0:.09)
 }else{renderer.setSelectedLinks([],[]);renderer.setFocus(null)}
 renderer.setLinkOpacity(localMode()&&idx!=null?0:currentPreset.value.look.linkOpacity);lastLabelUpdate=0
}
function choose(node,move=true){
 const idx=indexById.get(String(node.id));if(idx==null)return
 selected.value=props.nodes.find(n=>String(n.id)===String(node.id));query.value='';hovered.value=-1
 emit('node-select',selected.value);updateFocus()
 if(move)director.flyTo(renderer.nodePosition(idx,new THREE.Vector3()),renderer.nodeRadius(idx),()=>director.beginFocusOrbit(null))
}
function searchFirst(){if(matches.value.length)choose(matches.value[0])}
function reset(){selected.value=null;focusOnly.value=false;query.value='';emit('node-select',null);emit('reset');updateFocus();director?.resetView(graphCenter,graphRadius)}
function fullscreen(){if(document.fullscreenElement)document.exitFullscreen();else stage.value.requestFullscreen()}
function loadData(){
 if(!renderer)return
 ready.value=false;labels.value=[]
 indexById=new Map(dataNodes.value.map((n,i)=>[String(n.id),i]))
 const nodes=dataNodes.value.map(n=>({...n,id:String(n.id),folderTop:topicKey(n),degree:0,inDegree:0,outDegree:0,fileSize:0,tags:[],unresolved:false,tag:false}))
 const links=dataEdges.value.map(e=>({...e,source:indexById.get(String(e.source)),target:indexById.get(String(e.target))}))
 links.forEach(e=>{nodes[e.source].degree++;nodes[e.source].outDegree++;nodes[e.target].degree++;nodes[e.target].inDegree++});graphData={nodes,links}
 const positions=new Float32Array(nodes.length*3);nodes.forEach((n,i)=>positions.set(seedPosition(n.id,200),i*3))
 const p=currentPreset.value.physics
 layout.init(graphData,positions,{charge:-p.repel,linkDistance:p.linkDistance,linkStrength:p.linkStrength,centerPull:p.centerPull,flatten:p.flatten,coreGravity:p.coreGravity,spiral:p.spiral,velocityDecay:.4})
 for(let i=0;i<310&&!layout.isSettled();i++)layout.step()
 renderer.setData(graphData,positions);applyLook();graphCenter=new THREE.Vector3()
 const points=nodes.map((_,i)=>renderer.nodePosition(i,new THREE.Vector3()))
 points.forEach(v=>graphCenter.add(v));graphCenter.divideScalar(Math.max(1,points.length));graphRadius=Math.max(80,...points.map(v=>v.distanceTo(graphCenter)))*.64
 director.setFramingElev(currentPreset.value.frameElevDeg||18);director.setInitialFraming(graphCenter,graphRadius)
 if(selected.value&&!indexById.has(String(selected.value.id))){selected.value=null;emit('node-select',null)}
 updateFocus();renderer.playReveal(1600);ready.value=true
}
function updateLabels(time){
 if(!renderer||time-lastLabelUpdate<90)return
 lastLabelUpdate=time
 const w=host.value.clientWidth,h=host.value.clientHeight,idx=indexById.get(String(selected.value?.id))
 const order=graphData.nodes.map((n,i)=>({n,i,score:(i===idx?10000:0)+(i===hovered.value?5000:0)+(firstNeighbors.has(i)?500:0)+n.degree})).sort((a,b)=>b.score-a.score)
 const shown=[]
 for(const {n,i} of order){
  const priority=i===idx||i===hovered.value
  if(idx!=null&&!allNeighbors.has(i)&&!priority)continue
  if(!priority&&(idx==null||shown.length>=7))continue
  const p=renderer.projectNode(i,w,h),width=Math.min(280,n.name.length*15+28),height=n.name.length>16?50:31
  let x=p.x+14,y=p.y-height/2
  if(x+width>w-18)x=p.x-width-14
  if(p.behind||x<12||y<110||y+height>h-84)continue
  if(shown.some(l=>x<l.x+l.w+8&&x+width>l.x-8&&y<l.y+l.h+8&&y+height>l.y-8))continue
  shown.push({id:n.id,name:n.name,x,y,w:width,h:height,active:i===idx,color:renderer.nodeColorHex(i)})
 }
 labels.value=shown
 const pos=renderer.camera.position
 host.value.__galaxyEvidence={nodeCount:graphData.nodes.length,edgeCount:graphData.links.length,labelCount:shown.length,labelBounds:shown.map(l=>({x:l.x,y:l.y,w:l.w,h:l.h})),selectedId:selected.value?.id||null,layout:'galaxy-view-native-three',settled:ready.value&&!renderer.revealing,preset:presetId.value,light:light.value,drawCalls:renderer.drawCalls,camera:{x:pos.x,y:pos.y,z:pos.z},depthSpan:[0,1,2].map(axis=>Math.max(...layout.positions.filter((_,i)=>i%3===axis))-Math.min(...layout.positions.filter((_,i)=>i%3===axis)))}
}
function animate(time){if(!mounted)return;const dt=Math.min((time-lastTime)/1000||.016,.05);lastTime=time;director?.update(time,dt);renderer?.render(dt);updateLabels(time);frame=requestAnimationFrame(animate)}
function bindPointer(){
 const element=renderer.renderer.domElement
 const pick=e=>{
  const r=element.getBoundingClientRect(),x=e.clientX-r.left,y=e.clientY-r.top;let best=-1,dist=18
  graphData.nodes.forEach((_,i)=>{if(localMode()&&selected.value&&!allNeighbors.has(i))return;const p=renderer.projectNode(i,r.width,r.height),d=Math.hypot(p.x-x,p.y-y);if(!p.behind&&d<dist){best=i;dist=d}});return best
 }
 const down=e=>{pointerDown={x:e.clientX,y:e.clientY}}
 const up=e=>{if(!pointerDown||Math.hypot(e.clientX-pointerDown.x,e.clientY-pointerDown.y)>5)return;const i=pick(e);if(i>=0)choose(graphData.nodes[i]);pointerDown=null}
 const move=e=>{if(e.buttons)return;hovered.value=pick(e);element.style.cursor=hovered.value>=0?'pointer':'grab'}
 const leave=()=>{hovered.value=-1}
 element.addEventListener('pointerdown',down);element.addEventListener('pointerup',up);element.addEventListener('pointermove',move);element.addEventListener('pointerleave',leave)
 removeEvents=()=>{element.removeEventListener('pointerdown',down);element.removeEventListener('pointerup',up);element.removeEventListener('pointermove',move);element.removeEventListener('pointerleave',leave)}
}
onMounted(async()=>{
 try{
  const [render,camera,force,three,presets]=await Promise.all([import('../vendor/galaxy-view/render/AggregateRenderer'),import('../vendor/galaxy-view/interactions/CameraDirector'),import('../vendor/galaxy-view/layout/MainThreadForceLayout'),import('three'),import('../vendor/galaxy-view/render/presets')])
  if(!mounted)return
  THREE=three;modules=presets;renderer=new render.AggregateRenderer(host.value,220);renderer.applyTier({...TIERS.high,starScale:.28},currentPreset.value.bloom.strength);renderer.resize(host.value.clientWidth,host.value.clientHeight)
  director=new camera.CameraDirector(renderer.camera,renderer.renderer.domElement,{onFlyToSelected:()=>{if(selected.value)choose(selected.value)},onResetView:reset});director.cruiseEnabled=rotate.value;director.cruiseSpeed=1.4
  layout=new force.MainThreadForceLayout();loadData();bindPointer()
  host.value.__galaxySelect=id=>{const n=dataNodes.value.find(n=>String(n.id)===String(id));if(n)choose(n)};host.value.__galaxyRenderer=renderer
  observer=new ResizeObserver(()=>{renderer.resize(host.value.clientWidth,host.value.clientHeight);lastLabelUpdate=0});observer.observe(host.value);frame=requestAnimationFrame(animate)
 }catch(error){failure.value='三维视图暂时无法打开，请切换层级列表。';console.error(error)}
})
onUnmounted(()=>{mounted=false;observer?.disconnect();cancelAnimationFrame(frame);removeEvents();director?.dispose();layout?.dispose();renderer?.dispose()})
watch(()=>[props.nodes,props.edges,scope.value,relationFilter.value,presetId.value],loadData,{deep:true})
watch(()=>props.layoutMode,()=>{if(props.layoutMode==='relationship_projection'&&!selected.value&&graphData.nodes.length)choose([...graphData.nodes].sort((a,b)=>b.degree-a.degree)[0]);updateFocus()})
watch([focusOnly,depth],updateFocus);watch([light,colorMode],applyLook)
watch(rotate,value=>{if(director){director.cruiseEnabled=value;if(value)director.beginFocusOrbit(null)}})
</script>

<template>
 <section class="knowledge-graph galaxy-graph" data-testid="knowledge-graph-explorer">
  <div class="graph-toolbar">
   <div class="graph-search-wrap"><SearchField v-model="query" aria-label="检索知识点" placeholder="搜索知识点" clearable @keydown.enter="searchFirst" /><div v-if="matches.length" class="graph-matches"><button v-for="node in matches" :key="node.id" @click="choose(node)">{{node.name}}</button></div></div>
   <select v-model="scope" aria-label="图谱内容范围"><option value="knowledge">课程知识</option><option value="all">知识与来源</option></select>
   <select v-if="showRelationFilter" v-model="relationFilter" aria-label="按关系类型筛选"><option value="all">全部关系</option><option value="prerequisite">先修关系</option><option value="grounds">来源支撑</option></select>
   <select v-model="colorMode" aria-label="节点配色"><option value="topic">按章节</option><option value="mastery">按掌握</option></select>
  </div>
  <div ref="stage" class="galaxy-stage" :class="{light}" :style="{height:`${canvasHeight}px`}">
   <div ref="host" class="galaxy-canvas" aria-label="可旋转的三维课程知识图谱" />
   <div class="galaxy-heading"><strong>{{chartTitle}}</strong><span>{{dataNodes.length}} 个节点 · {{dataEdges.length}} 条关系</span></div>
   <div class="scene-controls"><select v-model="presetId" aria-label="星系风格"><option v-for="p in STYLE_PRESETS" :key="p.id" :value="p.id">{{p.name}}</option></select><button :title="light?'切换星空':'切换纸面'" @click="light=!light"><Moon v-if="light" :size="17"/><Sun v-else :size="17"/></button><button :aria-pressed="rotate" :title="rotate?'停止环视':'环视'" @click="rotate=!rotate"><Orbit :size="17"/></button><button title="重置图谱视图" @click="reset"><Maximize2 :size="17"/></button><button title="全屏图谱" @click="fullscreen"><Expand :size="17"/></button></div>
   <div class="node-labels"><button v-for="label in labels" :key="label.id" :class="{active:label.active}" :style="{left:`${label.x}px`,top:`${label.y}px`,width:`${label.w}px`,color:light?'#344659':label.color}" @click="choose({id:label.id})">{{label.name}}</button></div>
   <div class="graph-key" :class="{selected}"><template v-if="colorMode==='mastery'"><span v-for="item in palette" :key="item.name"><i :style="{background:item.color}"/>{{item.name}}</span></template><span v-else>同章同色 · 连线表示课程关系</span></div>
   <div v-if="selected" class="focus-chip"><strong>{{selected.name}}</strong><select v-model="depth" aria-label="关联深度"><option :value="1">一层关联</option><option :value="2">两层关联</option></select><button :aria-pressed="focusOnly" @click="focusOnly=!focusOnly">{{focusOnly?'查看全课':'只看关联'}}</button></div>
   <span v-else class="gesture-note">拖动环绕 · 右键平移 · 滚轮缩放 · 点击飞近</span>
   <div v-if="failure||!dataNodes.length" class="graph-state">{{failure||emptyText}}</div><div v-else-if="!ready" class="graph-state">正在展开课程知识…</div>
  </div>
  <aside v-if="showDetails&&selected" class="compact-details"><strong>{{selected.name}}</strong><p>{{selected.summary}}</p></aside>
 </section>
</template>

<style scoped>
.knowledge-graph{min-width:0;overflow:hidden;border:1px solid var(--color-border);border-radius:18px;background:var(--color-surface);color:var(--color-text)}
.graph-toolbar{display:flex;align-items:center;flex-wrap:wrap;gap:10px;padding:14px 16px}.graph-search-wrap{flex:1 1 210px;min-width:170px;position:relative;z-index:3}
.graph-toolbar button,.graph-toolbar select{min-height:38px;padding:7px 11px;border:1px solid var(--color-border);border-radius:8px;background:var(--color-surface);font:inherit;font-size:14px;color:var(--color-text-secondary);cursor:pointer}
.graph-matches{position:absolute;top:100%;left:0;right:0;padding:6px;margin-top:4px;box-shadow:0 10px 30px #303b451a;border:1px solid var(--color-border);border-radius:10px;background:var(--color-surface)}.graph-matches button{display:block;width:100%;border:0;text-align:left;padding:10px}.graph-matches button:hover{background:var(--color-accent-soft)}
.galaxy-stage{position:relative;min-width:0;isolation:isolate;background:#000003;color:#e7eaf1}.galaxy-stage:fullscreen{height:100vh!important;border-radius:0}.galaxy-canvas{position:absolute;inset:0;overflow:hidden}.galaxy-canvas :deep(canvas){display:block;outline:none}
.galaxy-heading{position:absolute;left:24px;top:22px;pointer-events:none;display:grid;gap:7px}.galaxy-heading strong{font-size:22px;font-weight:500;letter-spacing:.04em}.galaxy-heading span{font-size:13px;opacity:.65}
.scene-controls{position:absolute;right:18px;top:18px;display:flex;gap:7px}.scene-controls button,.scene-controls select,.focus-chip button,.focus-chip select{display:flex;align-items:center;justify-content:center;min-height:35px;padding:6px 9px;border:1px solid #ffffff24;border-radius:7px;color:inherit;background:#17202caa;font:inherit;font-size:13px;cursor:pointer}.scene-controls button[aria-pressed=true]{color:#a9d7ec}.scene-controls option,.focus-chip option{background:#17202c}
.node-labels{position:absolute;inset:0;pointer-events:none}.node-labels button{position:absolute;pointer-events:auto;border:0;border-radius:5px;background:#060b13b8;padding:5px 9px;text-align:left;font:500 14px/1.4 "Microsoft YaHei",sans-serif;cursor:pointer;max-width:280px}.node-labels button.active{background:#17202ce0;color:#fff!important;box-shadow:inset 2px 0 #a9d7ec}
.graph-key{position:absolute;left:24px;bottom:56px;display:flex;flex-wrap:wrap;gap:12px;font-size:12px;color:#c5ccd9;pointer-events:none}.graph-key span{display:flex;align-items:center;gap:6px}.graph-key i{width:7px;height:7px;border-radius:50%}
.graph-key.selected{bottom:78px}
.focus-chip{position:absolute;left:18px;bottom:14px;max-width:calc(100% - 36px);display:flex;align-items:center;gap:10px;padding:9px 12px;border:1px solid #ffffff24;border-radius:10px;background:#111924dd;font-size:14px}.focus-chip strong{font-weight:500;max-width:300px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.focus-chip select,.focus-chip button{border:0;background:#ffffff0c;white-space:nowrap}
.gesture-note{position:absolute;bottom:21px;left:24px;font-size:12px;color:#a9b4c7;pointer-events:none}.graph-state{position:absolute;inset:0;display:grid;place-items:center;background:#000003;font-size:15px;pointer-events:none}
.light{color:#354554;background:#fcfbf8}.light .scene-controls button,.light .scene-controls select,.light .focus-chip,.light .focus-chip select,.light .focus-chip button{background:#fffefde8;color:#354554;border-color:#43556a26}.light option{background:#fffefd}.light .node-labels button{background:#fffefddd}.light .node-labels button.active{color:#344659!important;background:#edf2f8}.light .graph-key,.light .gesture-note{color:#637181}.light .graph-state{background:#fcfbf8}
.compact-details{padding:18px 22px}.compact-details p{margin:7px 0 0;line-height:1.7;color:var(--color-text-secondary)}
@media(max-width:1100px){.galaxy-heading strong{font-size:18px}.galaxy-heading{top:66px;left:18px}.scene-controls{left:18px;right:auto;top:14px}.focus-chip strong{max-width:180px}.graph-key{left:18px;right:18px;font-size:11px}.gesture-note{left:18px;font-size:11px}}
</style>
