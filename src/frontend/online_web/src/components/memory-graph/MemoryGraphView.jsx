import { AlertTriangle, Network, RefreshCw } from 'lucide-react'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { useMemoryGraph } from '../../hooks/useMemoryGraph.js'
import {
  buildGraphModel,
  DEFAULT_GRAPH_FILTERS,
  deriveGraphView
} from '../../utils/memoryGraphUtils.js'
import EpisodicGraph from './EpisodicGraph.jsx'
import GraphDetailsPanel from './GraphDetailsPanel.jsx'
import GraphToolbar from './GraphToolbar.jsx'
import SemanticGraph from './SemanticGraph.jsx'

export default function MemoryGraphView({ session, authoritativeUpdate, onSessionUnavailable }) {
  const graphRequest = useMemoryGraph(session.sessionId, {
    authoritativeUpdate,
    onSessionUnavailable
  })
  const [activeMobileGraph, setActiveMobileGraph] = useState('episodic')
  const [filters, setFilters] = useState(() => ({ ...DEFAULT_GRAPH_FILTERS }))
  const [selection, setSelection] = useState(null)
  const [expandedEventId, setExpandedEventId] = useState(null)
  const debouncedQuery = useDebouncedValue(filters.query, 200)
  const model = useMemo(() => graphRequest.payload ? buildGraphModel(graphRequest.payload) : null, [graphRequest.payload])
  const effectiveFilters = useMemo(() => ({ ...filters, query: debouncedQuery }), [debouncedQuery, filters])
  const view = useMemo(
    () => model ? deriveGraphView(model, effectiveFilters, expandedEventId) : null,
    [effectiveFilters, expandedEventId, model]
  )

  useEffect(() => {
    if (!model || !selection) return
    const stillExists = selection.kind === 'event'
      ? model.eventById.has(selection.id)
      : selection.kind === 'fact'
        ? model.factById.has(selection.id)
        : model.episodicEntityById.has(selection.id) || model.semanticEntityById.has(selection.id)
    if (!stillExists) {
      setSelection(null)
      setExpandedEventId(null)
    }
  }, [model, selection])

  useEffect(() => {
    if (expandedEventId && model && !model.eventById.has(expandedEventId)) setExpandedEventId(null)
  }, [expandedEventId, model])

  const updateFilters = useCallback((patch) => setFilters((current) => ({ ...current, ...patch })), [])
  const resetFilters = useCallback(() => setFilters({ ...DEFAULT_GRAPH_FILTERS }), [])
  const clearSelection = useCallback(() => {
    setSelection(null)
    setExpandedEventId(null)
  }, [])

  const selectEpisodic = useCallback((kind, id) => {
    setSelection({ kind, id, origin: 'episodic' })
    if (kind === 'event') setExpandedEventId((current) => current === id ? null : id)
  }, [])

  const selectSemantic = useCallback((kind, id) => {
    setSelection({ kind, id, origin: 'semantic' })
    if (kind === 'entity') {
      const mentionedBy = model?.graph.episodic.edges.find((edge) => (
        edge.kind === 'mentions' && edge.target === id && view?.visibleEventIds.has(edge.source)
      ))
      if (mentionedBy) setExpandedEventId(mentionedBy.source)
    }
  }, [model, view])

  const selectSupportingEvent = useCallback((eventId, outsideFilters) => {
    const event = model?.eventById.get(eventId)
    if (!event) return
    if (outsideFilters) {
      const eventStart = event.eventTime.timelineStartSeconds
      const eventEnd = event.eventTime.timelineEndSeconds
      setFilters((current) => ({
        ...current,
        query: '',
        relations: [],
        episodicMinConfidence: 0,
        startSeconds: Number.isFinite(eventStart)
          ? Math.min(Number.isFinite(current.startSeconds) ? current.startSeconds : model.timeDomain.start, eventStart)
          : current.startSeconds,
        endSeconds: Number.isFinite(eventEnd)
          ? Math.max(Number.isFinite(current.endSeconds) ? current.endSeconds : model.timeDomain.end, eventEnd)
          : current.endSeconds
      }))
    }
    setSelection({ kind: 'event', id: eventId, origin: 'details' })
    setExpandedEventId(eventId)
    setActiveMobileGraph('episodic')
  }, [model])

  if (!graphRequest.payload) {
    return (
      <GraphRequestState
        status={graphRequest.status}
        error={graphRequest.error}
        requestId={graphRequest.requestId}
        onRetry={graphRequest.retry}
      />
    )
  }

  const linkedEventIds = selection?.kind === 'fact' ? model.factIdToEventIds.get(selection.id) || [] : []
  const linkedFactIds = selection?.kind === 'event' ? model.eventIdToFactIds.get(selection.id) || [] : []
  const linkedEntityId = selection?.kind === 'entity' ? selection.id : null
  const visibleLinkedFactIds = linkedFactIds.filter((id) => view.visibleFactIds.has(id))
  const warnings = collectWarnings(graphRequest.payload)
  const versions = graphRequest.payload.componentVersions

  return (
    <div className="memory-graph-view">
      <div className="memory-graph-meta">
        <div>
          <span>30-second linked memory graph</span>
          <strong>M_lt v{graphRequest.payload.memoryVersion ?? session.memoryVersion} · Graph v{versions.graph} · Semantic v{versions.semantic}</strong>
          <small>{formatUpdatedAt(graphRequest.payload.updatedAt || session.updatedAt)}</small>
        </div>
        <GraphStatus status={graphRequest.status} lastCheckedAt={graphRequest.lastCheckedAt} />
      </div>

      {graphRequest.error && (
        <div className="memory-graph-banner is-warning" role="status">
          <AlertTriangle size={15} />
          <span>{formatGraphError(graphRequest.error)}</span>
          {graphRequest.status === 'error' && (
            <button className="icon-button secondary" type="button" onClick={graphRequest.retry}>
              <RefreshCw size={14} />
              Retry
            </button>
          )}
        </div>
      )}

      {warnings.length > 0 && (
        <div className="memory-graph-banner" role="status">
          <AlertTriangle size={15} />
          <span>{warnings.join(' · ')}</span>
        </div>
      )}

      <GraphToolbar
        filters={filters}
        relationOptions={view.relationOptions}
        timeDomain={view.timeDomain}
        onChange={updateFilters}
        onReset={resetFilters}
      />

      <div className="memory-graph-summary">
        <span>{view.visibleEvents.length} events</span>
        <span>Showing {view.visibleFacts.length} of {view.semanticCandidateCount} matching facts</span>
        {selection?.kind === 'event' && <span>{linkedFactIds.length} related facts · {visibleLinkedFactIds.length} currently visible</span>}
      </div>

      <div className="memory-graph-mobile-tabs" role="tablist" aria-label="Memory graph type">
        <button type="button" role="tab" aria-selected={activeMobileGraph === 'episodic'} className={activeMobileGraph === 'episodic' ? 'active' : ''} onClick={() => setActiveMobileGraph('episodic')}>Episodic</button>
        <button type="button" role="tab" aria-selected={activeMobileGraph === 'semantic'} className={activeMobileGraph === 'semantic' ? 'active' : ''} onClick={() => setActiveMobileGraph('semantic')}>Semantic</button>
      </div>

      <div className="memory-graph-board">
        <section className={`memory-graph-pane episodic ${activeMobileGraph === 'episodic' ? 'is-mobile-active' : ''}`}>
          <div className="memory-graph-pane-heading">
            <div>
              <strong>Episodic Graph</strong>
              <span>Event timeline · select an Event to expand entities</span>
            </div>
            <small>{view.visibleEvents.length} events</small>
          </div>
          <EpisodicGraph
            elements={view.episodic.elements}
            selection={selection}
            linkedEventIds={linkedEventIds}
            linkedEntityId={linkedEntityId}
            focusEventIds={selection?.kind === 'fact' ? linkedEventIds : selection?.id ? [selection.id] : []}
            onSelect={selectEpisodic}
            onClear={clearSelection}
          />
        </section>

        <section className={`memory-graph-pane semantic ${activeMobileGraph === 'semantic' ? 'is-mobile-active' : ''}`}>
          <div className="memory-graph-pane-heading">
            <div>
              <strong>Semantic Graph</strong>
              <span>Stable knowledge · edge width represents support</span>
            </div>
            <small>{view.visibleFacts.length} / {view.semanticCandidateCount} facts</small>
          </div>
          <SemanticGraph
            elements={view.semantic.elements}
            selection={selection}
            linkedFactIds={visibleLinkedFactIds}
            linkedEntityId={linkedEntityId}
            focusFactIds={selection?.kind === 'event' ? visibleLinkedFactIds : selection?.id ? [selection.id] : []}
            onSelect={selectSemantic}
            onClear={clearSelection}
          />
        </section>
      </div>

      <GraphDetailsPanel
        selection={selection}
        model={model}
        view={view}
        onSelectEvent={selectSupportingEvent}
        onClear={clearSelection}
      />
    </div>
  )
}

