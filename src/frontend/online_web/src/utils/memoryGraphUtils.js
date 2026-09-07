const SEMANTIC_FACT_LIMIT = 100

const RELATION_GROUPS = {
  spatial: new Set(['contains', 'appears_in']),
  action: new Set(['uses', 'moves', 'holds']),
  state: new Set(['state_changed_to']),
  dialogue: new Set(['discusses'])
}

const KNOWN_NODE_KINDS = new Set(['event', 'entity'])
const KNOWN_EPISODIC_EDGE_KINDS = new Set(['before', 'mentions', 'entity_relation'])

export const DEFAULT_GRAPH_FILTERS = Object.freeze({
  query: '',
  startSeconds: null,
  endSeconds: null,
  relations: [],
  episodicMinConfidence: 0,
  semanticMinConfidence: 0.6,
  semanticMinSupportCount: 1
})

export function normalizeMemoryGraphResponse(raw, expectedSessionId) {
  if (!raw || typeof raw !== 'object') throw invalidGraphResponse()

  const schemaVersion = Number(first(raw.schema_version, raw.schemaVersion))
  const sessionId = String(first(raw.session_id, raw.sessionId, ''))
  const memorySource = String(first(raw.memory_source, raw.memorySource, ''))
  const scale = String(first(raw.scale, ''))
  const memoryVersion = numericOrNull(first(raw.memory_version, raw.memoryVersion))
  const componentVersionsRaw = first(raw.component_versions, raw.componentVersions, {})
  const componentVersions = {
    episodic: numericOrNull(componentVersionsRaw?.episodic),
    graph: numericOrNull(componentVersionsRaw?.graph),
    semantic: numericOrNull(componentVersionsRaw?.semantic)
  }
  const graphVersionsRaw = first(raw.graph_versions, raw.graphVersions, null)
  const graphVersions = graphVersionsRaw && typeof graphVersionsRaw === 'object'
    ? {
        episodicGraph: numericOrNull(first(graphVersionsRaw.episodic_graph, graphVersionsRaw.episodicGraph)),
        semanticGraph: numericOrNull(first(graphVersionsRaw.semantic_graph, graphVersionsRaw.semanticGraph))
      }
    : null
  const graphVersionsValid = graphVersions === null || Object.values(graphVersions).every((value) => (
    Number.isInteger(value) && value > 0
  ))

  if (
    schemaVersion !== 1
    || raw.status !== 'ok'
    || !sessionId
    || sessionId !== expectedSessionId
    || memorySource !== 'M_lt'
    || scale !== '30sec'
    || !Number.isInteger(memoryVersion)
    || memoryVersion <= 0
    || !Object.values(componentVersions).every((value) => Number.isInteger(value) && value > 0)
    || !graphVersionsValid
    || !Array.isArray(raw.episodic?.nodes)
    || !Array.isArray(raw.episodic?.edges)
    || !Array.isArray(raw.semantic?.nodes)
    || !Array.isArray(raw.semantic?.edges)
    || !Array.isArray(raw.semantic?.timeline)
    || !isPlainObject(raw.documents)
    || !isPlainObject(raw.indexes)
    || !isPlainObject(raw.warnings)
  ) throw invalidGraphResponse()

  const clientWarnings = {
    duplicateNodeCount: 0,
    invalidNodeCount: 0,
    invalidEdgeCount: 0,
    missingRelationEventIdCount: 0
  }

  const episodicNodes = normalizeNodes(raw.episodic.nodes, clientWarnings)
  const semanticNodes = normalizeNodes(raw.semantic.nodes, clientWarnings)
  const episodicNodeIds = new Set(episodicNodes.map((node) => node.id))
  const semanticNodeIds = new Set(semanticNodes.map((node) => node.id))
  const episodicEdges = normalizeEdges(
    raw.episodic.edges,
    episodicNodeIds,
    KNOWN_EPISODIC_EDGE_KINDS,
    clientWarnings
  )
  const semanticEdges = normalizeEdges(
    raw.semantic.edges,
    semanticNodeIds,
    new Set(['semantic_fact']),
    clientWarnings
  )

  return {
    schemaVersion,
    status: 'ok',
    sessionId,
    memorySource,
    scale,
    memoryVersion,
    componentVersions,
    graphVersions,
    updatedAt: first(raw.updated_at, raw.updatedAt, null),
    availability: camelizeSmallObject(raw.availability),
    stats: camelizeSmallObject(raw.stats),
    episodic: { nodes: episodicNodes, edges: episodicEdges },
    semantic: {
      nodes: semanticNodes,
      edges: semanticEdges,
      timeline: raw.semantic.timeline.map((item) => normalizeTimelineItem(item)).filter(Boolean)
    },
    documents: normalizeDocuments(raw.documents),
    indexes: normalizeIndexes(raw.indexes),
    warnings: camelizeSmallObject(raw.warnings),
    clientWarnings
  }
}

