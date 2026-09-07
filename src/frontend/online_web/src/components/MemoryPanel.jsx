import { ChevronDown, ChevronUp, Database, RefreshCw } from 'lucide-react'
import { useCallback, useEffect, useRef, useState } from 'react'
import { fetchLongTermMemorySessions } from '../api/lightmem_egoApi.js'
import MemoryDialog from './MemoryDialog.jsx'

const FIRST_PAGE_KEY = '__first_page__'
const CATALOG_PAGE_SIZE = 10
const COMPONENT_KEYS = ['episodic', 'semantic', 'visual']

export default function MemoryPanel({ authoritativeUpdate = null }) {
  const [open, setOpen] = useState(false)
  const [items, setItems] = useState([])
  const [totalReadySessions, setTotalReadySessions] = useState(0)
  const [hasMore, setHasMore] = useState(false)
  const [initialLoading, setInitialLoading] = useState(false)
  const [refreshing, setRefreshing] = useState(false)
  const [catalogError, setCatalogError] = useState('')
  const [catalogBlocked, setCatalogBlocked] = useState(false)
  const [catalogNotice, setCatalogNotice] = useState('')
  const [currentPage, setCurrentPage] = useState(1)
  const [pageInput, setPageInput] = useState('1')
  const [pageError, setPageError] = useState('')
  const [pageLoading, setPageLoading] = useState(false)
  const [targetPage, setTargetPage] = useState(null)
  const [selectedSession, setSelectedSession] = useState(null)
  const [selectedOpener, setSelectedOpener] = useState(null)

  const toggleButtonRef = useRef(null)
  const panelRef = useRef(null)
  const catalogControllerRef = useRef(null)
  const catalogGenerationRef = useRef(0)
  const navigationGenerationRef = useRef(0)
  const catalogRequestSequenceRef = useRef(0)
  const inFlightCursorRef = useRef(null)
  const seenCursorsRef = useRef(new Set())
  const cursorRecoveryUsedRef = useRef(false)
  const catalogLoadedRef = useRef(false)
  const pageOperationRef = useRef(false)
  const lastTargetPageRef = useRef(1)
  const currentPageRef = useRef(1)
  const itemsRef = useRef([])
  const nextCursorRef = useRef(null)
  const hasMoreRef = useRef(false)
  const detailCacheRef = useRef(new Map())
  const mountedRef = useRef(true)

  const replaceItems = useCallback((nextItems) => {
    itemsRef.current = nextItems
    setItems(nextItems)
  }, [])

  const mergeCatalogItems = useCallback((incomingItems, requestSequence) => {
    const merged = [...itemsRef.current]
    const positions = new Map(merged.map((item, index) => [item.sessionId, index]))

    for (const incoming of incomingItems) {
      const position = positions.get(incoming.sessionId)
      const existing = position === undefined ? null : merged[position]
      const cacheEntry = detailCacheRef.current.get(incoming.sessionId)
      let nextItem = existing ? { ...existing, ...incoming } : incoming

      if (cacheEntry?.confirmedRequestSequence >= requestSequence) {
        nextItem = applyAuthoritativeMemory(nextItem, cacheEntry.memory)
      } else if (cacheEntry) {
        if (isCacheCompatible(incoming, cacheEntry)) {
          nextItem = preserveUnknownComponentVersions(nextItem, cacheEntry.memory)
        } else {
          detailCacheRef.current.delete(incoming.sessionId)
        }
      }

      if (position === undefined) {
        positions.set(nextItem.sessionId, merged.length)
        merged.push(nextItem)
      } else {
        merged[position] = nextItem
      }
    }

    replaceItems(merged)
    return merged
  }, [replaceItems])

  const fetchCatalogBatch = useCallback(async ({ cursor = null, mode = 'page' } = {}) => {
    const requestKey = cursor || FIRST_PAGE_KEY
    if (catalogControllerRef.current || inFlightCursorRef.current === requestKey) return { status: 'busy' }

    if (cursor && seenCursorsRef.current.has(cursor)) {
      nextCursorRef.current = null
      hasMoreRef.current = false
      setHasMore(false)
      setCatalogBlocked(true)
      setCatalogError('The server returned a repeated pagination cursor. Refresh the Catalog to continue.')
      return { status: 'loop' }
    }

    const controller = new AbortController()
    const generation = catalogGenerationRef.current
    const requestSequence = ++catalogRequestSequenceRef.current
    catalogControllerRef.current = controller
    inFlightCursorRef.current = requestKey
    setCatalogError('')
    setCatalogBlocked(false)
    if (mode === 'initial') setInitialLoading(true)
    if (mode === 'refresh') setRefreshing(true)

    try {
      const result = await fetchLongTermMemorySessions({ cursor, signal: controller.signal })
      if (!mountedRef.current || generation !== catalogGenerationRef.current) return { status: 'stale' }

      const cursorLoop = !!result.nextCursor && seenCursorsRef.current.has(result.nextCursor)
      if (cursor) seenCursorsRef.current.add(cursor)
      const merged = mergeCatalogItems(result.items, requestSequence)
      catalogLoadedRef.current = true
      setTotalReadySessions(result.totalReadySessions)

      if (cursorLoop) {
        nextCursorRef.current = null
        hasMoreRef.current = false
        setHasMore(false)
        setCatalogBlocked(true)
        setCatalogError('The server returned a cursor that was already loaded. Refresh the Catalog to resync.')
        return { status: 'loop', items: merged }
      }

      nextCursorRef.current = result.nextCursor
      hasMoreRef.current = result.hasMore
      setHasMore(result.hasMore)
      return { status: 'ok', items: merged, result }
    } catch (error) {
      if (error?.name === 'AbortError') return { status: 'aborted' }
      if (!mountedRef.current || generation !== catalogGenerationRef.current) return { status: 'stale' }

      if (error?.code === 'invalid_cursor' || error?.status === 400) {
        if (!cursorRecoveryUsedRef.current) return { status: 'invalid_cursor' }
      }

      if (error?.code === 'invalid_memory_catalog_response') {
        nextCursorRef.current = null
        hasMoreRef.current = false
        setHasMore(false)
        setCatalogBlocked(true)
      }
      setCatalogError(formatCatalogError(error))
      if (error?.code !== 'invalid_memory_catalog_response') setCatalogBlocked(false)
      return { status: 'error', error }
    } finally {
      if (catalogControllerRef.current === controller) catalogControllerRef.current = null
      if (inFlightCursorRef.current === requestKey) inFlightCursorRef.current = null
      if (mountedRef.current && generation === catalogGenerationRef.current) {
        setInitialLoading(false)
        setRefreshing(false)
      }
    }
  }, [mergeCatalogItems])

  const resetAfterInvalidCursor = useCallback(() => {
    cursorRecoveryUsedRef.current = true
    catalogGenerationRef.current += 1
    catalogControllerRef.current = null
    inFlightCursorRef.current = null
    seenCursorsRef.current = new Set()
    catalogLoadedRef.current = false
    nextCursorRef.current = null
    hasMoreRef.current = false
    detailCacheRef.current.clear()
    replaceItems([])
    setSelectedSession(null)
    setSelectedOpener(null)
    setTotalReadySessions(0)
    setHasMore(false)
    currentPageRef.current = 1
    setCurrentPage(1)
    setCatalogError('')
    setCatalogBlocked(false)
    setCatalogNotice('The pagination cursor expired. The Catalog was restarted from the first page.')
  }, [replaceItems])

  const goToPage = useCallback(async (requestedPage, { mode = 'page' } = {}) => {
    if (pageOperationRef.current) return false
    const page = Number(requestedPage)
    if (!Number.isInteger(page) || page < 1) return false

    const navigationGeneration = navigationGenerationRef.current
    pageOperationRef.current = true
    lastTargetPageRef.current = page
    setPageError('')
    setCatalogError('')
    if (mode === 'page') {
      setPageLoading(true)
      setTargetPage(page)
    }

    let shouldRestart = false
    try {
      do {
        shouldRestart = false
        if (!catalogLoadedRef.current) {
          const firstOutcome = await fetchCatalogBatch({ cursor: null, mode })
          if (firstOutcome.status === 'invalid_cursor' && !cursorRecoveryUsedRef.current) {
            resetAfterInvalidCursor()
            shouldRestart = true
            continue
          }
          if (firstOutcome.status !== 'ok') return false
        }

        while (itemsRef.current.length < page * CATALOG_PAGE_SIZE && hasMoreRef.current) {
          const cursor = nextCursorRef.current
          if (!cursor) break
          const outcome = await fetchCatalogBatch({ cursor, mode: 'page' })
          if (outcome.status === 'invalid_cursor' && !cursorRecoveryUsedRef.current) {
            resetAfterInvalidCursor()
            shouldRestart = true
            break
          }
          if (outcome.status !== 'ok') return false
        }
      } while (shouldRestart)

      if (!mountedRef.current || navigationGeneration !== navigationGenerationRef.current) return false
      const availablePages = Math.max(1, Math.ceil(itemsRef.current.length / CATALOG_PAGE_SIZE))
      const pageHasRecords = page === 1 || itemsRef.current.length > (page - 1) * CATALOG_PAGE_SIZE
      if (page <= availablePages && pageHasRecords) {
        currentPageRef.current = page
        setCurrentPage(page)
        setPageInput(String(page))
        setPageError('')
        requestAnimationFrame(() => panelRef.current?.scrollTo({ top: 0, behavior: 'smooth' }))
        return true
      }

      setPageInput(String(currentPageRef.current))
      setPageError(`Only ${availablePages} ${availablePages === 1 ? 'page is' : 'pages are'} currently available.`)
      return false
    } finally {
      if (navigationGeneration === navigationGenerationRef.current) {
        pageOperationRef.current = false
        setPageLoading(false)
        setTargetPage(null)
      }
    }
  }, [fetchCatalogBatch, resetAfterInvalidCursor])

  useEffect(() => {
    mountedRef.current = true
    return () => {
      mountedRef.current = false
      navigationGenerationRef.current += 1
      catalogControllerRef.current?.abort()
    }
  }, [])

  const toggleOpen = () => {
    const nextOpen = !open
    setOpen(nextOpen)
    if (nextOpen && !catalogLoadedRef.current && !pageOperationRef.current) {
      goToPage(1, { mode: 'initial' })
    }
  }

  const refreshCatalog = () => {
    catalogControllerRef.current?.abort()
    catalogControllerRef.current = null
    inFlightCursorRef.current = null
    catalogGenerationRef.current += 1
    navigationGenerationRef.current += 1
    pageOperationRef.current = false
    seenCursorsRef.current = new Set()
    cursorRecoveryUsedRef.current = false
    catalogLoadedRef.current = false
    nextCursorRef.current = null
    hasMoreRef.current = false
    detailCacheRef.current.clear()
    replaceItems([])
    setSelectedSession(null)
    setSelectedOpener(null)
    setTotalReadySessions(0)
    setHasMore(false)
    currentPageRef.current = 1
    setCurrentPage(1)
    setPageInput('1')
    setPageError('')
    setPageLoading(false)
    setTargetPage(null)
    setCatalogError('')
    setCatalogBlocked(false)
    setCatalogNotice('')
    setInitialLoading(false)
    setRefreshing(true)
    queueMicrotask(() => goToPage(1, { mode: 'refresh' }))
  }

  const submitPage = (event) => {
    event.preventDefault()
    const normalizedInput = pageInput.trim()
    const page = Number(normalizedInput)
    const loadedPages = Math.max(1, Math.ceil(itemsRef.current.length / CATALOG_PAGE_SIZE))
    const estimatedPages = hasMoreRef.current
      ? Math.max(loadedPages, Math.ceil(totalReadySessions / CATALOG_PAGE_SIZE), 1)
      : loadedPages
    if (!/^[1-9]\d*$/.test(normalizedInput) || !Number.isSafeInteger(page) || page > estimatedPages) {
      setPageError(`Enter a page from 1 to ${estimatedPages}.`)
      return
    }
    goToPage(page)
  }

  const openSession = (session, opener) => {
    setCatalogNotice('')
    setSelectedSession(session)
    setSelectedOpener(opener)
  }

  const handleMemoryLoaded = (memory) => {
    const cacheEntry = {
      versionKey: buildVersionKey(memory),
      activeRootKind: memory.activeRootKind,
      memory,
      confirmedRequestSequence: catalogRequestSequenceRef.current
    }
    detailCacheRef.current.set(memory.sessionId, cacheEntry)

    const nextItems = itemsRef.current.map((item) => (
      item.sessionId === memory.sessionId ? applyAuthoritativeMemory(item, memory) : item
    ))
    replaceItems(nextItems)
    setSelectedSession((current) => (
      current?.sessionId === memory.sessionId ? applyAuthoritativeMemory(current, memory) : current
    ))
  }

  useEffect(() => {
    const memory = authoritativeUpdate?.memory
    if (!memory?.sessionId) return

    detailCacheRef.current.set(memory.sessionId, {
      versionKey: buildVersionKey(memory),
      activeRootKind: memory.activeRootKind,
      memory,
      confirmedRequestSequence: catalogRequestSequenceRef.current
    })
    replaceItems(itemsRef.current.map((item) => (
      item.sessionId === memory.sessionId ? applyAuthoritativeMemory(item, memory) : item
    )))
    setSelectedSession((current) => (
      current?.sessionId === memory.sessionId ? applyAuthoritativeMemory(current, memory) : current
    ))
  }, [authoritativeUpdate?.revision, replaceItems])

  const handleSessionUnavailable = (sessionId) => {
    detailCacheRef.current.delete(sessionId)
    const nextItems = itemsRef.current.filter((item) => item.sessionId !== sessionId)
    replaceItems(nextItems)
    setTotalReadySessions((current) => Math.max(0, current - 1))
    setSelectedSession(null)
    setCatalogNotice('The selected Session is no longer available and was removed from the Catalog.')

    const availablePages = Math.max(1, Math.ceil(nextItems.length / CATALOG_PAGE_SIZE))
    if (currentPage > availablePages) {
      currentPageRef.current = availablePages
      setCurrentPage(availablePages)
      setPageInput(String(availablePages))
    } else if (nextItems.length < currentPage * CATALOG_PAGE_SIZE && hasMoreRef.current) {
      queueMicrotask(() => goToPage(currentPage))
    }
  }

  const loadedPages = Math.max(1, Math.ceil(items.length / CATALOG_PAGE_SIZE))
  const catalogComplete = catalogLoadedRef.current && !hasMore && !catalogBlocked
  const estimatedPages = catalogComplete
    ? loadedPages
    : Math.max(1, loadedPages, Math.ceil(totalReadySessions / CATALOG_PAGE_SIZE))
  const pageStartIndex = (currentPage - 1) * CATALOG_PAGE_SIZE
  const visibleSessions = items.slice(pageStartIndex, pageStartIndex + CATALOG_PAGE_SIZE)
  const visibleStart = visibleSessions.length ? pageStartIndex + 1 : 0
  const visibleEnd = pageStartIndex + visibleSessions.length
  const summaryTotal = catalogComplete ? items.length : Math.max(items.length, totalReadySessions)
  const canGoNext = hasMore || currentPage < loadedPages
  const cachedMemory = selectedSession
    ? getCompatibleCache(selectedSession, detailCacheRef.current.get(selectedSession.sessionId))?.memory || null
    : null

  return (
    <section className="advanced-tools memory-tools">
      <button
        ref={toggleButtonRef}
        className="advanced-toggle"
        type="button"
        aria-expanded={open}
        aria-controls="long-term-memory-panel"
        onClick={toggleOpen}
      >
        <span>
          <Database size={16} />
          Memories
        </span>
        {open ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
      </button>

      {open && (
        <div ref={panelRef} id="long-term-memory-panel" className="surface advanced-panel memory-panel memory-catalog fade-in">
          <div className="memory-catalog-heading">
            <div>
              <span>Ready long-term memory Sessions</span>
              <strong>Global M_lt Catalog</strong>
              <small>Loaded {items.length} / {catalogComplete ? '' : 'about '}{summaryTotal}</small>
            </div>
            <button
              className="icon-button secondary memory-refresh"
              type="button"
              disabled={initialLoading || pageLoading || refreshing}
              onClick={refreshCatalog}
            >
              <RefreshCw size={15} className={refreshing ? 'memory-spin' : ''} />
              <span>{refreshing ? 'Refreshing' : 'Refresh'}</span>
            </button>
          </div>

          {catalogNotice && <div className="memory-notice" role="status">{catalogNotice}</div>}

          {initialLoading && items.length === 0 && (
            <div className="memory-loading" aria-live="polite">
              <span className="memory-spinner" />
              Loading ready long-term memory Sessions…
            </div>
          )}

          {!initialLoading && catalogError && items.length === 0 && (
            <div className="inline-error memory-error" role="alert">
              <span>{catalogError}</span>
              <button className="icon-button secondary" type="button" onClick={refreshCatalog}>Retry</button>
            </div>
          )}

          {!initialLoading && !catalogError && catalogLoadedRef.current && items.length === 0 && (
            <div className="memory-empty">No stable long-term memory Sessions are currently available.</div>
          )}

          {visibleSessions.length > 0 && (
            <div className="memory-session-list">
              {visibleSessions.map((session) => (
                <SessionCard session={session} onOpen={openSession} key={session.sessionId} />
              ))}
            </div>
          )}

          {items.length > 0 && (
            <nav className="memory-catalog-pagination" aria-label="Long-term memory Session pages">
              <div className="memory-catalog-page-summary">
                Showing {visibleStart}–{visibleEnd} of {catalogComplete ? '' : 'about '}{summaryTotal} Sessions
              </div>

              {catalogError && <div className="memory-catalog-page-error" role="alert">{catalogError}</div>}
              {pageError && <div className="memory-catalog-page-error" role="alert">{pageError}</div>}
              {pageLoading && (
                <div className="memory-catalog-page-loading" aria-live="polite">
                  <span className="memory-spinner is-small" />
                  Loading page {targetPage}…
                </div>
              )}

              <div className="memory-catalog-page-actions">
                <button
                  className="icon-button secondary"
                  type="button"
                  disabled={currentPage === 1 || pageLoading || refreshing}
                  onClick={() => goToPage(currentPage - 1)}
                >
                  Previous
                </button>
                <span className="memory-catalog-page-status" aria-current="page">
                  Page {currentPage} of {catalogComplete ? '' : 'about '}{estimatedPages}
                </span>
                <button
                  className="icon-button secondary"
                  type="button"
                  disabled={!canGoNext || pageLoading || refreshing}
                  onClick={() => goToPage(currentPage + 1)}
                >
                  Next
                </button>
              </div>

              <form className="memory-catalog-page-jump" onSubmit={submitPage}>
                <input
                  className="memory-catalog-page-input"
                  type="number"
                  min="1"
                  max={estimatedPages}
                  step="1"
                  inputMode="numeric"
                  aria-label="Catalog page number"
                  value={pageInput}
                  disabled={pageLoading || refreshing}
                  onChange={(event) => {
                    setPageInput(event.target.value)
                    setPageError('')
                  }}
                />
                <button
                  className="icon-button secondary"
                  type="submit"
                  disabled={estimatedPages === 1 || pageLoading || refreshing}
                >
                  Jump
                </button>
              </form>

              {catalogBlocked ? (
                <button className="icon-button secondary" type="button" onClick={refreshCatalog}>Refresh Catalog</button>
              ) : catalogError ? (
                <button
                  className="icon-button secondary"
                  type="button"
                  disabled={pageLoading}
                  onClick={() => goToPage(lastTargetPageRef.current)}
                >
                  Retry
                </button>
              ) : null}
            </nav>
          )}
        </div>
      )}

      {selectedSession && (
        <MemoryDialog
          key={selectedSession.sessionId}
          session={selectedSession}
          cachedMemory={cachedMemory}
          authoritativeUpdate={authoritativeUpdate?.sessionId === selectedSession?.sessionId ? authoritativeUpdate : null}
          openerElement={selectedOpener}
          fallbackFocusElement={toggleButtonRef.current}
          onMemoryLoaded={handleMemoryLoaded}
          onSessionUnavailable={handleSessionUnavailable}
          onClose={() => setSelectedSession(null)}
        />
      )}
    </section>
  )
}

function SessionCard({ session, onOpen }) {
  return (
    <button
      className="memory-session-card"
      type="button"
      onClick={(event) => onOpen(session, event.currentTarget)}
    >
      <span className="memory-session-card-heading">
        <strong>{session.sessionId}</strong>
        <small>{formatUpdatedAt(session.updatedAt)}</small>
      </span>
      <span className="memory-session-versions">
        <VersionItem label="M_lt" value={session.memoryVersion} />
        <VersionItem label="Episodic" value={session.componentVersions?.episodic} />
        <VersionItem label="Semantic" value={session.componentVersions?.semantic} />
        <VersionItem label="Visual" value={session.componentVersions?.visual} />
      </span>
      <span className="memory-status-row">
        <span className={`memory-status-badge ${session.qaAligned ? 'is-ready' : 'is-warning'}`}>
          {session.qaAligned ? 'QA aligned' : 'Legacy M_lt'}
        </span>
        <span className="memory-status-badge is-muted">{session.activeRootKind}</span>
      </span>
    </button>
  )
}

function VersionItem({ label, value }) {
  return (
    <span>
      <small>{label}</small>
      <strong>{value === null || value === undefined ? 'Unknown' : `v${value}`}</strong>
    </span>
  )
}

function buildVersionKey(memory) {
  const versions = memory.componentVersions || {}
  return [
    memory.sessionId,
    memory.memoryVersion,
    versions.episodic ?? 'na',
    versions.semantic ?? 'na',
    versions.visual ?? 'na'
  ].join('|')
}

function isCacheCompatible(session, cacheEntry) {
  if (!cacheEntry?.memory) return false
  const memory = cacheEntry.memory
  if (memory.sessionId !== session.sessionId) return false
  if (memory.memoryVersion !== session.memoryVersion) return false
  if (memory.activeRootKind !== session.activeRootKind) return false
  return COMPONENT_KEYS.every((key) => (
    session.componentVersions?.[key] === null
    || session.componentVersions?.[key] === undefined
    || session.componentVersions[key] === memory.componentVersions?.[key]
  ))
}

function getCompatibleCache(session, cacheEntry) {
  return isCacheCompatible(session, cacheEntry) ? cacheEntry : null
}

function preserveUnknownComponentVersions(session, memory) {
  return {
    ...session,
    componentVersions: Object.fromEntries(COMPONENT_KEYS.map((key) => [
      key,
      session.componentVersions?.[key] ?? memory.componentVersions?.[key] ?? null
    ]))
  }
}

function applyAuthoritativeMemory(session, memory) {
  return {
    ...session,
    memoryVersion: memory.memoryVersion,
    componentVersions: memory.componentVersions,
    updatedAt: memory.updatedAt,
    activeRootKind: memory.activeRootKind,
    qaAligned: memory.qaAligned
  }
}

function formatUpdatedAt(value) {
  if (!value) return 'Updated time unavailable'
  const parsed = new Date(value)
  return Number.isNaN(parsed.getTime()) ? 'Updated time unavailable' : `Updated ${parsed.toLocaleString()}`
}

function formatCatalogError(error) {
  if (error?.code === 'invalid_cursor' || error?.status === 400) {
    return 'The Catalog cursor is no longer valid. Refresh the Catalog to restart.'
  }
  if (error?.code === 'memory_catalog_failed' || error?.status === 500) {
    return 'The long-term memory Catalog is temporarily unavailable.'
  }
  if (error?.code === 'invalid_memory_catalog_response') {
    return 'The long-term memory Catalog response was invalid.'
  }
  return error?.message || 'Unable to load the long-term memory Catalog.'
}