function GraphRequestState({ status, error, requestId, onRetry }) {
  const waiting = status === 'waiting'
  const loading = status === 'idle' || status === 'loading'
  if (loading || waiting) {
    return (
      <div className="memory-graph-request-state" aria-live="polite">
        <span className="memory-spinner" />
        <strong>{waiting ? 'Memory graph is being built' : 'Loading linked memory graph…'}</strong>
        <span>{waiting ? 'The page will retry automatically.' : 'Loading Episodic and Semantic data.'}</span>
        {requestId && <small>Request {requestId}</small>}
      </div>
    )
  }

  return (
    <div className="memory-graph-request-state is-error" role="alert">
      <Network size={28} />
      <strong>{formatGraphError(error)}</strong>
      <span>{error?.code === 'graph_not_supported' ? 'The Records tab remains available for this legacy Session.' : 'The graph could not be displayed.'}</span>
      {requestId && <small>Request {requestId}</small>}
      {error?.status !== 409 && error?.status !== 413 && (
        <button className="icon-button secondary" type="button" onClick={onRetry}>
          <RefreshCw size={14} />
          Retry
        </button>
      )}
    </div>
  )
}

function GraphStatus({ status, lastCheckedAt }) {
  const label = status === 'waiting' ? 'Building' : status === 'error' ? 'Refresh failed' : 'Synced'
  return (
    <div className={`memory-graph-sync-status is-${status}`} aria-live={status === 'waiting' ? 'polite' : 'off'}>
      <span />
      <strong>{label}</strong>
      {lastCheckedAt && <small>{new Date(lastCheckedAt).toLocaleTimeString()}</small>}
    </div>
  )
}