function normalizeNodes(items, warnings) {
  const seen = new Set()
  const result = []
  for (const raw of items) {
    const id = String(raw?.id || '')
    const kind = String(raw?.kind || '').toLowerCase()
    if (!id || !KNOWN_NODE_KINDS.has(kind)) {
      warnings.invalidNodeCount += 1
      continue
    }
    if (seen.has(id)) {
      warnings.duplicateNodeCount += 1
      continue
    }
    seen.add(id)
    result.push({
      id,
      kind,
      docId: first(raw.doc_id, raw.docId, null),
      label: String(first(raw.label, id)),
      title: String(first(raw.title, '')),
      eventTime: normalizeEventTime(first(raw.event_time, raw.eventTime, {})),
      confidence: numericOrNull(raw.confidence),
      status: first(raw.status, null),
      counts: camelizeSmallObject(raw.counts),
      factCount: numberOrZero(first(raw.fact_count, raw.factCount)),
      totalSupportCount: numberOrZero(first(raw.total_support_count, raw.totalSupportCount)),
      firstSeen: first(raw.first_seen, raw.firstSeen, null),
      lastSeen: first(raw.last_seen, raw.lastSeen, null)
    })
  }
  return result
}

function normalizeEdges(items, nodeIds, allowedKinds, warnings) {
  const seen = new Set()
  const result = []
  for (const raw of items) {
    const id = String(raw?.id || '')
    const kind = String(raw?.kind || '').toLowerCase()
    const source = String(raw?.source || '')
    const target = String(raw?.target || '')
    if (!id || seen.has(id) || !allowedKinds.has(kind) || !nodeIds.has(source) || !nodeIds.has(target)) {
      warnings.invalidEdgeCount += 1
      continue
    }
    seen.add(id)
    const eventId = first(raw.event_id, raw.eventId, null)
    if (kind === 'entity_relation' && !eventId) warnings.missingRelationEventIdCount += 1
    result.push({
      id,
      kind,
      source,
      target,
      eventId,
      relation: String(first(raw.relation, raw.label, '')),
      label: String(first(raw.label, raw.relation, '')),
      occurrenceCount: Math.max(1, numberOrZero(first(raw.occurrence_count, raw.occurrenceCount, 1))),
      confidence: numericOrNull(raw.confidence),
      supportCount: Math.max(0, numberOrZero(first(raw.support_count, raw.supportCount))),
      rawSupportCount: Math.max(0, numberOrZero(first(raw.raw_support_count, raw.rawSupportCount))),
      habitStrength: String(first(raw.habit_strength, raw.habitStrength, '')).toLowerCase(),
      supportDays: stringArray(first(raw.support_days, raw.supportDays, [])),
      supportScales: stringArray(first(raw.support_scales, raw.supportScales, [])),
      supportDocIds: stringArray(first(raw.support_doc_ids, raw.supportDocIds, [])),
      supportEventIds: stringArray(first(raw.support_event_ids, raw.supportEventIds, [])),
      unresolvedSupportCount: numberOrZero(first(raw.unresolved_support_count, raw.unresolvedSupportCount)),
      firstSeen: first(raw.first_seen, raw.firstSeen, null),
      lastSeen: first(raw.last_seen, raw.lastSeen, null),
      semanticVersion: numericOrNull(first(raw.semantic_version, raw.semanticVersion))
    })
  }
  return result
}

