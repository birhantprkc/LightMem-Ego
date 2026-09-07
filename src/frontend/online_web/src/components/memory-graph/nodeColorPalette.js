export const NODE_COLOR_PALETTE = Object.freeze([
  { fill: '#5eead4', border: '#0f766e', text: '#134e4a', shadow: '#14b8a6' },
  { fill: '#67e8f9', border: '#0e7490', text: '#164e63', shadow: '#06b6d4' },
  { fill: '#7dd3fc', border: '#0369a1', text: '#0c4a6e', shadow: '#0ea5e9' },
  { fill: '#c4b5fd', border: '#7c3aed', text: '#3b0764', shadow: '#8b5cf6' },
  { fill: '#a5b4fc', border: '#4f46e5', text: '#312e81', shadow: '#6366f1' },
  { fill: '#d8b4fe', border: '#9333ea', text: '#581c87', shadow: '#a855f7' },
  { fill: '#fcd34d', border: '#d97706', text: '#451a03', shadow: '#f59e0b' },
  { fill: '#fdba74', border: '#ea580c', text: '#7c2d12', shadow: '#f97316' },
  { fill: '#bef264', border: '#65a30d', text: '#365314', shadow: '#84cc16' },
  { fill: '#f9a8d4', border: '#db2777', text: '#500724', shadow: '#ec4899' },
  { fill: '#fda4af', border: '#e11d48', text: '#881337', shadow: '#f43f5e' },
  { fill: '#fca5a5', border: '#dc2626', text: '#7f1d1d', shadow: '#ef4444' }
])

export const NODE_COLOR_STYLES = NODE_COLOR_PALETTE.map((color, index) => ({
  selector: `node[nodeColorIndex = "${index}"]`,
  style: {
    'background-color': color.fill,
    'border-color': color.border,
    color: color.text,
    'shadow-color': color.shadow
  }
}))