function collectWarnings(payload) {
  const warnings = []
  const serverWarningTotal = Object.values(payload.warnings || {}).reduce((total, value) => total + (Number(value) || 0), 0)
  if (serverWarningTotal > 0) warnings.push(`${serverWarningTotal} server normalization warnings`)
  if (payload.clientWarnings.invalidNodeCount) warnings.push(`${payload.clientWarnings.invalidNodeCount} invalid nodes skipped`)
  if (payload.clientWarnings.duplicateNodeCount) warnings.push(`${payload.clientWarnings.duplicateNodeCount} duplicate nodes skipped`)
  if (payload.clientWarnings.invalidEdgeCount) warnings.push(`${payload.clientWarnings.invalidEdgeCount} invalid edges skipped`)
  if (payload.clientWarnings.missingRelationEventIdCount) warnings.push(`${payload.clientWarnings.missingRelationEventIdCount} entity relations cannot be assigned to an Event`)
  return warnings
}

function formatGraphError(error) {
  const code = error?.code
  if (code === 'invalid_session_id' || code === 'unsupported_graph_scale' || error?.status === 400) return 'The memory graph request is invalid.'
  if (code === 'session_not_found') return 'The Session is no longer available.'
  if (error?.status === 404) return 'The memory graph endpoint is not available in this deployment.'
  if (code === 'graph_not_supported' || error?.status === 409) return 'This legacy Session does not support linked memory graphs.'
  if (code === 'memory_graph_response_too_large' || error?.status === 413) return 'This memory graph is too large to display safely.'
  if (code === 'memory_graph_not_ready') return 'The memory graph is not ready yet.'
  if (code === 'memory_component_lagging') return 'Graph components are still being published.'
  if (code === 'memory_snapshot_changing') return 'The memory graph is being updated.'
  if (code === 'invalid_memory_graph_response') return 'The memory graph response is incomplete or incompatible.'
  if (error?.status === 500) return 'The memory graph service is temporarily unavailable.'
  return error?.message || 'Unable to load the memory graph.'
}

function formatUpdatedAt(value) {
  if (!value) return '30-second scale'
  const parsed = new Date(value)
  return Number.isNaN(parsed.getTime()) ? '30-second scale' : `Updated ${parsed.toLocaleString()}`
}

function useDebouncedValue(value, delay) {
  const [debounced, setDebounced] = useState(value)
  useEffect(() => {
    const timer = window.setTimeout(() => setDebounced(value), delay)
    return () => window.clearTimeout(timer)
  }, [delay, value])
  return debounced
}