function normalizeDocuments(documents) {
  const result = {}
  for (const [key, raw] of Object.entries(documents)) {
    if (!raw || typeof raw !== 'object') continue
    const docId = String(first(raw.doc_id, raw.docId, key))
    result[docId] = {
      docId,
      eventId: first(raw.event_id, raw.eventId, null),
      eventTime: normalizeEventTime(first(raw.event_time, raw.eventTime, {})),
      text: safeValue(raw.text),
      caption: safeValue(raw.caption),
      visualSummary: safeValue(first(raw.visual_summary, raw.visualSummary)),
      transcript: safeValue(raw.transcript),
      scene: safeValue(raw.scene),
      visualObjects: safeArray(first(raw.visual_objects, raw.visualObjects)),
      actions: safeArray(raw.actions),
      stateChanges: safeArray(first(raw.state_changes, raw.stateChanges)),
      topicThreads: safeArray(first(raw.topic_threads, raw.topicThreads)),
      criticalSpeechLines: safeArray(first(raw.critical_speech_lines, raw.criticalSpeechLines)),
      confidence: numericOrNull(raw.confidence),
      status: first(raw.status, null),
      keyframes: safeArray(raw.keyframes).map((frame) => ({
        thumbnailUrl: String(first(frame?.thumbnail_url, frame?.thumbnailUrl, '')),
        timestampSeconds: numericOrNull(first(frame?.timestamp_seconds, frame?.timestampSeconds))
      })).filter((frame) => frame.thumbnailUrl)
    }
  }
  return result
}

function normalizeIndexes(indexes) {
  return {
    docIdToEventId: stringMap(first(indexes.doc_id_to_event_id, indexes.docIdToEventId, {})),
    eventIdToFactIds: stringArrayMap(first(indexes.event_id_to_fact_ids, indexes.eventIdToFactIds, {})),
    factIdToEventIds: stringArrayMap(first(indexes.fact_id_to_event_ids, indexes.factIdToEventIds, {}))
  }
}

function normalizeEventTime(value) {
  const raw = value && typeof value === 'object' ? value : {}
  return {
    date: first(raw.date, null),
    startCode: first(raw.start_code, raw.startCode, null),
    endCode: first(raw.end_code, raw.endCode, null),
    startSeconds: numericOrNull(first(raw.start_seconds, raw.startSeconds)),
    endSeconds: numericOrNull(first(raw.end_seconds, raw.endSeconds)),
    timelineStartSeconds: numericOrNull(first(raw.timeline_start_seconds, raw.timelineStartSeconds)),
    timelineEndSeconds: numericOrNull(first(raw.timeline_end_seconds, raw.timelineEndSeconds))
  }
}

function normalizeTimelineItem(item) {
  if (typeof item === 'string') return item
  if (!item || typeof item !== 'object') return null
  return camelizeSmallObject(item)
}

export function buildGraphModel(graph) {
  const eventById = new Map(graph.episodic.nodes.filter((node) => node.kind === 'event').map((node) => [node.id, node]))
  const episodicEntityById = new Map(graph.episodic.nodes.filter((node) => node.kind === 'entity').map((node) => [node.id, node]))
  const semanticEntityById = new Map(graph.semantic.nodes.filter((node) => node.kind === 'entity').map((node) => [node.id, node]))
  const factById = new Map(graph.semantic.edges.filter((edge) => edge.kind === 'semantic_fact').map((edge) => [edge.id, edge]))
  const episodicEdgesByEventId = new Map()

  for (const eventId of eventById.keys()) episodicEdgesByEventId.set(eventId, [])
  for (const edge of graph.episodic.edges) {
    const eventId = edge.kind === 'mentions' ? edge.source : edge.eventId
    if (eventId && episodicEdgesByEventId.has(eventId)) episodicEdgesByEventId.get(eventId).push(edge)
  }

  const events = [...eventById.values()].sort(compareEvents)
  const timelineStart = finiteMin(events.map((event) => event.eventTime.timelineStartSeconds))
  const timelineEnd = finiteMax(events.map((event) => event.eventTime.timelineEndSeconds))
  const relationOptions = [...new Set([
    ...graph.episodic.edges.filter((edge) => edge.kind === 'entity_relation').map((edge) => edge.relation),
    ...[...factById.values()].map((edge) => edge.relation)
  ].filter(Boolean))].sort((left, right) => left.localeCompare(right))

  return {
    graph,
    events,
    eventById,
    episodicEntityById,
    semanticEntityById,
    factById,
    episodicEdgesByEventId,
    documentByDocId: new Map(Object.entries(graph.documents)),
    eventIdToFactIds: new Map(Object.entries(graph.indexes.eventIdToFactIds)),
    factIdToEventIds: new Map(Object.entries(graph.indexes.factIdToEventIds)),
    docIdToEventId: new Map(Object.entries(graph.indexes.docIdToEventId)),
    relationOptions,
    timeDomain: { start: timelineStart ?? 0, end: timelineEnd ?? timelineStart ?? 0 }
  }
}

