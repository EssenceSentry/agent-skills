/** Chart colours resolved from the active direction's tokens. */
export type VizTokens = {
  surface: string
  text: string
  ink: string
  grid: string
  axis: string
  primary: string
  popover: string
  border: string
  /** Validated categorical slots, in fixed order. Never cycle past the end. */
  series: string[]
  divNeg: string
  divMid: string
  divPos: string
  good: string
  warning: string
  critical: string
  font: string
  labelFont: string
}

/**
 * Reads tokens as literal colours. Tokens hold light-dark() pairs and SVG
 * presentation attributes accept neither var() nor light-dark(), so each
 * colour goes through a probe element that resolves it for the current mode.
 */
export function readVizTokens(root: HTMLElement = document.documentElement): VizTokens {
  const css = getComputedStyle(root)
  const raw = (name: string) => css.getPropertyValue(name).trim()
  const probe = document.createElement("span")
  probe.hidden = true
  root.appendChild(probe)
  const color = (name: string) => {
    if (!raw(name)) return ""
    probe.style.color = `var(${name})`
    return getComputedStyle(probe).color
  }
  const tokens = {
    surface: color("--card"),
    text: color("--viz-text"),
    ink: color("--foreground"),
    grid: color("--viz-grid"),
    axis: color("--viz-axis"),
    primary: color("--primary"),
    popover: color("--popover"),
    border: color("--border"),
    series: [1, 2, 3, 4, 5, 6].map((i) => color(`--series-${i}`)).filter(Boolean),
    divNeg: color("--div-neg"),
    divMid: color("--div-mid"),
    divPos: color("--div-pos"),
    good: color("--status-good"),
    warning: color("--status-warning"),
    critical: color("--status-critical"),
    font: raw("--ff-sans"),
    labelFont: raw("--label-font"),
  }
  probe.remove()
  return tokens
}

/**
 * Calls back when the direction or mode changes: data-direction or data-theme
 * on <html>, or the system setting while data-theme is unset.
 */
export function observeTheme(callback: () => void, root: HTMLElement = document.documentElement) {
  const observer = new MutationObserver(callback)
  observer.observe(root, { attributes: true, attributeFilter: ["data-direction", "data-theme"] })
  const media = matchMedia("(prefers-color-scheme: dark)")
  media.addEventListener("change", callback)
  return () => {
    observer.disconnect()
    media.removeEventListener("change", callback)
  }
}
