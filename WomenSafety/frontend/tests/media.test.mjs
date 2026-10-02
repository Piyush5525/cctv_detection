import test from 'node:test'
import assert from 'node:assert/strict'
import { API_BASE, describeFailure, evidenceDir, evidenceUrl, hasAnnotated, isVideoPlaying, setVideoPlaying } from '../src/utils/media.mjs'

const incident = (over = {}) => ({
  incident_id: 'abc-123', camera_id: 'CAM-SAMPLE-002', event_start: '2026-10-02T10:00:00+00:00',
  evidence: { best_frame_path: 'CAM-SAMPLE-002/2026-10-02/abc-123/best_frame.jpg', thumbnail_path: 'CAM-SAMPLE-002/2026-10-02/abc-123/thumbnail.jpg',
              clip_path: 'CAM-SAMPLE-002/2026-10-02/abc-123/clip.mp4', annotated_frame_path: 'CAM-SAMPLE-002/2026-10-02/abc-123/annotated_frame.jpg' }, ...over,
})

test('every URL is the API base plus the incident relative path', () => {
  assert.equal(API_BASE, '/api/v1')
  assert.equal(evidenceUrl(incident(), 'clip'), '/api/v1/evidence/v2/CAM-SAMPLE-002/2026-10-02/abc-123/clip.mp4')
  assert.equal(evidenceUrl(incident(), 'best'), '/api/v1/evidence/v2/CAM-SAMPLE-002/2026-10-02/abc-123/best_frame.jpg')
  assert.equal(evidenceUrl(incident(), 'annotated'), '/api/v1/evidence/v2/CAM-SAMPLE-002/2026-10-02/abc-123/annotated_frame.jpg')
  assert.equal(evidenceUrl(incident(), 'thumbnail'), '/api/v1/evidence/v2/CAM-SAMPLE-002/2026-10-02/abc-123/thumbnail.jpg')
})

test('showcase incident (camera re-assigned): the stored relative path agrees with the camera folder', () => {
  assert.equal(evidenceDir(incident({ camera_id: 'CAM-SAMPLE-002' })), 'CAM-SAMPLE-002/2026-10-02/abc-123')
})

test('without stored paths the folder is built from camera, event date and id', () => {
  const inc = incident({ evidence: {} })
  assert.equal(evidenceDir(inc), 'CAM-SAMPLE-002/2026-10-02/abc-123')
  assert.equal(hasAnnotated(inc), false)
})

test('windows separators and an evidence/ prefix are normalised; a path for another incident is ignored', () => {
  assert.equal(evidenceDir(incident({ evidence: { clip_path: 'evidence\\CAM-X\\2026-10-02\\abc-123\\clip.mp4' } })), 'CAM-X/2026-10-02/abc-123')
  assert.equal(evidenceDir(incident({ evidence: { clip_path: 'CAM-X/2026-10-02/other-id/clip.mp4' } })), 'CAM-SAMPLE-002/2026-10-02/abc-123')
})

test('retry adds a cache-busting nonce, unknown kind throws', () => {
  assert.ok(evidenceUrl(incident(), 'clip', 2).endsWith('clip.mp4?r=2'))
  assert.throws(() => evidenceUrl(incident(), 'nope'))
})

test('failure reasons are specific, never blank', () => {
  assert.match(describeFailure(404), /not found/i)
  assert.match(describeFailure(null), /network/i)
  assert.match(describeFailure(500), /server error/i)
  assert.match(describeFailure(200), /decode/i)
})

test('slideshow pause flag', () => {
  setVideoPlaying(true); assert.equal(isVideoPlaying(), true)
  setVideoPlaying(false); assert.equal(isVideoPlaying(), false)
})