export function deriveGraphView(model, filters, expandedEventId) {
  const query = normalizeSearch(filters.query)
  const selectedRelations = new Set((filters.relations || []).map(normalizeRelation))
  const start = finiteOr(filters.startSeconds, model.timeDomain.start)
  const end = finiteOr(filters.endSeconds, model.timeDomain.end)
  const timeVisibleEvents = model.events.filter((event) => eventOverlaps(event, start, end))
  const timeVisibleEventIds = new Set(timeVisibleEvents.map((event) => event.id))

  const visibleEvents = timeVisibleEvents.filter((event) => {
    if (finiteOr(event.confidence, 0) < finiteOr(filters.episodicMinConfidence, 0)) return false
    const edges = model.episodicEdgesByEventId.get(event.id) || []
    if (selectedRelations.size && !edges.some((edge) => edge.kind === 'entity_relation' && selectedRelations.has(normalizeRelation(edge.relation)))) return false
    if (!query) return true
    const document = event.docId ? model.documentByDocId.get(event.docId) : null
    const entityLabels = edges.flatMap((edge) => [
      model.episodicEntityById.get(edge.source)?.label,
      model.episodicEntityById.get(edge.target)?.label,
      edge.relation
    ])
    return searchable([
      event.label,
      event.title,
      document?.text,
      document?.caption,
      document?.visualSummary,
      document?.transcript,
      document?.scene,
      ...entityLabels
    ]).includes(query)
  })
  const visibleEventIds = new Set(visibleEvents.map((event) => event.id))
  const episodic = buildEpisodicElements(model, visibleEvents, visibleEventIds, expandedEventId)

  const timeRestricted = start > model.timeDomain.start || end < model.timeDomain.end
  const semanticCandidates = [...model.factById.values()].filter((fact) => {
    if (finiteOr(fact.confidence, 0) < finiteOr(filters.semanticMinConfidence, 0.6)) return false
    if (fact.supportCount < finiteOr(filters.semanticMinSupportCount, 1)) return false
    if (selectedRelations.size && !selectedRelations.has(normalizeRelation(fact.relation))) return false
    if (timeRestricted && !fact.supportEventIds.some((eventId) => timeVisibleEventIds.has(eventId))) return false
    if (!query) return true
    return searchable([
      model.semanticEntityById.get(fact.source)?.label,
      fact.relation,
      model.semanticEntityById.get(fact.target)?.label
    ]).includes(query)
  }).sort(compareFacts)

  const visibleFacts = semanticCandidates.slice(0, SEMANTIC_FACT_LIMIT)
  const semantic = buildSemanticElements(model, visibleFacts)

  return {
    episodic,
    semantic,
    visibleEvents,
    visibleEventIds,
    timeVisibleEventIds,
    visibleFacts,
    visibleFactIds: new Set(visibleFacts.map((fact) => fact.id)),
    semanticCandidateCount: semanticCandidates.length,
    relationOptions: model.relationOptions,
    timeDomain: model.timeDomain
  }
}

