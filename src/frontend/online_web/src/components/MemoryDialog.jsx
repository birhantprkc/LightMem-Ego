import { ChevronDown, ChevronUp, X } from 'lucide-react'
import { lazy, memo, Suspense, useCallback, useEffect, useId, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { fetchLongTermMemories } from '../api/lightmem_egoApi.js'

const MemoryGraphView = lazy(() => import('./memory-graph/MemoryGraphView.jsx'))

const PAGE_SIZE = 100
const EPISODIC_GROUPS = [
  ['30sec', '30 seconds'],
  ['3min', '3 minutes'],
  ['10min', '10 minutes'],
  ['1h', '1 hour']
]
const GROUP_IDS = [
  ...EPISODIC_GROUPS.map(([key]) => `episodic-${key}`),
  'semantic',
  'visual'
]

function createVisibleCounts() {
  return Object.fromEntries(GROUP_IDS.map((key) => [key, PAGE_SIZE]))
}

function createExpandedGroups(memory) {
  const groups = new Set()
  const episodicCount = EPISODIC_GROUPS.reduce((total, [key]) => total + (memory?.episodic?.[key]?.length || 0), 0)
  if (episodicCount > 0) groups.add('episodic')
  for (const [key] of EPISODIC_GROUPS) {
    if (memory?.episodic?.[key]?.length) groups.add(`episodic-${key}`)
  }
  if (memory?.semantic?.length) groups.add('semantic')
  if (memory?.visual?.length) groups.add('visual')
  return groups
}

export default function MemoryDialog({
  session,
  cachedMemory,
  authoritativeUpdate,
  openerElement,
  fallbackFocusElement,
  onMemoryLoaded,
  onSessionUnavailable,
  onClose
}) {
  const [activeTab, setActiveTab] = useState('graph')
  const [memory, setMemory] = useState(cachedMemory)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [expandedGroups, setExpandedGroups] = useState(() => createExpandedGroups(cachedMemory))
  const [visibleCounts, setVisibleCounts] = useState(createVisibleCounts)
  const titleId = useId()
  const dialogRef = useRef(null)
  const closeButtonRef = useRef(null)
  const scrollRootRef = useRef(null)
  const requestControllerRef = useRef(null)
  const requestGenerationRef = useRef(0)
  const mountedRef = useRef(true)
  const onMemoryLoadedRef = useRef(onMemoryLoaded)
  const onSessionUnavailableRef = useRef(onSessionUnavailable)

  onMemoryLoadedRef.current = onMemoryLoaded
  onSessionUnavailableRef.current = onSessionUnavailable

  const loadMemory = useCallback(async ({ force = false } = {}) => {
    if (requestControllerRef.current && !force) return
    if (force) requestControllerRef.current?.abort()

    const controller = new AbortController()
    const generation = ++requestGenerationRef.current
    requestControllerRef.current = controller
    setLoading(true)
    setError(null)

    try {
      const result = await fetchLongTermMemories({
        sessionId: session.sessionId,
        signal: controller.signal
      })
      if (
        !mountedRef.current
        || generation !== requestGenerationRef.current
        || result.sessionId !== session.sessionId
      ) return

      setMemory(result)
      setExpandedGroups(createExpandedGroups(result))
      setVisibleCounts(createVisibleCounts())
      onMemoryLoadedRef.current(result)
    } catch (loadError) {
      if (loadError?.name === 'AbortError') return
      if (!mountedRef.current || generation !== requestGenerationRef.current) return
      if (loadError?.code === 'session_not_found' || loadError?.status === 404) {
        onSessionUnavailableRef.current(session.sessionId)
        return
      }
      setError(loadError)
    } finally {
      if (requestControllerRef.current === controller) requestControllerRef.current = null
      if (mountedRef.current && generation === requestGenerationRef.current) setLoading(false)
    }
  }, [session.sessionId])

  useEffect(() => {
    mountedRef.current = true
    return () => {
      mountedRef.current = false
      requestControllerRef.current?.abort()
      requestControllerRef.current = null
      requestGenerationRef.current += 1
    }
  }, [cachedMemory, loadMemory])

  const showRecords = () => {
    setActiveTab('records')
    if (!memory && !requestControllerRef.current) loadMemory()
  }

  useEffect(() => {
    const authoritativeMemory = authoritativeUpdate?.memory
    if (!authoritativeMemory || authoritativeMemory.sessionId !== session.sessionId) return
    setMemory(authoritativeMemory)
    setExpandedGroups(createExpandedGroups(authoritativeMemory))
    setVisibleCounts(createVisibleCounts())
  }, [authoritativeUpdate?.revision, session.sessionId])

  useEffect(() => {
    const previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    const focusFrame = requestAnimationFrame(() => closeButtonRef.current?.focus())
    return () => {
      cancelAnimationFrame(focusFrame)
      document.body.style.overflow = previousOverflow
      const focusTarget = openerElement?.isConnected ? openerElement : fallbackFocusElement
      requestAnimationFrame(() => focusTarget?.focus())
    }
  }, [fallbackFocusElement, openerElement])

  const toggleGroup = (groupId) => {
    setExpandedGroups((current) => {
      const next = new Set(current)
      if (next.has(groupId)) next.delete(groupId)
      else next.add(groupId)
      return next
    })
  }

  const showMore = (groupId, total) => {
    setVisibleCounts((current) => ({
      ...current,
      [groupId]: Math.min(total, (current[groupId] || PAGE_SIZE) + PAGE_SIZE)
    }))
  }

  const handleKeyDown = (event) => {
    if (event.key === 'Escape') {
      event.preventDefault()
      onClose()
      return
    }
    if (event.key !== 'Tab') return

    const focusable = Array.from(dialogRef.current?.querySelectorAll([
      'button:not([disabled])',
      'a[href]',
      'input:not([disabled])',
      'select:not([disabled])',
      'textarea:not([disabled])',
      'summary',
      '[tabindex]:not([tabindex="-1"])'
    ].join(',')) || []).filter((element) => !element.closest('[hidden]'))

    if (!focusable.length) {
      event.preventDefault()
      dialogRef.current?.focus()
      return
    }

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

  const formattedError = error ? formatMemoryError(error) : ''
  const retryAllowed = error && error?.status !== 413 && error?.code !== 'memory_response_too_large'

  return createPortal(
    <div
      className="memory-dialog-overlay fade-in"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose()
      }}
    >
      <section
        ref={dialogRef}
        className="memory-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        tabIndex={-1}
        onKeyDown={handleKeyDown}
      >
        <header className="memory-dialog-header">
          <div className="memory-dialog-title-block">
            <div>
              <span>Complete business-level M_lt</span>
              <h2 id={titleId}>{session.sessionId}</h2>
            </div>
            <div className="memory-dialog-version-chips" aria-label="Memory component versions">
              <span>M_lt v{session.memoryVersion}</span>
              <span>Episodic {formatVersion(session.componentVersions?.episodic)}</span>
              <span>Semantic {formatVersion(session.componentVersions?.semantic)}</span>
            </div>
          </div>
          <button ref={closeButtonRef} className="icon-button secondary" type="button" aria-label="Close Memory" onClick={onClose}>
            <X size={17} />
            <span>Close</span>
          </button>
        </header>

        <div className="memory-dialog-tabs" role="tablist" aria-label="Long-term memory detail view">
          <button
            id={`${titleId}-graph-tab`}
            type="button"
            role="tab"
            aria-selected={activeTab === 'graph'}
            aria-controls={`${titleId}-graph-panel`}
            className={activeTab === 'graph' ? 'active' : ''}
            onClick={() => setActiveTab('graph')}
          >
            Graph
          </button>
          <button
            id={`${titleId}-records-tab`}
            type="button"
            role="tab"
            aria-selected={activeTab === 'records'}
            aria-controls={`${titleId}-records-panel`}
            className={activeTab === 'records' ? 'active' : ''}
            onClick={showRecords}
          >
            Records
          </button>
        </div>

        <div ref={scrollRootRef} className={`memory-dialog-body is-${activeTab}`}>
          <div
            id={`${titleId}-graph-panel`}
            role="tabpanel"
            aria-labelledby={`${titleId}-graph-tab`}
            hidden={activeTab !== 'graph'}
          >
            <Suspense fallback={(
              <div className="memory-graph-request-state" aria-live="polite">
                <span className="memory-spinner" />
                <strong>Loading graph viewer…</strong>
              </div>
            )}>
              <MemoryGraphView
                session={session}
                authoritativeUpdate={authoritativeUpdate}
                onSessionUnavailable={onSessionUnavailableRef.current}
              />
            </Suspense>
          </div>

          <div
            id={`${titleId}-records-panel`}
            role="tabpanel"
            aria-labelledby={`${titleId}-records-tab`}
            hidden={activeTab !== 'records'}
          >
            {loading && !memory && (
              <div className="memory-loading" aria-live="polite">
                <span className="memory-spinner" />
                Loading complete long-term memory…
              </div>
            )}

            {formattedError && (
              <div className="inline-error memory-error" role="alert">
                <span>{formattedError}</span>
                {retryAllowed && (
                  <button className="icon-button secondary" type="button" onClick={() => loadMemory({ force: true })}>Retry</button>
                )}
              </div>
            )}

            {memory && (
              <MemoryContent
                memory={memory}
                expandedGroups={expandedGroups}
                visibleCounts={visibleCounts}
                scrollRootRef={scrollRootRef}
                onToggleGroup={toggleGroup}
                onShowMore={showMore}
              />
            )}

            {!loading && !memory && !formattedError && (
              <div className="memory-empty">Open Records to load the complete long-term memory.</div>
            )}
          </div>
        </div>
      </section>
    </div>,
    document.body
  )
}

