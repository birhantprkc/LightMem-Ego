import { ArrowRight, CircleX } from 'lucide-react'
import { formatEventRange, safeDisplay } from '../../utils/memoryGraphUtils.js'
import KeyframeGrid from './KeyframeGrid.jsx'

export default function GraphDetailsPanel({ selection, model, view, onSelectEvent, onClear }) {
  if (!selection) {
    return (
      <section className="memory-graph-details" aria-label="Memory graph details">
        <div className="memory-graph-details-empty">
          <strong>Select an Event, Fact, or Entity</strong>
          <span>Details and cross-graph evidence will appear here.</span>
        </div>
      </section>
    )
  }

  let content = null
  if (selection.kind === 'event') content = <EventDetails event={model.eventById.get(selection.id)} model={model} />
  if (selection.kind === 'fact') content = <FactDetails fact={model.factById.get(selection.id)} model={model} view={view} onSelectEvent={onSelectEvent} />
  if (selection.kind === 'entity') content = <EntityDetails entityId={selection.id} model={model} view={view} />

  return (
    <section className="memory-graph-details" aria-label="Selected memory graph item details">
      <div className="memory-graph-detail-heading">
        <span>{selection.kind === 'fact' ? 'Semantic Fact' : selection.kind === 'event' ? 'Episodic Event' : 'Canonical Entity'}</span>
        <button className="icon-button secondary" type="button" onClick={onClear}>
          <CircleX size={14} />
          <span>Clear</span>
        </button>
      </div>
      {content || <div className="memory-graph-details-empty">The selected item is no longer available.</div>}
    </section>
  )
}

function EventDetails({ event, model }) {
  if (!event) return null
  const document = event.docId ? model.documentByDocId.get(event.docId) : null
  const relations = (model.episodicEdgesByEventId.get(event.id) || []).filter((edge) => edge.kind === 'entity_relation')

  return (
    <div className="memory-graph-detail-content">
      <div className="memory-graph-detail-title">
        <strong>{event.title || event.label || 'Untitled event'}</strong>
        <span>{formatEventRange(event)}</span>
      </div>
      <DetailGrid items={[
        ['Confidence', formatNumber(event.confidence)],
        ['Status', event.status],
        ['Actions', event.counts?.actions],
        ['Objects', event.counts?.objects ?? event.counts?.visualObjects],
        ['State changes', event.counts?.stateChanges]
      ]} />
      <DetailSection title="Description" value={document?.text || document?.caption || event.title} />
      <DetailSection title="Visual summary" value={document?.visualSummary} />
      <DetailSection title="Transcript" value={document?.transcript} />
      <DetailSection title="Scene" value={document?.scene} />
      <DetailSection title="Visual objects" value={document?.visualObjects} />
      <DetailSection title="Actions" value={document?.actions} />
      <DetailSection title="State changes" value={document?.stateChanges} />
      <DetailSection title="Topic threads" value={document?.topicThreads} />
      <DetailSection title="Critical speech" value={document?.criticalSpeechLines} />
      {relations.length > 0 && (
        <section className="memory-graph-detail-section">
          <h4>Event triples</h4>
          <ul className="memory-graph-triples">
            {relations.map((edge) => (
              <li key={edge.id}>
                <span>{model.episodicEntityById.get(edge.source)?.label || edge.source}</span>
                <strong>{edge.relation || edge.label || 'related to'}</strong>
                <span>{model.episodicEntityById.get(edge.target)?.label || edge.target}</span>
                {edge.occurrenceCount > 1 && <small>×{edge.occurrenceCount}</small>}
              </li>
            ))}
          </ul>
        </section>
      )}
      <KeyframeGrid keyframes={document?.keyframes || []} />
    </div>
  )
}

