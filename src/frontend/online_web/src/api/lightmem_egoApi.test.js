import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  normalizeLongTermMemoryResponse,
  normalizeEvidenceFrames,
  startImageUploadStream,
  uploadAudioChunk,
  updateThirtySecondMemories
} from './lightmem_egoApi.js'
import { normalizeMemoryGraphResponse } from '../utils/memoryGraphUtils.js'

afterEach(() => {
  vi.restoreAllMocks()
})

describe('long-term memory edit API', () => {
  it('normalizes the edit contract and record permissions', () => {
    const memory = normalizeLongTermMemoryResponse(buildMemory(), 'session-1')
    expect(memory.editPolicy.maxCharsPerRecord).toBe(4000)
    expect(memory.fullPropagationSupported).toBe(true)
    expect(memory.episodic['30sec'][0]).toMatchObject({
      id: 'record-1',
      editable: true,
      editDisabledReason: null
    })
  })

  it('keeps legacy backend Memory readable while disabling edits', () => {
    const legacy = buildMemory()
    delete legacy.propagation

    const memory = normalizeLongTermMemoryResponse(legacy, 'session-1')
    expect(memory.editSupported).toBe(false)
    expect(memory.fullPropagationSupported).toBe(false)
    expect(memory.canRollback).toBe(false)
    expect(memory.episodic['30sec'][0]).toMatchObject({
      editable: false,
      editDisabledReason: 'full_propagation_not_supported'
    })
  })

  it('sends only the requested changes with one idempotency key', async () => {
    const responseMemory = buildMemory({ version: 2, content: 'updated', canRollback: true })
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify({
      status: 'ok',
      success: true,
      message: '当前记忆已修改，请刷新页面。',
      sessionId: 'session-1',
      memoryVersion: 2,
      memory: responseMemory,
      graphUpdate: {
        status: 'ready',
        scale: '30sec',
        memoryVersion: 2,
        componentVersions: { episodic: 2, graph: 2, semantic: 2 },
        graphVersions: { episodicGraph: 2, semanticGraph: 2 },
        etag: '"mg-2"'
      },
      propagation: buildPropagation(2),
      canRollback: true
    }), {
      status: 200,
      headers: { 'Content-Type': 'application/json', 'X-Request-ID': 'request-1' }
    }))

    const result = await updateThirtySecondMemories({
      sessionId: 'session-1',
      baseVersion: 1,
      records: [{ id: 'record-1', content: 'updated' }],
      idempotencyKey: 'operation-1'
    })

    const [url, options] = fetchMock.mock.calls[0]
    expect(url).toMatch(/\/session\/session-1\/memories\/30sec$/)
    expect(options.method).toBe('PUT')
    expect(options.headers['Idempotency-Key']).toBe('operation-1')
    expect(JSON.parse(options.body)).toEqual({
      baseVersion: 1,
      records: [{ id: 'record-1', content: 'updated' }]
    })
    expect(result.memory.memoryVersion).toBe(2)
    expect(result.propagation.status).toBe('ready')
    expect(result.requestId).toBe('request-1')
  })

  it('rejects a successful mutation response without complete propagation', async () => {
    const responseMemory = buildMemory({ version: 2, content: 'updated', canRollback: true })
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify({
      status: 'ok',
      success: true,
      message: 'updated',
      sessionId: 'session-1',
      memoryVersion: 2,
      memory: responseMemory,
      graphUpdate: {
        status: 'ready',
        scale: '30sec',
        memoryVersion: 2,
        componentVersions: { episodic: 2, graph: 2, semantic: 2 },
        graphVersions: { episodicGraph: 2, semanticGraph: 2 }
      },
      canRollback: true
    }), { status: 200, headers: { 'Content-Type': 'application/json' } }))

    await expect(updateThirtySecondMemories({
      sessionId: 'session-1',
      baseVersion: 1,
      records: [{ id: 'record-1', content: 'updated' }],
      idempotencyKey: 'operation-1'
    })).rejects.toMatchObject({ code: 'invalid_memory_mutation_response' })
  })

  it('preserves structured backend errors and request IDs', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify({
      error: {
        code: 'memory_version_conflict',
        message: 'reload',
        details: { currentVersion: 3 }
      }
    }), {
      status: 409,
      headers: { 'Content-Type': 'application/json', 'X-Request-ID': 'request-conflict' }
    }))

    await expect(updateThirtySecondMemories({
      sessionId: 'session-1',
      baseVersion: 1,
      records: [{ id: 'record-1', content: 'updated' }],
      idempotencyKey: 'operation-1'
    })).rejects.toMatchObject({
      status: 409,
      code: 'memory_version_conflict',
      details: { currentVersion: 3 },
      requestId: 'request-conflict'
    })
  })

  it('normalizes both graph versions while keeping old read-only Graph responses compatible', () => {
    const current = buildGraphResponse(2)
    expect(normalizeMemoryGraphResponse(current, 'session-1').graphVersions).toEqual({
      episodicGraph: 2,
      semanticGraph: 2
    })

    const legacy = buildGraphResponse(1)
    delete legacy.graph_versions
    expect(normalizeMemoryGraphResponse(legacy, 'session-1').graphVersions).toBeNull()
  })
})

