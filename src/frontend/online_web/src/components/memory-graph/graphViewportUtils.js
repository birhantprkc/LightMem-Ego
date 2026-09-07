const AUTO_FOCUS_MAX_ZOOM = 1.45
const AUTO_FOCUS_PADDING = 120

export function connectedGraphContext(elements) {
  const edges = elements.edges().union(elements.nodes().connectedEdges())
  return elements.union(edges).union(edges.connectedNodes())
}

export function focusGraphElements(cy, elements, duration) {
  const viewport = cy.getFitViewport(elements, AUTO_FOCUS_PADDING)
  if (!viewport) return

  cy.stop()
  cy.animate({
    zoom: Math.min(viewport.zoom, AUTO_FOCUS_MAX_ZOOM),
    center: { eles: elements }
  }, { duration })
}