function FactDetails({ fact, model, view, onSelectEvent }) {
  if (!fact) return null
  const source = model.semanticEntityById.get(fact.source)?.label || fact.source
  const target = model.semanticEntityById.get(fact.target)?.label || fact.target
  const eventIds = model.factIdToEventIds.get(fact.id) || fact.supportEventIds || []

  return (
    <div className="memory-graph-detail-content">
      <div className="memory-graph-fact-title">
        <strong>{source}</strong>
        <span>{fact.relation || 'related to'}</span>
        <ArrowRight size={17} />
        <strong>{target}</strong>
      </div>
      <DetailGrid items={[
        ['Confidence', formatNumber(fact.confidence)],
        ['Support count', fact.supportCount],
        ['Raw support', fact.rawSupportCount],
        ['Habit strength', fact.habitStrength],
        ['Semantic version', fact.semanticVersion],
        ['Unresolved support', fact.unresolvedSupportCount]
      ]} />
      <DetailSection title="First seen" value={fact.firstSeen} />
      <DetailSection title="Last seen" value={fact.lastSeen} />
      <DetailSection title="Support days" value={fact.supportDays} />
      <DetailSection title="Support scales" value={fact.supportScales} />

      <section className="memory-graph-detail-section">
        <h4>Supporting events</h4>
        {eventIds.length ? (
          <div className="memory-graph-supporting-events">
            {eventIds.map((eventId) => {
              const event = model.eventById.get(eventId)
              const document = event?.docId ? model.documentByDocId.get(event.docId) : null
              const outsideFilters = !view.visibleEventIds.has(eventId)
              return (
                <button type="button" onClick={() => onSelectEvent(eventId, outsideFilters)} key={eventId}>
                  <span>
                    <strong>{event?.title || event?.label || eventId}</strong>
                    <small>{event ? formatEventRange(event) : 'Event details unavailable'}</small>
                    {(document?.caption || document?.text) && <em>{String(document.caption || document.text).slice(0, 180)}</em>}
                  </span>
                  <span>{outsideFilters ? 'Show event' : 'Open'}</span>
                </button>
              )
            })}
          </div>
        ) : <div className="memory-graph-detail-empty">No resolved supporting events.</div>}
      </section>
    </div>
  )
}

function EntityDetails({ entityId, model, view }) {
  const episodicEntity = model.episodicEntityById.get(entityId)
  const semanticEntity = model.semanticEntityById.get(entityId)
  const entity = semanticEntity || episodicEntity
  if (!entity) return null
  const mentions = model.graph.episodic.edges.filter((edge) => edge.kind === 'mentions' && edge.target === entityId)
  const relatedFacts = [...model.factById.values()].filter((fact) => fact.source === entityId || fact.target === entityId)
  const relatedEvents = new Set(mentions.map((edge) => edge.source))
  const visibleFacts = relatedFacts.filter((fact) => view.visibleFactIds.has(fact.id)).length
  const visibleEvents = [...relatedEvents].filter((eventId) => view.visibleEventIds.has(eventId)).length

  return (
    <div className="memory-graph-detail-content">
      <div className="memory-graph-detail-title">
        <strong>{entity.label}</strong>
        <span>{entity.id}</span>
      </div>
      <DetailGrid items={[
        ['Mentions', mentions.reduce((total, edge) => total + edge.occurrenceCount, 0)],
        ['Events', relatedEvents.size],
        ['Visible events', visibleEvents],
        ['Facts', semanticEntity?.factCount || relatedFacts.length],
        ['Visible facts', visibleFacts],
        ['Total support', semanticEntity?.totalSupportCount || 0]
      ]} />
      <DetailSection title="First seen" value={semanticEntity?.firstSeen || entity.firstSeen} />
      <DetailSection title="Last seen" value={semanticEntity?.lastSeen || entity.lastSeen} />
    </div>
  )
}

function DetailGrid({ items }) {
  const visibleItems = items.filter(([, value]) => value !== null && value !== undefined && value !== '')
  if (!visibleItems.length) return null
  return (
    <div className="memory-graph-detail-grid">
      {visibleItems.map(([label, value]) => (
        <div key={label}>
          <span>{label}</span>
          <strong>{safeDisplay(value)}</strong>
        </div>
      ))}
    </div>
  )
}

function DetailSection({ title, value }) {
  if (value === null || value === undefined || value === '' || (Array.isArray(value) && !value.length)) return null
  const content = Array.isArray(value)
    ? <ul>{value.map((item, index) => <li key={`${title}-${index}`}>{safeDisplay(item)}</li>)}</ul>
    : <p>{safeDisplay(value)}</p>
  return (
    <section className="memory-graph-detail-section">
      <h4>{title}</h4>
      {content}
    </section>
  )
}

function formatNumber(value) {
  return Number.isFinite(value) ? value.toFixed(2) : value
}