function buildEpisodicElements(model, events, eventIds, expandedEventId) {
  const elements = []
  const eventPositions = new Map()
  events.forEach((event, index) => {
    const position = { x: 100 + index * 220, y: 110 }
    eventPositions.set(event.id, position)
    elements.push({
      group: 'nodes',
      data: {
        id: event.id,
        graphKind: 'event',
        label: eventLabel(event),
        shortTime: formatShortTimelineSeconds(event.eventTime.timelineStartSeconds),
        confidence: finiteOr(event.confidence, 0),
        visualWeight: Math.max(0.18, finiteOr(event.confidence, 0)),
        nodeColorIndex: stableNodeColorIndex(event.id)
      },
      position
    })
  })

  for (const edge of model.graph.episodic.edges) {
    if (edge.kind === 'before' && eventIds.has(edge.source) && eventIds.has(edge.target)) {
      elements.push({ group: 'edges', data: edgeData(edge) })
    }
  }

  if (!expandedEventId || !eventIds.has(expandedEventId)) return { elements, eventPositions }
  const expandedEdges = model.episodicEdgesByEventId.get(expandedEventId) || []
  const entityIds = new Set()
  for (const edge of expandedEdges) {
    if (edge.kind === 'mentions') entityIds.add(edge.target)
    if (edge.kind === 'entity_relation') {
      entityIds.add(edge.source)
      entityIds.add(edge.target)
    }
  }
  const relationEdges = expandedEdges.filter((edge) => edge.kind === 'entity_relation')
  const entities = [...entityIds].map((id) => model.episodicEntityById.get(id)).filter(Boolean)
  const entityRings = arrangeEntityRings(entities, relationEdges)
  const origin = eventPositions.get(expandedEventId) || { x: 120, y: 120 }
  entityRings.forEach((ringEntities, ringIndex) => {
    const ringCount = ringEntities.length
    if (!ringCount) return
    const radius = semicircleRadius(ringCount, 132 + ringIndex * 96)
    for (let ringIndexWithin = 0; ringIndexWithin < ringCount; ringIndexWithin += 1) {
      const entity = ringEntities[ringIndexWithin]
      const angle = ringCount === 1
        ? Math.PI / 2
        : (Math.PI * 0.12) + ((Math.PI * 0.76) * ringIndexWithin / (ringCount - 1))
      const position = {
        x: origin.x + Math.cos(angle) * radius,
        y: origin.y + Math.sin(angle) * radius
      }
      elements.push({
        group: 'nodes',
        data: {
          id: entity.id,
          graphKind: 'entity',
          label: entity.label,
          confidence: 1,
          nodeColorIndex: stableNodeColorIndex(entity.id)
        },
        position
      })
    }
  })
  for (const edge of expandedEdges) {
    if ((edge.kind === 'mentions' || edge.kind === 'entity_relation') && entityIds.has(edge.target)) {
      elements.push({ group: 'edges', data: edgeData(edge) })
    }
  }
  return { elements, eventPositions }
}

function buildSemanticElements(model, facts) {
  const entityIds = new Set(facts.flatMap((fact) => [fact.source, fact.target]))
  const elements = [...entityIds].map((id) => {
    const entity = model.semanticEntityById.get(id)
    return {
      group: 'nodes',
      data: {
        id,
        graphKind: 'entity',
        label: entity?.label || id,
        factCount: entity?.factCount || 1,
        totalSupportCount: entity?.totalSupportCount || 0,
        visualWeight: Math.min(30, Math.max(1, entity?.factCount || 1)),
        supportWeight: Math.min(50, Math.max(0, entity?.totalSupportCount || 0)),
        nodeColorIndex: stableNodeColorIndex(id)
      }
    }
  })
  for (const fact of facts) elements.push({ group: 'edges', data: edgeData(fact) })
  return { elements }
}

function edgeData(edge) {
  const supportLabel = edge.kind === 'semantic_fact' && edge.supportCount > 1 ? ` (${edge.supportCount})` : ''
  const mentionLabel = edge.kind === 'mentions' && edge.occurrenceCount > 1 ? `mentions ×${edge.occurrenceCount}` : ''
  return {
    id: edge.id,
    source: edge.source,
    target: edge.target,
    graphKind: edge.kind,
    relation: edge.relation,
    label: mentionLabel || `${edge.label || edge.relation || ''}${supportLabel}`,
    occurrenceCount: edge.occurrenceCount,
    confidence: finiteOr(edge.confidence, 1),
    supportCount: edge.supportCount,
    habitStrength: edge.habitStrength,
    relationGroup: relationGroup(edge.relation)
  }
}

