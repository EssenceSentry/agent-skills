/** Moving through a gallery's pictures and zooming into one. */

export const MIN_ZOOM = 1
export const MAX_ZOOM = 8

/** How the picture sits: its scale, and how far it is moved, from its top left corner. */
export type View = { scale: number; x: number; y: number }

export const WHOLE: View = { scale: 1, x: 0, y: 0 }

/** The picture `delta` away, round the ends. */
export function step(index: number, count: number, delta: number): number {
  if (count <= 0) return 0
  return (((index + delta) % count) + count) % count
}

/**
 * Zoomed by `factor` around `point`, which stays under the pointer; back to the whole
 * picture once it would be smaller than that.
 */
export function zoomAround(view: View, factor: number, point: { x: number; y: number }): View {
  const scale = Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, view.scale * factor))
  if (scale === MIN_ZOOM) return WHOLE
  const k = scale / view.scale
  return { scale, x: point.x - (point.x - view.x) * k, y: point.y - (point.y - view.y) * k }
}
