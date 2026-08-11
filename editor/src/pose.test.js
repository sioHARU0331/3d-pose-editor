import { describe, expect, it } from 'vitest';
import { BONES, B_TEST_CASES, NORMALIZED_BONE_NAMES, blankPose, createPoseDocument, createVmcPayload, normalizePoseDocument } from './pose.js';
describe('pose schema', () => {
  it('contains the arm and all 15 right finger joints', () => expect(BONES).toHaveLength(19));
  it('limits B direction checks to three local-Y tests', () => { expect(Object.keys(B_TEST_CASES)).toHaveLength(3); expect(Object.values(B_TEST_CASES).every(t => t.axis === 'Y' && t.degrees === 30)).toBe(true); });
  it('maps VRM 0 thumb joints to normalized VRM 1 names', () => expect(NORMALIZED_BONE_NAMES.rightThumbIntermediate).toBe('rightThumbProximal'));
  it('loads legacy PascalCase JSON', () => { const p=normalizePoseDocument({RightHand:[1,2,3],RightIndexDistal:[4,5,6]}); expect(p.rightHand).toEqual([1,2,3]); expect(p.rightIndexDistal).toEqual([4,5,6]); });
  it('round trips the versioned format', () => { const p=blankPose(); p.rightThumbDistal=[7,8,9]; expect(normalizePoseDocument(createPoseDocument(p))).toEqual(p); });
  it('creates controller-compatible bone keys', () => expect(createVmcPayload(blankPose())).toHaveProperty('RightLittleDistal'));
  it('rejects invalid rotations', () => expect(() => normalizePoseDocument({RightHand:[1,2]})).toThrow());
});
