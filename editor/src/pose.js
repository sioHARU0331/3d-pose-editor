import * as THREE from 'three';

export const MODEL_ID = { file: 'AvatarSample_B_clean_hands_v3.vrm', sha256: '7CDD3E660F9396A6AD82DA319D301A541493034504780882B58AACFC868ACD18' };
export const BONE_GROUPS = {
  '右腕': ['rightShoulder','rightUpperArm','rightLowerArm','rightHand'],
  '親指': ['rightThumbProximal','rightThumbIntermediate','rightThumbDistal'],
  '人差し指': ['rightIndexProximal','rightIndexIntermediate','rightIndexDistal'],
  '中指': ['rightMiddleProximal','rightMiddleIntermediate','rightMiddleDistal'],
  '薬指': ['rightRingProximal','rightRingIntermediate','rightRingDistal'],
  '小指': ['rightLittleProximal','rightLittleIntermediate','rightLittleDistal'],
};
export const BONES = Object.values(BONE_GROUPS).flat();
export const B_TEST_CASES = {
  rightHand: { label: '右手首', bone: 'rightHand', controllerBone: 'RightHand', axis: 'Y', axisIndex: 1, degrees: 30 },
  rightIndexProximal: { label: '右人差し指付け根', bone: 'rightIndexProximal', controllerBone: 'RightIndexProximal', axis: 'Y', axisIndex: 1, degrees: 30 },
  rightThumbProximal: { label: '右親指付け根', bone: 'rightThumbProximal', controllerBone: 'RightThumbProximal', axis: 'Y', axisIndex: 1, degrees: 30 },
};
export const NORMALIZED_BONE_NAMES = { rightThumbProximal: 'rightThumbMetacarpal', rightThumbIntermediate: 'rightThumbProximal' };
export const DISPLAY_NAMES = Object.fromEntries(Object.entries(BONE_GROUPS).flatMap(([group, bones]) => bones.map((bone, index) => [bone, `${group}${index ? index : ''}`])));
const LEGACY = Object.fromEntries(BONES.map(name => [name[0].toUpperCase() + name.slice(1), name]));
export const blankPose = () => Object.fromEntries(BONES.map(name => [name, [0,0,0]]));
export const clonePose = pose => Object.fromEntries(BONES.map(name => [name, [...(pose[name] ?? [0,0,0])]]));
export function normalizePoseDocument(doc) {
  const source = doc?.pose?.bones ?? doc?.bones ?? doc;
  if (!source || typeof source !== 'object' || Array.isArray(source)) throw new Error('ポーズデータの形式が不正です');
  const pose = blankPose();
  for (const [key, value] of Object.entries(source)) {
    const name = BONES.includes(key) ? key : LEGACY[key];
    if (!name) continue;
    if (!Array.isArray(value) || value.length !== 3 || value.some(v => !Number.isFinite(Number(v)))) throw new Error(`${key} は3つの数値で指定してください`);
    pose[name] = value.map(Number);
  }
  return pose;
}
export function createPoseDocument(pose) {
  return { schema: 'vrm-pose-editor', version: 1, model: MODEL_ID, rotation: { space: 'normalizedHumanoidLocalRest', unit: 'degree', order: 'XYZ', composition: 'restQuaternion * deltaQuaternion' }, pose: { bones: clonePose(pose) } };
}
export function createVmcPayload(pose) {
  return Object.fromEntries(BONES.map(name => [name[0].toUpperCase() + name.slice(1), pose[name].map(v => Math.round(v * 100) / 100)]));
}
export function quaternionFromDegrees(values) { return new THREE.Quaternion().setFromEuler(new THREE.Euler(...values.map(THREE.MathUtils.degToRad), 'XYZ')); }
export function degreesFromQuaternion(q) { const e = new THREE.Euler().setFromQuaternion(q, 'XYZ'); return [e.x,e.y,e.z].map(THREE.MathUtils.radToDeg); }