describe('Photo Stream API', () => {
  it('formats relative upload time from milliseconds for evidence labels', () => {
    const [frame] = normalizeEvidenceFrames({
      evidence_frames: [{ id: 'frame-2', relative_ts_ms: 2450, caption: 'A scene' }]
    }, 'session-1')

    expect(frame.timestamp).toBe(2.45)
    expect(frame.timestampText).toBe('2.5s')
  })

  it('starts an image upload session through the existing stream endpoint', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify({
      session_id: 'photo-session',
      input_mode: 'frame_audio_stream',
      can_ask: false
    }), { status: 200, headers: { 'Content-Type': 'application/json' } }))

    await startImageUploadStream()

    const [url, options] = fetchMock.mock.calls[0]
    expect(url).toMatch(/\/stream\/start$/)
    expect(options.method).toBe('POST')
    expect(JSON.parse(options.body).metadata).toMatchObject({
      source: 'web_image_upload',
      mode: 'image_upload'
    })
  })

  it('uploads a local audio file through the existing audio chunk endpoint', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify({
      session_id: 'media-session',
      audio_index: 0,
      audio_ready: true
    }), { status: 200, headers: { 'Content-Type': 'application/json' } }))
    const audio = new File(['audio'], 'sample.wav', { type: 'audio/wav' })

    await uploadAudioChunk('media-session', audio, {
      audioIndex: 0,
      relativeTsMs: 1250,
      durationMs: 3000,
      source: 'web_audio_upload',
      filename: audio.name
    })

    const [url, options] = fetchMock.mock.calls[0]
    expect(url).toMatch(/\/stream\/media-session\/audio_chunk$/)
    expect(options.method).toBe('POST')
    expect(options.body.get('audio')).toMatchObject({ name: 'sample.wav', type: 'audio/wav', size: 5 })
    expect(options.body.get('audio_index')).toBe('0')
    expect(options.body.get('relative_ts_ms')).toBe('1250')
    expect(options.body.get('duration_ms')).toBe('3000')
    expect(options.body.get('source')).toBe('web_audio_upload')
  })
})

function buildMemory({ version = 1, content = 'original', canRollback = false } = {}) {
  return {
    status: 'ok',
    schemaVersion: 1,
    sessionId: 'session-1',
    memorySource: 'M_lt',
    memoryVersion: version,
    componentVersions: { episodic: version, semantic: version, visual: version },
    activeRootKind: 'em2mem',
    qaAligned: true,
    updatedAt: null,
    completeRecordSet: true,
    fieldTruncation: false,
    truncatedFieldCount: 0,
    availability: { episodic: 'ready', semantic: 'ready', visual: 'ready' },
    counts: {
      total: 1,
      episodic: 1,
      semantic: 0,
      visual: 0,
      episodicByGranularity: { '30sec': 1, '3min': 0, '10min': 0, '1h': 0 }
    },
    episodic: {
      '30sec': [{ id: 'record-1', content, editable: true, editDisabledReason: null }],
      '3min': [],
      '10min': [],
      '1h': []
    },
    semantic: [],
    visual: [],
    editPolicy: {
      field: 'episodic.30sec[].content',
      maxCharsPerRecord: 4000,
      maxTotalChars: 32000,
      lengthUnit: 'unicode_code_points'
    },
    propagation: buildPropagation(version),
    canRollback
  }
}

function buildPropagation(version) {
  return {
    status: 'ready',
    sourceScale: '30sec',
    targetMemoryVersion: version,
    derivedScales: {
      '3min': { status: 'ready', recomputedRecords: 0 },
      '10min': { status: 'ready', recomputedRecords: 0 },
      '1h': { status: 'ready', recomputedRecords: 0 }
    },
    semantic: { status: 'ready', version, changedFacts: 0 },
    graphs: {
      episodic: { status: 'ready', version },
      semantic: { status: 'ready', version }
    },
    backends: {
      multiscale: 'llm',
      triplets: 'llm_openie',
      semantic: 'llm_semantic_extraction_consolidation'
    }
  }
}

function buildGraphResponse(version) {
  return {
    schema_version: 1,
    status: 'ok',
    session_id: 'session-1',
    memory_source: 'M_lt',
    scale: '30sec',
    memory_version: version,
    component_versions: { episodic: version, graph: version, semantic: version },
    graph_versions: { episodic_graph: version, semantic_graph: version },
    episodic: { nodes: [], edges: [] },
    semantic: { nodes: [], edges: [], timeline: [] },
    documents: {},
    indexes: {},
    warnings: {}
  }
}
