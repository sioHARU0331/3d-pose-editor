import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { TransformControls } from 'three/addons/controls/TransformControls.js';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { VRMLoaderPlugin, VRMUtils } from '@pixiv/three-vrm';
import { BONES, BONE_GROUPS, B_TEST_CASES, DISPLAY_NAMES, NORMALIZED_BONE_NAMES, blankPose, clonePose, createPoseDocument, createVmcPayload, degreesFromQuaternion, normalizePoseDocument, quaternionFromDegrees } from './pose.js';
import legacyThinkingPose from '../../poses/fortune_think_pose.json';

const $ = id => document.getElementById(id);
const canvas=$('viewport'), renderer=new THREE.WebGLRenderer({canvas,antialias:true,alpha:true});
renderer.setPixelRatio(Math.min(devicePixelRatio,2)); renderer.outputColorSpace=THREE.SRGBColorSpace;
const scene=new THREE.Scene(); scene.background=new THREE.Color(0x111827);
const camera=new THREE.PerspectiveCamera(35,1,.01,100); camera.position.set(0,1.25,3.4);
const orbit=new OrbitControls(camera,canvas); orbit.enableDamping=true; orbit.target.set(0,1,0);
scene.add(new THREE.HemisphereLight(0xffffff,0x263045,2.4)); const key=new THREE.DirectionalLight(0xffffff,2.8); key.position.set(2,3,4); scene.add(key);
const grid=new THREE.GridHelper(10,20,0x52617d,0x263045); scene.add(grid);
const transform=new TransformControls(camera,canvas); transform.setMode('rotate'); transform.setSpace('local'); transform.setSize(.75); scene.add(transform.getHelper()); transform.addEventListener('dragging-changed',e=>orbit.enabled=!e.value);
let vrm, helper, pose=blankPose(), rests={}, selected='rightUpperArm', history=[], future=[], draggingStart;
let activeBTest=null;
const nodes=()=>Object.fromEntries(BONES.map(name=>[name,vrm?.humanoid.getNormalizedBoneNode(NORMALIZED_BONE_NAMES[name] ?? name)]));
function status(text,error=false){$('status').textContent=text;$('status').classList.toggle('error',error)}
function resize(){const w=canvas.clientWidth,h=canvas.clientHeight;if(canvas.width!==w*renderer.getPixelRatio()||canvas.height!==h*renderer.getPixelRatio()){renderer.setSize(w,h,false);camera.aspect=w/h;camera.updateProjectionMatrix()}}
function applyBone(name){const node=nodes()[name];if(!node)return;node.quaternion.copy(rests[name]).multiply(quaternionFromDegrees(pose[name]));node.updateMatrixWorld(true)}
function applyAll(){BONES.forEach(applyBone);syncControls()}
function commit(before){if(JSON.stringify(before)===JSON.stringify(pose))return;history.push(before);if(history.length>100)history.shift();future=[];syncHistory()}
function syncHistory(){$('undo').disabled=!history.length;$('redo').disabled=!future.length}
function setPose(next,record=true){const before=clonePose(pose);pose=clonePose(next);applyAll();if(record)commit(before)}
function setSelected(name){selected=name;$('boneSelect').value=name;document.querySelectorAll('[data-bone]').forEach(b=>b.classList.toggle('active',b.dataset.bone===name));$('selectedTitle').textContent=`回転：${DISPLAY_NAMES[name]}`;if(vrm)transform.attach(nodes()[name]);syncControls()}
function syncControls(){document.querySelectorAll('[data-axis]').forEach(row=>{const i='XYZ'.indexOf(row.dataset.axis),v=Math.round(pose[selected][i]*100)/100;row.querySelector('input[type=range]').value=v;row.querySelector('input[type=number]').value=v})}
function editAxis(i,value,commitNow){const before=clonePose(pose);pose[selected][i]=THREE.MathUtils.clamp(Number(value)||0,-180,180);applyBone(selected);syncControls();if(commitNow)commit(before)}
function buildUI(){
  $('boneSelect').innerHTML=Object.entries(BONE_GROUPS).map(([g,b])=>`<optgroup label="${g}">${b.map(n=>`<option value="${n}">${DISPLAY_NAMES[n]}</option>`).join('')}</optgroup>`).join('');
  $('boneList').innerHTML=Object.entries(BONE_GROUPS).map(([g,b])=>`<div><strong>${g}</strong>${b.map(n=>`<button data-bone="${n}">${DISPLAY_NAMES[n]}</button>`).join('')}</div>`).join('');
  document.querySelectorAll('[data-bone]').forEach(b=>b.onclick=()=>setSelected(b.dataset.bone));$('boneSelect').onchange=e=>setSelected(e.target.value);
  $('axisControls').innerHTML='XYZ'.split('').map(a=>`<label class="axis" data-axis="${a}"><b>${a}</b><input type="range" min="-180" max="180" step="0.1"><input type="number" min="-180" max="180" step="0.1"><span>°</span></label>`).join('');
  document.querySelectorAll('[data-axis]').forEach(row=>{const i='XYZ'.indexOf(row.dataset.axis);for(const input of row.querySelectorAll('input')){input.oninput=e=>{if(!input._before){input._before=clonePose(pose);history.push(input._before);if(history.length>100)history.shift();future=[];syncHistory()}editAxis(i,e.target.value,false)};input.onchange=input.onblur=()=>{input._before=null};}});
  setSelected(selected);
}
function frameBody(direction){const box=new THREE.Box3().setFromObject(vrm.scene),center=box.getCenter(new THREE.Vector3()),size=box.getSize(new THREE.Vector3()),d=Math.max(size.y*1.35,1.8);orbit.target.copy(center);camera.position.copy(center).add(direction.clone().multiplyScalar(d));camera.up.set(0,1,0);camera.lookAt(center);orbit.update()}
function getRightHandBasis(){
  scene.updateMatrixWorld(true);
  const boneNodes=nodes(),wrist=boneNodes.rightHand.getWorldPosition(new THREE.Vector3()),middle=boneNodes.rightMiddleProximal.getWorldPosition(new THREE.Vector3()),thumb=boneNodes.rightThumbProximal.getWorldPosition(new THREE.Vector3());
  const handLength=middle.distanceTo(wrist),longitudinal=middle.clone().sub(wrist).normalize(),thumbOffset=thumb.clone().sub(wrist);
  const thumbSide=thumbOffset.addScaledVector(longitudinal,-thumbOffset.dot(longitudinal)).normalize();
  const palmSide=new THREE.Vector3().crossVectors(thumbSide,longitudinal).normalize();
  return {wrist,longitudinal,thumbSide,palmSide,handLength};
}
function frameHand(view){
  const {wrist,longitudinal,thumbSide,palmSide,handLength}=getRightHandBasis();
  const direction=view==='palm'?palmSide:view==='back'?palmSide.clone().negate():view==='thumb'?thumbSide:thumbSide.clone().negate();
  const center=wrist.clone().addScaledVector(longitudinal,Math.max(handLength*1.35,.075)),distance=Math.max(handLength*4.5,.3);
  orbit.target.copy(center);camera.position.copy(center).addScaledVector(direction,distance);camera.up.copy(longitudinal);camera.lookAt(center);orbit.update();
}
const CAMERA={front:()=>frameBody(new THREE.Vector3(0,0,1)),back:()=>frameBody(new THREE.Vector3(0,0,-1)),side:()=>frameBody(new THREE.Vector3(1,0,0)),handBack:()=>frameHand('back'),handPalm:()=>frameHand('palm'),thumb:()=>frameHand('thumb'),little:()=>frameHand('little')};
document.querySelectorAll('[data-camera]').forEach(b=>b.onclick=()=>{CAMERA[b.dataset.camera]?.();document.querySelectorAll('[data-camera]').forEach(x=>x.classList.toggle('active',x===b))});
transform.addEventListener('mouseDown',()=>draggingStart=clonePose(pose));
transform.addEventListener('objectChange',()=>{if(!vrm)return;const node=nodes()[selected],delta=rests[selected].clone().invert().multiply(node.quaternion);pose[selected]=degreesFromQuaternion(delta);syncControls()});
transform.addEventListener('mouseUp',()=>{if(draggingStart)commit(draggingStart);draggingStart=null});
$('undo').onclick=()=>{if(!history.length)return;future.push(clonePose(pose));pose=history.pop();applyAll();syncHistory()};$('redo').onclick=()=>{if(!future.length)return;history.push(clonePose(pose));pose=future.pop();applyAll();syncHistory()};
$('resetBone').onclick=()=>{const n=clonePose(pose);n[selected]=[0,0,0];setPose(n)};$('resetAll').onclick=()=>setPose(blankPose());
async function loadDocument(doc,label){try{setPose(normalizePoseDocument(doc));status(`${label}を読み込みました`)}catch(e){status(e.message,true)}}
$('loadLegacy').onclick=async()=>loadDocument(legacyThinkingPose,'考えるポーズ');
$('importPose').onchange=async e=>{const file=e.target.files[0];if(file)await loadDocument(JSON.parse(await file.text()),file.name);e.target.value=''};
$('exportPose').onclick=()=>{const blob=new Blob([JSON.stringify(createPoseDocument(pose),null,2)],{type:'application/json'}),a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download='vrm-pose-v1.json';a.click();setTimeout(()=>URL.revokeObjectURL(a.href),1000)};
$('mockSend').onclick=()=>{$('payload').textContent=JSON.stringify({endpoint:'http://127.0.0.1:8766/fortune_pose_adjust',mode:'mock-only-on-A',body:{action:'preview',bones:createVmcPayload(pose)}},null,2);status('モックpayloadを生成（送信していません）')};
const B_TEST_ENDPOINT='http://127.0.0.1:8766/fortune_pose_adjust';
$('bTestButtons').innerHTML=Object.entries(B_TEST_CASES).map(([key,test])=>`<button data-b-test="${key}"><b>${test.label}</b>local ${test.axis} +${test.degrees}°</button>`).join('');
function showBTestRecord(test,phase,payload,response){
  $('bTestRecord').textContent=JSON.stringify({phase,bone:test.controllerBone,editorLocalAxis:test.axis,degrees:phase==='test'?test.degrees:0,endpoint:B_TEST_ENDPOINT,payload,response},null,2);
}
async function postBTest(test,values,phase){
  const payload={active:true,test_only:true,values:{[test.controllerBone]:values.map(v=>Math.round(v*100)/100)}},abort=new AbortController(),timer=setTimeout(()=>abort.abort(),800);
  showBTestRecord(test,phase,payload,{pending:true});
  try{const r=await fetch(B_TEST_ENDPOINT,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload),signal:abort.signal}),body=await r.json();if(!r.ok||!body.ok)throw new Error(body.error||`HTTP ${r.status}`);showBTestRecord(test,phase,payload,body);status(`B送信成功：${test.label} local ${test.axis} ${phase==='test'?'+':''}${phase==='test'?test.degrees:0}°`);return true}catch(e){showBTestRecord(test,phase,payload,{ok:false,error:e.name==='AbortError'?'timeout':e.message});status(`画面確認済み / B未接続：${test.label}`,true);return false}finally{clearTimeout(timer)}
}
async function startBTest(key){
  if(activeBTest)await restoreBTest(false);
  const test=B_TEST_CASES[key],original=clonePose(pose),next=clonePose(pose);next[test.bone][test.axisIndex]=THREE.MathUtils.clamp(next[test.bone][test.axisIndex]+test.degrees,-180,180);activeBTest={test,original};setPose(next);setSelected(test.bone);frameHand('palm');$('restoreBTest').disabled=false;await postBTest(test,next[test.bone],'test');
}
async function restoreBTest(finish=true){
  if(!activeBTest)return;const {test,original}=activeBTest;setPose(original);setSelected(test.bone);frameHand('palm');if(finish){activeBTest=null;$('restoreBTest').disabled=true;status(`テスト前へ復帰：${test.label}`)}await postBTest(test,original[test.bone],'restore');if(finish){const abort=new AbortController(),timer=setTimeout(()=>abort.abort(),800);try{await fetch(B_TEST_ENDPOINT,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({active:false,values:{}}),signal:abort.signal})}catch{}finally{clearTimeout(timer)}}
}
document.querySelectorAll('[data-b-test]').forEach(button=>button.onclick=()=>startBTest(button.dataset.bTest));
$('restoreBTest').onclick=()=>restoreBTest(true);
async function loadVrm(){status('実VRMを読み込み中…');const loader=new GLTFLoader();loader.register(p=>new VRMLoaderPlugin(p));const gltf=await loader.loadAsync('/AvatarSample_B_clean_hands_v3.vrm');vrm=gltf.userData.vrm;if(!vrm)throw new Error('VRMデータがありません');VRMUtils.removeUnnecessaryVertices(gltf.scene);VRMUtils.combineSkeletons(gltf.scene);VRMUtils.rotateVRM0(vrm);scene.add(vrm.scene);for(const [name,node] of Object.entries(nodes())){if(!node)throw new Error(`Humanoidボーン不足: ${name}`);rests[name]=node.quaternion.clone()}helper=new THREE.SkeletonHelper(vrm.scene);helper.material.opacity=.32;helper.material.transparent=true;scene.add(helper);applyAll();setSelected(selected);frameBody(new THREE.Vector3(0,0,1));status(`実VRM読込完了：右腕・右手 ${BONES.length}ボーン`)}
function animate(){requestAnimationFrame(animate);resize();orbit.update();vrm?.update(1/60);renderer.render(scene,camera)}
buildUI();animate();loadVrm().catch(e=>{console.error(e);status(`VRM読込失敗: ${e.message}`,true)});