export function relationGroup(relation) {
  const value = normalizeRelation(relation)
  for (const [group, relations] of Object.entries(RELATION_GROUPS)) {
    if (relations.has(value)) return group
  }
  return 'other'
}

export function formatTimelineSeconds(value) {
  const numeric = Number(value)
  if (!Number.isFinite(numeric)) return '—'
  const day = Math.floor(numeric / 86400) + 1
  const secondsInDay = Math.max(0, numeric % 86400)
  const hours = Math.floor(secondsInDay / 3600)
  const minutes = Math.floor((secondsInDay % 3600) / 60)
  const seconds = Math.floor(secondsInDay % 60)
  return `DAY${day} ${pad(hours)}:${pad(minutes)}:${pad(seconds)}`
}

export function formatEventRange(event) {
  const start = event?.eventTime?.timelineStartSeconds
  const end = event?.eventTime?.timelineEndSeconds
  if (!Number.isFinite(start)) return event?.label || 'Time unavailable'
  return `${formatTimelineSeconds(start)} – ${formatTimelineSeconds(Number.isFinite(end) ? end : start)}`
}

export function safeDisplay(value) {
  if (value === null || value === undefined || value === '') return '—'
  if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') return String(value)
  if (Array.isArray(value)) return value.map(safeDisplay).join(', ')
  if (typeof value === 'object') return Object.values(value).filter((item) => item !== null && item !== undefined && item !== '').map(safeDisplay).join(' · ')
  return String(value)
}

function eventLabel(event) {
  const time = formatShortTimelineSeconds(event.eventTime.timelineStartSeconds)
  const title = event.title || event.label || 'Untitled event'
  const confidence = finiteOr(event.confidence, 0).toFixed(2)
  return [time, title, `confidence ${confidence}`].filter(Boolean).join('\n')
}

function formatShortTimelineSeconds(value) {
  const numeric = Number(value)
  if (!Number.isFinite(numeric)) return 'TIME —'
  const day = Math.floor(numeric / 86400) + 1
  const secondsInDay = Math.max(0, numeric % 86400)
  const hours = Math.floor(secondsInDay / 3600)
  const minutes = Math.floor((secondsInDay % 3600) / 60)
  const seconds = Math.floor(secondsInDay % 60)
  return `D${day} ${pad(hours)}:${pad(minutes)}:${pad(seconds)}`
}

function semicircleRadius(count, minimum) {
  if (count <= 1) return minimum
  return Math.max(minimum, ((count - 1) * 82) / (Math.PI * 0.76))
}

function arrangeEntityRings(entities, edges) {
  if (entities.length <= 6) return [sortEntitiesByConnectivity(entities, edges)]

  const adjacency = entityAdjacency(entities, edges)
  const ranked = [...entities].sort((left, right) => (
    (adjacency.get(right.id)?.size || 0) - (adjacency.get(left.id)?.size || 0)
    || left.label.localeCompare(right.label)
  ))
  const innerCount = Math.min(6, Math.max(2, Math.ceil(entities.length / 3)))
  const inner = ranked.slice(0, innerCount)
  const innerIndex = new Map(inner.map((entity, index) => [entity.id, index]))
  const outer = ranked.slice(innerCount).sort((left, right) => (
    neighborBarycenter(left.id, adjacency, innerIndex) - neighborBarycenter(right.id, adjacency, innerIndex)
    || (adjacency.get(right.id)?.size || 0) - (adjacency.get(left.id)?.size || 0)
    || left.label.localeCompare(right.label)
  ))
  return [inner, outer]
}

function sortEntitiesByConnectivity(entities, edges) {
  const adjacency = entityAdjacency(entities, edges)
  return [...entities].sort((left, right) => (
    (adjacency.get(right.id)?.size || 0) - (adjacency.get(left.id)?.size || 0)
    || left.label.localeCompare(right.label)
  ))
}

function entityAdjacency(entities, edges) {
  const adjacency = new Map(entities.map((entity) => [entity.id, new Set()]))
  for (const edge of edges) {
    if (!adjacency.has(edge.source) || !adjacency.has(edge.target)) continue
    adjacency.get(edge.source).add(edge.target)
    adjacency.get(edge.target).add(edge.source)
  }
  return adjacency
}