function MemoryContent({ memory, expandedGroups, visibleCounts, scrollRootRef, onToggleGroup, onShowMore }) {
  const overviewItems = [
    ['Total', memory.counts.total],
    ['Episodic', memory.counts.episodic],
    ['Semantic', memory.counts.semantic],
    ['Visual', memory.counts.visual]
  ]

  return (
    <>
      <div className="memory-panel-heading">
        <div>
          <span>Complete business-level memory</span>
          <strong>M_lt · v{memory.memoryVersion}</strong>
          <small>{formatUpdatedAt(memory.updatedAt)}</small>
        </div>
      </div>

      <div className="memory-overview" aria-label="Long-term memory overview">
        {overviewItems.map(([label, value]) => (
          <div className="memory-overview-item" key={label}>
            <span>{label}</span>
            <strong>{value}</strong>
          </div>
        ))}
      </div>

      <div className="memory-status-row">
        <span className={`memory-status-badge ${memory.qaAligned ? 'is-ready' : 'is-warning'}`}>
          {memory.qaAligned ? 'QA aligned' : 'Legacy M_lt'}
        </span>
        {Object.entries(memory.availability || {}).map(([key, value]) => (
          <span className={`memory-status-badge ${value === 'ready' ? 'is-ready' : 'is-muted'}`} key={key}>
            {humanizeKey(key)}: {humanizeKey(value)}
          </span>
        ))}
      </div>

      {!memory.qaAligned && (
        <div className="memory-notice is-warning">
          Legacy M_lt is displayed and may not match the memory currently used by QA.
        </div>
      )}
      {memory.fieldTruncation && (
        <div className="memory-notice">
          Some repeated metadata arrays were truncated by the server. All Memory records are included.
        </div>
      )}

      <MemorySection
        groupId="episodic"
        title="Episodic Memory"
        count={memory.counts.episodic}
        availability={memory.availability?.episodic}
        expanded={expandedGroups.has('episodic')}
        onToggle={onToggleGroup}
      >
        {EPISODIC_GROUPS.map(([key, label]) => {
          const groupId = `episodic-${key}`
          const records = memory.episodic[key]
          return (
            <MemorySection
              compact
              groupId={groupId}
              title={label}
              count={memory.counts.episodicByGranularity?.[key] ?? records.length}
              availability={memory.availability?.episodic}
              expanded={expandedGroups.has(groupId)}
              onToggle={onToggleGroup}
              key={key}
            >
              <MemoryList
                groupId={groupId}
                items={records}
                visibleCount={visibleCounts[groupId] || PAGE_SIZE}
                emptyLabel={`No ${label} episodic Memory in this Session.`}
                scrollRootRef={scrollRootRef}
                onShowMore={onShowMore}
              />
            </MemorySection>
          )
        })}
      </MemorySection>

      <MemorySection
        groupId="semantic"
        title="Semantic Memory"
        count={memory.counts.semantic}
        availability={memory.availability?.semantic}
        expanded={expandedGroups.has('semantic')}
        onToggle={onToggleGroup}
      >
        <MemoryList
          groupId="semantic"
          items={memory.semantic}
          visibleCount={visibleCounts.semantic || PAGE_SIZE}
          emptyLabel="No Semantic Memory in this Session."
          scrollRootRef={scrollRootRef}
          onShowMore={onShowMore}
        />
      </MemorySection>

      <MemorySection
        groupId="visual"
        title="Visual Memory"
        count={memory.counts.visual}
        availability={memory.availability?.visual}
        expanded={expandedGroups.has('visual')}
        onToggle={onToggleGroup}
      >
        <MemoryList
          groupId="visual"
          items={memory.visual}
          visibleCount={visibleCounts.visual || PAGE_SIZE}
          emptyLabel="No Visual Memory in this Session."
          scrollRootRef={scrollRootRef}
          onShowMore={onShowMore}
        />
      </MemorySection>
    </>
  )
}

