import { AlertTriangle, Pencil, RefreshCw, RotateCcw, X } from 'lucide-react'
import { useCallback, useEffect, useId, useMemo, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import {
  fetchLongTermMemories,
  fetchLongTermMemoryGraph,
  rollbackThirtySecondMemories,
  updateThirtySecondMemories
} from '../api/lightmem_egoApi.js'
import { MemoryRecordCard, ReadonlyValue } from './MemoryDialog.jsx'

const GET_TIMEOUT_MS = 15000
const WRITE_TIMEOUT_MS = 300000
const PENDING_RETRY_DELAYS_MS = [2000, 5000, 10000, 30000]
const GRAPH_RETRY_DELAYS_MS = [2000, 5000, 10000, 30000]
const RETRYABLE_DERIVATION_CODES = new Set([
  'semantic_rebuild_unavailable',
  'memory_derivation_failed'
])

export default function CurrentSessionMemoryEditor({ sessionId, onPublication }) {
  const [open, setOpen] = useState(false)
  const [memory, setMemory] = useState(null)
  const [drafts, setDrafts] = useState({})
  const [loading, setLoading] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [pendingOperation, setPendingOperation] = useState(null)
  const [error, setError] = useState(null)
  const [fieldErrors, setFieldErrors] = useState({})
  const [notice, setNotice] = useState('')
  const [graphState, setGraphState] = useState({ status: 'idle', error: null })
  const [graphTarget, setGraphTarget] = useState(null)
  const openerRef = useRef(null)
  const controllerRef = useRef(null)
  const retryTimerRef = useRef(null)
  const graphTimerRef = useRef(null)
  const generationRef = useRef(0)
  const publicationRevisionRef = useRef(0)

  const publish = useCallback((update) => {
    publicationRevisionRef.current += 1
    onPublication?.({ ...update, revision: publicationRevisionRef.current })
  }, [onPublication])

  const abortCurrentRequest = useCallback(() => {
    controllerRef.current?.abort()
    controllerRef.current = null
  }, [])

  const clearTimers = useCallback(() => {
    window.clearTimeout(retryTimerRef.current)
    window.clearTimeout(graphTimerRef.current)
    retryTimerRef.current = null
    graphTimerRef.current = null
  }, [])

  const installMemory = useCallback((nextMemory) => {
    setMemory(nextMemory)
    setDrafts(Object.fromEntries(
      nextMemory.episodic['30sec'].map((record) => [record.id, record.content])
    ))
    setFieldErrors({})
  }, [])

  const loadMemory = useCallback(async ({ preserveNotice = false } = {}) => {
    if (!sessionId) return null
    abortCurrentRequest()
    const generation = ++generationRef.current
    const request = createTimedController(GET_TIMEOUT_MS)
    controllerRef.current = request.controller
    setLoading(true)
    setError(null)
    if (!preserveNotice) setNotice('')
    try {
      const result = await fetchLongTermMemories({ sessionId, signal: request.controller.signal })
      if (generation !== generationRef.current || result.sessionId !== sessionId) return null
      installMemory(result)
      return result
    } catch (loadError) {
      if (generation !== generationRef.current) return null
      if (loadError?.name === 'AbortError' && !request.didTimeout()) return null
      setError(normalizeClientError(loadError, request.didTimeout()))
      return null
    } finally {
      request.cleanup()
      if (controllerRef.current === request.controller) controllerRef.current = null
      if (generation === generationRef.current) setLoading(false)
    }
  }, [abortCurrentRequest, installMemory, sessionId])

  useEffect(() => {
    generationRef.current += 1
    abortCurrentRequest()
    clearTimers()
    setOpen(false)
    setMemory(null)
    setDrafts({})
    setLoading(false)
    setSubmitting(false)
    setPendingOperation(null)
    setError(null)
    setFieldErrors({})
    setNotice('')
    setGraphState({ status: 'idle', error: null })
    setGraphTarget(null)
  }, [abortCurrentRequest, clearTimers, sessionId])

  useEffect(() => () => {
    generationRef.current += 1
    abortCurrentRequest()
    clearTimers()
  }, [abortCurrentRequest, clearTimers])

  const openEditor = (event) => {
    openerRef.current = event.currentTarget
    setOpen(true)
    setError(null)
    if (!memory) loadMemory()
  }

  const closeEditor = () => {
    if (submitting || retryTimerRef.current) return
    if (memory) installMemory(memory)
    setOpen(false)
    setError(null)
    requestAnimationFrame(() => openerRef.current?.focus())
  }

  const changedRecords = useMemo(() => {
    if (!memory) return []
    return memory.episodic['30sec']
      .filter((record) => record.editable && drafts[record.id] !== record.content)
      .map((record) => ({ id: record.id, content: drafts[record.id] ?? '' }))
  }, [drafts, memory])

  const validateChanges = () => {
    if (!memory) return false
    const nextErrors = {}
    let total = 0
    const seen = new Set()
    for (const record of changedRecords) {
      const length = codePointLength(record.content)
      total += length
      if (seen.has(record.id)) nextErrors[record.id] = 'Duplicate record ID.'
      else if (!record.content.trim()) nextErrors[record.id] = 'Content cannot be empty.'
      else if (length > memory.editPolicy.maxCharsPerRecord) {
        nextErrors[record.id] = `Maximum ${memory.editPolicy.maxCharsPerRecord} characters.`
      }
      seen.add(record.id)
    }
    if (total > memory.editPolicy.maxTotalChars) {
      nextErrors._global = `This update cannot exceed ${memory.editPolicy.maxTotalChars} characters in total.`
    }
    if (!changedRecords.length) nextErrors._global = 'There are no changes to save.'
    setFieldErrors(nextErrors)
    return Object.keys(nextErrors).length === 0
  }

  const submitChanges = () => {
    if (!validateChanges() || submitting || pendingOperation) return
    const operation = createOperation({
      type: 'update',
      sessionId,
      body: { baseVersion: memory.memoryVersion, records: changedRecords }
    })
    setPendingOperation(operation)
    runOperation(operation)
  }

  const startRollback = () => {
    if (!memory?.fullPropagationSupported || !memory?.canRollback || submitting || pendingOperation) return
    const operation = createOperation({
      type: 'rollback',
      sessionId,
      body: { currentVersion: memory.memoryVersion }
    })
    setPendingOperation(operation)
    runOperation(operation)
  }

  const runOperation = async (operation) => {
    if (!operation || operation.sessionId !== sessionId) return
    abortCurrentRequest()
    window.clearTimeout(retryTimerRef.current)
    retryTimerRef.current = null
    const generation = generationRef.current
    const request = createTimedController(WRITE_TIMEOUT_MS)
    controllerRef.current = request.controller
    setSubmitting(true)
    setError(null)
    setFieldErrors({})
    try {
      const common = {
        sessionId: operation.sessionId,
        idempotencyKey: operation.key,
        signal: request.controller.signal
      }
      const result = operation.type === 'update'
        ? await updateThirtySecondMemories({ ...common, ...operation.body })
        : await rollbackThirtySecondMemories({ ...common, ...operation.body })
      if (generation !== generationRef.current || result.sessionId !== operation.sessionId || operation.sessionId !== sessionId) return
      setPendingOperation(null)
      installMemory(result.memory)
      setNotice(formatMutationSuccess(result.message, operation.type))
      setOpen(false)
      const target = { memory: result.memory, graphUpdate: result.graphUpdate, propagation: result.propagation }
      setGraphTarget(target)
      setGraphState({ status: 'refreshing', error: null })
      publish({ sessionId, memory: result.memory, propagation: result.propagation, graph: null, graphEtag: '', graphStatus: 'refreshing' })
      refreshGraph(target, 0)
    } catch (operationError) {
      if (generation !== generationRef.current) return
      const normalized = normalizeClientError(operationError, request.didTimeout())
      if (normalized.code === 'memory_update_in_progress') {
        const attempt = operation.attempt || 0
        const nextOperation = Object.freeze({ ...operation, attempt: attempt + 1 })
        setPendingOperation(nextOperation)
        if (attempt < PENDING_RETRY_DELAYS_MS.length) {
          retryTimerRef.current = window.setTimeout(
            () => runOperation(nextOperation),
            PENDING_RETRY_DELAYS_MS[attempt]
          )
          setError({ ...normalized, message: 'The server is still processing. Checking the result with the same idempotency key.' })
        } else {
          setError({ ...normalized, message: 'The result is not confirmed. Continue checking with the original request.', outcomeUnknown: true })
        }
      } else if (normalized.outcomeUnknown) {
        setPendingOperation(operation)
        setError(normalized)
      } else if (RETRYABLE_DERIVATION_CODES.has(normalized.code)) {
        setPendingOperation(operation)
        setError({ ...normalized, retryableRebuild: true })
      } else if (['memory_version_conflict', 'rollback_unavailable', 'idempotency_key_conflict'].includes(normalized.code)) {
        setPendingOperation(null)
        setSubmitting(false)
        await loadMemory({ preserveNotice: true })
        setError(normalized)
      } else {
        setPendingOperation(null)
        const recordId = normalized.details?.recordId
        if (recordId) {
          setFieldErrors((current) => ({
            ...current,
            [recordId]: formatMemoryFieldError(normalized)
          }))
        }
        setError(normalized)
      }
    } finally {
      request.cleanup()
      if (controllerRef.current === request.controller) controllerRef.current = null
      if (generation === generationRef.current) setSubmitting(false)
    }
  }

  const refreshGraph = async (target = graphTarget, attempt = 0) => {
    if (!target || !sessionId) return
    window.clearTimeout(graphTimerRef.current)
    const generation = generationRef.current
    const request = createTimedController(GET_TIMEOUT_MS)
    try {
      setGraphState({ status: 'refreshing', error: null })
      const result = await fetchLongTermMemoryGraph({ sessionId, etag: '', signal: request.controller.signal })
      if (generation !== generationRef.current) return
      assertGraphMatches(result.graph, target.graphUpdate, target.propagation)
      setGraphState({ status: 'ready', error: null })
      publish({
        sessionId,
        memory: target.memory,
        propagation: target.propagation,
        graph: result.graph,
        graphEtag: result.etag,
        graphStatus: 'ready'
      })
    } catch (graphError) {
      if (generation !== generationRef.current) return
      const normalized = normalizeClientError(graphError, request.didTimeout())
      setGraphState({ status: 'error', error: normalized })
      publish({ sessionId, memory: target.memory, propagation: target.propagation, graph: null, graphEtag: '', graphStatus: 'error', graphError: normalized })
      if (attempt < GRAPH_RETRY_DELAYS_MS.length && normalized.code === 'memory_component_lagging') {
        graphTimerRef.current = window.setTimeout(
          () => refreshGraph(target, attempt + 1),
          GRAPH_RETRY_DELAYS_MS[attempt]
        )
      }
    } finally {
      request.cleanup()
    }
  }

  const discardPendingOperation = async () => {
    abortCurrentRequest()
    window.clearTimeout(retryTimerRef.current)
    retryTimerRef.current = null
    setPendingOperation(null)
    setSubmitting(false)
    setError(null)
    setNotice('')
    await loadMemory()
  }

  const canRetryPending = pendingOperation && !submitting && !retryTimerRef.current
  const canDiscardPending = canRetryPending && (
    error?.outcomeUnknown || error?.retryableRebuild || error?.code === 'memory_update_in_progress'
  )
  const retryPendingLabel = error?.retryableRebuild ? 'Retry rebuild' : 'Continue checking'
  const operationBlocking = submitting || !!retryTimerRef.current
  const canRollback = !!memory?.fullPropagationSupported && !!memory?.canRollback && !pendingOperation

  return (
    <>
      <section className="current-memory-action" aria-label="Current Session long-term memory actions">
        <button
          ref={openerRef}
          className="icon-button secondary current-memory-edit-button"
          type="button"
          disabled={!sessionId || submitting}
          onClick={openEditor}
        >
          <Pencil size={16} />
          <span>Edit Current Session Long-Term Memory</span>
        </button>

        {submitting && !open && (
          <div className="current-memory-notice" role="status">
            <span className="memory-spinner" />
            <span>Rebuilding complete long-term memory and knowledge graphs…</span>
          </div>
        )}

        {notice && (
          <div className="current-memory-notice" role="status">
            <span>{notice}</span>
            {canRollback && (
              <button className="icon-button secondary" type="button" onClick={startRollback}>
                <RotateCcw size={15} />
                Undo Changes
              </button>
            )}
          </div>
        )}

        {graphState.status === 'error' && (
          <div className="current-memory-warning" role="status">
            <AlertTriangle size={16} />
            <span>Memory updated. Graph is still refreshing.</span>
            <button className="icon-button secondary" type="button" onClick={() => refreshGraph(graphTarget, 0)}>
              <RefreshCw size={15} />
              Retry Graph
            </button>
          </div>
        )}

        {!open && error && (
          <div className="inline-error current-memory-error" role="alert">
            <span>{formatMemoryEditError(error)}</span>
            {error.requestId && <small>Request {error.requestId}</small>}
            {canRetryPending && (
              <button className="icon-button secondary" type="button" onClick={() => runOperation(pendingOperation)}>
                {retryPendingLabel}
              </button>
            )}
            {canDiscardPending && (
              <button className="icon-button secondary" type="button" onClick={discardPendingOperation}>
                Discard and reload
              </button>
            )}
          </div>
        )}
      </section>

      {open && createPortal(
        <MemoryEditDialog
          sessionId={sessionId}
          memory={memory}
          drafts={drafts}
          loading={loading}
          submitting={submitting}
          pendingOperation={pendingOperation}
          error={error}
          fieldErrors={fieldErrors}
          canRetryPending={canRetryPending}
          canDiscardPending={canDiscardPending}
          retryPendingLabel={retryPendingLabel}
          operationBlocking={operationBlocking}
          onDraftChange={(id, content) => {
            setDrafts((current) => ({ ...current, [id]: content }))
            setFieldErrors((current) => ({ ...current, [id]: '', _global: '' }))
          }}
          onRetryLoad={() => loadMemory()}
          onRetryPending={() => runOperation(pendingOperation)}
          onDiscardPending={discardPendingOperation}
          onRollback={startRollback}
          onSubmit={submitChanges}
          onClose={closeEditor}
        />,
        document.body
      )}
    </>
  )
}

function MemoryEditDialog({
  sessionId,
  memory,
  drafts,
  loading,
  submitting,
  pendingOperation,
  error,
  fieldErrors,
  canRetryPending,
  canDiscardPending,
  retryPendingLabel,
  operationBlocking,
  onDraftChange,
  onRetryLoad,
  onRetryPending,
  onDiscardPending,
  onRollback,
  onSubmit,
  onClose
}) {
  const titleId = useId()
  const dialogRef = useRef(null)
  const closeRef = useRef(null)
  const hasLongTermMemory = Number(memory?.counts?.total || 0) > 0
  const hasEditableRecord = !!memory?.episodic?.['30sec']?.some((record) => record.editable)

  useEffect(() => {
    const previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    const frame = requestAnimationFrame(() => closeRef.current?.focus())
    return () => {
      cancelAnimationFrame(frame)
      document.body.style.overflow = previousOverflow
    }
  }, [])

  const handleKeyDown = (event) => {
    if (event.key === 'Escape') {
      event.preventDefault()
      if (!operationBlocking) onClose()
      return
    }
    trapDialogFocus(event, dialogRef.current)
  }

  return (
    <div className="memory-dialog-overlay current-memory-dialog-overlay fade-in" onMouseDown={(event) => {
      if (event.target === event.currentTarget && !operationBlocking) onClose()
    }}>
      <section
        ref={dialogRef}
        className="current-memory-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        tabIndex={-1}
        onKeyDown={handleKeyDown}
      >
        <header className="current-memory-dialog-header">
          <div>
            <span>Current Session Long-Term Memory</span>
            <h2 id={titleId}>{sessionId}</h2>
            {memory && <small>M_lt v{memory.memoryVersion}</small>}
          </div>
          <button ref={closeRef} className="icon-button secondary" type="button" disabled={operationBlocking} aria-label="Close" onClick={onClose}>
            <X size={17} />
          </button>
        </header>

        <div className="current-memory-dialog-body">
          {loading && !memory && <div className="memory-loading"><span className="memory-spinner" />Loading long-term memory…</div>}
          {error && (
            <div className="inline-error current-memory-error" role="alert">
              <span>{formatMemoryEditError(error)}</span>
              {error.requestId && <small>Request {error.requestId}</small>}
              {!memory && !pendingOperation && <button className="icon-button secondary" type="button" onClick={onRetryLoad}>Reload</button>}
              {canRetryPending && <button className="icon-button secondary" type="button" onClick={onRetryPending}>{retryPendingLabel}</button>}
              {canDiscardPending && <button className="icon-button secondary" type="button" onClick={onDiscardPending}>Discard and reload</button>}
            </div>
          )}

          {submitting && (
            <div className="memory-loading" role="status">
              <span className="memory-spinner" />
              Rebuilding complete long-term memory and knowledge graphs…
            </div>
          )}

          {memory && (
            <>
              {!hasLongTermMemory ? (
                <div className="memory-empty current-memory-empty" role="status">No long-term memory available.</div>
              ) : !memory.fullPropagationSupported ? (
                <div className="current-memory-warning" role="status">
                  <AlertTriangle size={16} />
                  <span>Full memory propagation is not available on the current backend.</span>
                </div>
              ) : !memory.editSupported && (
                <div className="current-memory-warning" role="status">
                  <AlertTriangle size={16} />
                  <span>Memory editing is not available for this Session.</span>
                </div>
              )}
              {hasLongTermMemory && (
                <>
                  <section className="current-memory-edit-section">
                    <div className="current-memory-section-heading">
                      <div>
                        <span>Editable scope</span>
                        <h3>30-Second Memory</h3>
                      </div>
                      <small>{memory.editPolicy.maxCharsPerRecord} per record · {memory.editPolicy.maxTotalChars} characters per update</small>
                    </div>
                    {!memory.episodic['30sec'].length && <div className="memory-empty">No 30-second memory available.</div>}
                    <div className="current-memory-record-list">
                      {memory.episodic['30sec'].map((record) => (
                        <ThirtySecondEditor
                          key={record.id}
                          record={record}
                          value={drafts[record.id] ?? record.content}
                          maxLength={memory.editPolicy.maxCharsPerRecord}
                          disabled={submitting || !!pendingOperation}
                          error={fieldErrors[record.id]}
                          onChange={(content) => onDraftChange(record.id, content)}
                        />
                      ))}
                    </div>
                    {fieldErrors._global && <div className="inline-error" role="alert">{fieldErrors._global}</div>}
                  </section>

                  <ReadonlyMemory memory={memory} />
                </>
              )}
            </>
          )}
        </div>

        <footer className="current-memory-dialog-footer">
          {memory?.canRollback && (
            <button className="icon-button secondary" type="button" disabled={submitting || !!pendingOperation} onClick={onRollback}>
              <RotateCcw size={15} />
              Undo Last Change
            </button>
          )}
          <span />
          <button className="icon-button secondary" type="button" disabled={operationBlocking} onClick={onClose}>Cancel</button>
          <button className="current-memory-confirm" type="button" disabled={!memory?.fullPropagationSupported || !memory?.editSupported || !hasEditableRecord || submitting || !!pendingOperation} onClick={onSubmit}>
            {submitting && <span className="button-spinner" />}
            {submitting ? 'Rebuilding…' : 'Save Changes'}
          </button>
        </footer>
      </section>
    </div>
  )
}

function ThirtySecondEditor({ record, value, maxLength, disabled, error, onChange }) {
  const length = codePointLength(value)
  const reason = !record.editable ? formatDisabledReason(record.editDisabledReason) : ''
  return (
    <article className={`current-memory-record ${record.editable ? '' : 'is-readonly'}`}>
      <div className="current-memory-record-meta">
        <code>{record.id}</code>
        <span>{length} / {maxLength}</span>
      </div>
      {record.editable ? (
        <textarea
          value={value}
          disabled={disabled}
          aria-label={`Edit 30-second memory ${record.id}`}
          aria-invalid={!!error}
          onChange={(event) => onChange(event.target.value)}
        />
      ) : (
        <p>{record.content || '—'}</p>
      )}
      {reason && <div className="current-memory-readonly-reason">Read-only: {reason}</div>}
      {error && <div className="current-memory-field-error" role="alert">{error}</div>}
      {record.data && <ReadonlyValue value={record.data} root />}
    </article>
  )
}

function ReadonlyMemory({ memory }) {
  const groups = [
    ['3-Minute Memory', memory.episodic['3min']],
    ['10-Minute Memory', memory.episodic['10min']],
    ['1-Hour Memory', memory.episodic['1h']],
    ['Semantic Memory', memory.semantic],
    ['Visual Memory', memory.visual]
  ]
  return (
    <section className="current-memory-readonly-section">
      <h3>Other Long-Term Memory (Read-Only)</h3>
      {groups.map(([label, records]) => (
        <details key={label}>
          <summary>{label}<span>{records.length} records</span></summary>
          {records.length ? (
            <div className="memory-list">
              {records.map((record) => <MemoryRecordCard memory={record} key={record.id} />)}
            </div>
          ) : <div className="memory-empty is-compact">No records.</div>}
        </details>
      ))}
    </section>
  )
}

function createTimedController(timeoutMs) {
  const controller = new AbortController()
  let timedOut = false
  const timer = window.setTimeout(() => {
    timedOut = true
    controller.abort()
  }, timeoutMs)
  return {
    controller,
    didTimeout: () => timedOut,
    cleanup: () => window.clearTimeout(timer)
  }
}

function createIdempotencyKey() {
  if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID()
  if (!globalThis.crypto?.getRandomValues) {
    const error = new Error('Secure random generation is unavailable.')
    error.code = 'secure_random_unavailable'
    throw error
  }
  const bytes = globalThis.crypto.getRandomValues(new Uint8Array(16))
  bytes[6] = (bytes[6] & 0x0f) | 0x40
  bytes[8] = (bytes[8] & 0x3f) | 0x80
  const hex = Array.from(bytes, (value) => value.toString(16).padStart(2, '0')).join('')
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`
}

function createOperation({ type, sessionId, body }) {
  const immutableBody = type === 'update'
    ? Object.freeze({
        baseVersion: body.baseVersion,
        records: Object.freeze(body.records.map((record) => Object.freeze({
          id: record.id,
          content: record.content
        })))
      })
    : Object.freeze({ currentVersion: body.currentVersion })
  return Object.freeze({
    type,
    sessionId,
    key: createIdempotencyKey(),
    body: immutableBody,
    attempt: 0
  })
}

function codePointLength(value) {
  return Array.from(String(value || '')).length
}

function normalizeClientError(error, timedOut) {
  if (timedOut || error?.name === 'TypeError') {
    return {
      ...error,
      code: timedOut ? 'request_timeout' : 'network_error',
      message: timedOut ? 'The request timed out; the update result is not confirmed.' : 'The network failed; the update result is not confirmed.',
      outcomeUnknown: true,
      requestId: error?.requestId || ''
    }
  }
  return error
}

function assertGraphMatches(graph, expected, propagation) {
  const versions = graph?.componentVersions || {}
  const expectedVersions = expected?.componentVersions || {}
  const graphVersions = graph?.graphVersions || {}
  const expectedGraphVersions = expected?.graphVersions || {}
  if (
    graph?.memoryVersion !== expected?.memoryVersion
    || graph?.memoryVersion !== propagation?.targetMemoryVersion
    || versions.episodic !== expectedVersions.episodic
    || versions.graph !== expectedVersions.graph
    || versions.semantic !== expectedVersions.semantic
    || graphVersions.episodicGraph !== expectedGraphVersions.episodicGraph
    || graphVersions.semanticGraph !== expectedGraphVersions.semanticGraph
    || graphVersions.episodicGraph !== propagation?.graphs?.episodic?.version
    || graphVersions.semanticGraph !== propagation?.graphs?.semantic?.version
  ) {
    const error = new Error('Graph has not reached the published Memory version.')
    error.status = 503
    error.code = 'memory_component_lagging'
    throw error
  }
}

function formatDisabledReason(code) {
  const labels = {
    missing_stable_id: 'Stable record ID is missing',
    duplicate_stable_id: 'Stable record ID is duplicated',
    unsupported_source_record: 'Source record does not support editing',
    missing_editable_text_field: 'No editable text field is available',
    backend_edit_not_supported: 'The editing API is not enabled by the backend',
    full_propagation_not_supported: 'Full memory propagation is not available'
  }
  return labels[code] || code || 'This record cannot be edited'
}

function formatMemoryEditError(error) {
  const labels = {
    session_not_found: 'This Session does not exist.',
    memory_not_ready: 'No long-term memory available.',
    memory_version_conflict: 'The memory version changed. The latest content was reloaded; please edit again.',
    rollback_unavailable: 'The one-time rollback has already been used.',
    idempotency_key_conflict: 'The idempotency key conflicts with another request. Memory was resynchronized.',
    memory_update_in_progress: 'The server is still processing this request.',
    memory_update_failed: 'The server could not update Memory or Graph. The previous version is unchanged.',
    semantic_rebuild_unavailable: 'Semantic rebuilding is unavailable. Retry the rebuild with the same request.',
    memory_derivation_failed: 'A derived memory component failed to rebuild. Retry with the same request.',
    memory_too_long: 'The update exceeds the server length limit.',
    invalid_thirty_second_memory: 'The 30-second memory content is invalid.',
    request_timeout: 'The request timed out; the update result is not confirmed.',
    network_error: 'The network failed; the update result is not confirmed.',
    invalid_memory_mutation_response: 'The server returned inconsistent Memory versions.'
  }
  const component = safeDerivationComponent(error?.details?.component)
  const message = labels[error?.code] || 'Unable to process the current long-term memory.'
  return component ? `${message} Component: ${component}.` : message
}

function safeDerivationComponent(value) {
  const components = new Set([
    '30sec',
    '3min',
    '10min',
    '1h',
    'multiscale',
    'sidecar',
    'semantic',
    'openie',
    'episodic_graph',
    'semantic_graph',
    'query_runtime',
    'snapshot'
  ])
  return components.has(value) ? value : (value ? 'derived component' : '')
}

function formatMemoryFieldError(error) {
  const details = error?.details || {}
  if (error?.code === 'memory_too_long' && details.limit) {
    return `The content exceeds the ${details.limit}-character limit.`
  }
  if (error?.code === 'invalid_thirty_second_memory' && details.field === 'content') {
    return 'This memory content is invalid or empty.'
  }
  return formatMemoryEditError(error)
}

function formatMutationSuccess(_message, operationType) {
  if (operationType === 'rollback') {
    return 'Memory rollback completed.'
  }
  return 'Memory updated.'
}

function trapDialogFocus(event, root) {
  if (event.key !== 'Tab') return
  const focusable = Array.from(root?.querySelectorAll([
    'button:not([disabled])',
    'textarea:not([disabled])',
    'summary',
    '[tabindex]:not([tabindex="-1"])'
  ].join(',')) || [])
  if (!focusable.length) return
  const first = focusable[0]
  const last = focusable[focusable.length - 1]
  if (event.shiftKey && document.activeElement === first) {
    event.preventDefault()
    last.focus()
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault()
    first.focus()
  }
}