function neighborBarycenter(entityId, adjacency, innerIndex) {
  const indexes = [...(adjacency.get(entityId) || [])]
    .map((id) => innerIndex.get(id))
    .filter(Number.isInteger)
  if (!indexes.length) return Number.MAX_SAFE_INTEGER
  return indexes.reduce((total, index) => total + index, 0) / indexes.length
}

export function stableNodeColorIndex(id) {
  let hash = 2166136261
  for (const character of String(id)) {
    hash ^= character.codePointAt(0)
    hash = Math.imul(hash, 16777619)
  }
  return String((hash >>> 0) % 12)
}

function eventOverlaps(event, start, end) {
  const eventStart = finiteOr(event.eventTime.timelineStartSeconds, event.eventTime.startSeconds, start)
  const eventEnd = finiteOr(event.eventTime.timelineEndSeconds, event.eventTime.endSeconds, eventStart)
  return eventEnd >= start && eventStart <= end
}

function compareEvents(left, right) {
  return finiteOr(left.eventTime.timelineStartSeconds, 0) - finiteOr(right.eventTime.timelineStartSeconds, 0)
    || finiteOr(left.eventTime.timelineEndSeconds, 0) - finiteOr(right.eventTime.timelineEndSeconds, 0)
    || left.id.localeCompare(right.id)
}

function compareFacts(left, right) {
  return right.supportCount - left.supportCount
    || finiteOr(right.confidence, 0) - finiteOr(left.confidence, 0)
    || left.id.localeCompare(right.id)
}

function normalizeSearch(value) {
  return String(value || '').normalize('NFKC').trim().replace(/\s+/g, ' ').toLocaleLowerCase()
}

function searchable(values) {
  return normalizeSearch(values.filter((value) => value !== null && value !== undefined).map(safeDisplay).join(' '))
}

function normalizeRelation(value) {
  return normalizeSearch(value)
}

function invalidGraphResponse() {
  const error = new Error('The memory graph response was incomplete or invalid.')
  error.code = 'invalid_memory_graph_response'
  return error
}

function first(...values) {
  return values.find((value) => value !== undefined && value !== null)
}

function numericOrNull(value) {
  const numeric = Number(value)
  return value !== '' && value !== null && value !== undefined && Number.isFinite(numeric) ? numeric : null
}

function numberOrZero(value) {
  return numericOrNull(value) ?? 0
}

function finiteOr(...values) {
  const found = values.find((value) => value !== null && value !== undefined && value !== '' && Number.isFinite(Number(value)))
  return found === undefined ? 0 : Number(found)
}

function finiteMin(values) {
  const finite = values.filter((value) => Number.isFinite(value))
  return finite.length ? Math.min(...finite) : null
}

function finiteMax(values) {
  const finite = values.filter((value) => Number.isFinite(value))
  return finite.length ? Math.max(...finite) : null
}

function safeValue(value) {
  return value === undefined || value === null ? '' : value
}

function safeArray(value) {
  return Array.isArray(value) ? value : []
}

function stringArray(value) {
  return safeArray(value).map((item) => String(item)).filter(Boolean)
}

function stringMap(value) {
  if (!isPlainObject(value)) return {}
  return Object.fromEntries(Object.entries(value).map(([key, item]) => [String(key), String(item)]).filter(([, item]) => item))
}

function stringArrayMap(value) {
  if (!isPlainObject(value)) return {}
  return Object.fromEntries(Object.entries(value).map(([key, items]) => [String(key), [...new Set(stringArray(items))]]))
}

function camelizeSmallObject(value) {
  if (Array.isArray(value)) return value.map(camelizeSmallObject)
  if (!isPlainObject(value)) return value && typeof value === 'object' ? {} : value
  return Object.fromEntries(Object.entries(value).map(([key, item]) => [
    key.replace(/_([a-z])/g, (_, character) => character.toUpperCase()),
    camelizeSmallObject(item)
  ]))
}

function isPlainObject(value) {
  return !!value && Object.prototype.toString.call(value) === '[object Object]'
}

function pad(value) {
  return String(value).padStart(2, '0')
}