function MemorySection({ groupId, title, count, availability, expanded, onToggle, compact = false, children }) {
  return (
    <section className={`memory-section ${compact ? 'is-compact' : ''}`}>
      <button
        className="memory-section-toggle"
        type="button"
        aria-expanded={expanded}
        onClick={() => onToggle(groupId)}
      >
        <span>
          <strong>{title}</strong>
          <small>{availability === 'not_available' ? 'Not available' : `${count ?? 0} records`}</small>
        </span>
        {expanded ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
      </button>
      {expanded && (
        <div className="memory-section-content fade-in">
          {availability === 'not_available'
            ? <div className="memory-empty is-compact">This component is not available for this Session.</div>
            : children}
        </div>
      )}
    </section>
  )
}

function MemoryList({ groupId, items, visibleCount, emptyLabel, scrollRootRef, onShowMore }) {
  const sentinelRef = useRef(null)
  const shownItems = items.slice(0, visibleCount)
  const hasMore = shownItems.length < items.length

  useEffect(() => {
    if (!hasMore || !sentinelRef.current || typeof IntersectionObserver === 'undefined') return undefined
    const observer = new IntersectionObserver((entries) => {
      if (entries.some((entry) => entry.isIntersecting)) onShowMore(groupId, items.length)
    }, { root: scrollRootRef.current, rootMargin: '0px' })
    observer.observe(sentinelRef.current)
    return () => observer.disconnect()
  }, [groupId, hasMore, items.length, onShowMore, scrollRootRef])

  if (!items.length) return <div className="memory-empty is-compact">{emptyLabel}</div>
  return (
    <>
      <div className="memory-list">
        {shownItems.map((item) => <MemoryRecordCard memory={item} key={item.id} />)}
      </div>
      <div className="memory-local-count">Showing {shownItems.length} of {items.length}</div>
      {hasMore && (
        <div ref={sentinelRef} className="memory-local-sentinel">
          <button className="icon-button secondary" type="button" onClick={() => onShowMore(groupId, items.length)}>
            Show next {Math.min(PAGE_SIZE, items.length - shownItems.length)}
          </button>
        </div>
      )}
    </>
  )
}

export const MemoryRecordCard = memo(function MemoryRecordCard({ memory }) {
  const timeLabel = formatEventTime(memory.eventTime)
  return (
    <article className="memory-card">
      <div className="memory-card-header">
        <div className="memory-card-badges">
          <span className="memory-badge">{humanizeKey(memory.memoryType || 'Memory')}</span>
          {memory.granularity && <span className="memory-badge is-muted">{memory.granularity}</span>}
          {memory.status && <span className="memory-badge is-muted">{humanizeKey(memory.status)}</span>}
        </div>
        {memory.confidence !== null && memory.confidence !== undefined && (
          <span className="memory-confidence">Confidence {formatConfidence(memory.confidence)}</span>
        )}
      </div>
      {timeLabel && <div className="memory-time">{timeLabel}</div>}
      <p className="memory-content">{memory.content || '—'}</p>
      {memory.data && <ReadonlyValue value={memory.data} root />}
    </article>
  )
})

export function ReadonlyValue({ value, root = false }) {
  if (value === null || value === undefined || value === '') return <span className="memory-param-value">—</span>

  if (Array.isArray(value)) {
    if (!value.length) return <span className="memory-param-value">—</span>
    const content = <MemoryArray items={value} />
    if (value.length <= 4) return content
    return (
      <details className="memory-value-details">
        <summary>{value.length} items</summary>
        {content}
      </details>
    )
  }

  if (typeof value === 'object') {
    if (Array.isArray(value.items) && Object.prototype.hasOwnProperty.call(value, 'truncated')) {
      return (
        <div className="memory-truncated-value">
          <div className="memory-truncation-note">
            Showing {value.returnedCount ?? value.items.length} of {value.originalCount ?? value.items.length} items.
          </div>
          <ReadonlyValue value={value.items} />
        </div>
      )
    }
    const entries = Object.entries(value)
    if (!entries.length) return <span className="memory-param-value">—</span>
    return (
      <div className={`memory-param-list ${root ? 'is-root' : 'is-nested'}`}>
        {entries.map(([key, item]) => (
          <div className="memory-param-row" key={key}>
            <span className="memory-param-key">{humanizeKey(key)}</span>
            <div className="memory-param-value"><ReadonlyValue value={item} /></div>
          </div>
        ))}
      </div>
    )
  }

  return <span className="memory-param-value">{String(value)}</span>
}

function MemoryArray({ items }) {
  return (
    <ul className="memory-array">
      {items.map((item, index) => (
        <li key={`${index}-${primitiveKey(item)}`}><ReadonlyValue value={item} /></li>
      ))}
    </ul>
  )
}

function primitiveKey(value) {
  return typeof value === 'object' ? '' : String(value).slice(0, 32)
}

function humanizeKey(value) {
  return String(value || '')
    .replace(/([a-z0-9])([A-Z])/g, '$1 $2')
    .replace(/[_-]+/g, ' ')
    .replace(/\b\w/g, (character) => character.toUpperCase())
}

function formatEventTime(eventTime) {
  if (!eventTime || typeof eventTime !== 'object') return ''
  const date = formatLooseValue(eventTime.date)
  const start = firstValue(eventTime.startSeconds, eventTime.startTime, eventTime.timestampSeconds, eventTime.timestamp)
  const end = firstValue(eventTime.endSeconds, eventTime.endTime)
  const firstSeen = formatLooseValue(eventTime.firstSeen)
  const lastSeen = formatLooseValue(eventTime.lastSeen)
  if (firstSeen || lastSeen) return [firstSeen, lastSeen].filter(Boolean).join(' – ')
  const range = start !== undefined ? `${formatSeconds(start)}${end !== undefined ? ` – ${formatSeconds(end)}` : ''}` : ''
  return [date, range].filter(Boolean).join(' · ')
}

function firstValue(...values) {
  return values.find((value) => value !== undefined && value !== null && value !== '')
}

function formatSeconds(value) {
  const numeric = Number(value)
  return Number.isFinite(numeric) ? `${numeric.toFixed(numeric % 1 ? 1 : 0)}s` : String(value)
}

function formatLooseValue(value) {
  if (value === undefined || value === null || value === '') return ''
  if (typeof value === 'object') return Object.values(value).filter(Boolean).join(' ')
  return String(value)
}

function formatConfidence(value) {
  const numeric = Number(value)
  return Number.isFinite(numeric) ? numeric.toFixed(2) : String(value)
}

function formatUpdatedAt(value) {
  if (!value) return 'Updated time unavailable'
  const parsed = new Date(value)
  return Number.isNaN(parsed.getTime()) ? String(value) : `Updated ${parsed.toLocaleString()}`
}

function formatVersion(value) {
  return value === null || value === undefined ? 'unknown' : `v${value}`
}

function formatMemoryError(error) {
  const code = error?.code || error?.raw?.error?.code
  if (code === 'invalid_session_id' || error?.status === 400) return 'The Session ID is invalid.'
  if (code === 'session_not_found' || error?.status === 404) return 'The Session does not exist.'
  if (code === 'memory_response_too_large' || error?.status === 413) {
    return "This Session's long-term memory is too large to display safely."
  }
  if (code === 'memory_not_ready') return 'Long-term memory is no longer ready for this Session.'
  if (code === 'memory_snapshot_changing') return 'Long-term memory is being updated. Please retry shortly.'
  if (code === 'memory_component_lagging') return 'Long-term memory components are still being published.'
  if (error?.status === 503) return 'Long-term memory is updating or not ready. Please retry shortly.'
  if (code === 'invalid_memory_view_response') return 'The long-term memory response was incomplete or invalid.'
  return error?.message || 'Unable to load long-term memory.'
}
