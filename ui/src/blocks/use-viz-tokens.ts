import { observeTheme, readVizTokens, type VizTokens } from "@atelier/theme/viz"
import { useEffect, useState } from "react"

/** Chart colours for the active direction and mode, re-read on any change. */
export function useVizTokens(): VizTokens | null {
  const [tokens, setTokens] = useState<VizTokens | null>(null)
  useEffect(() => {
    const read = () => setTokens(readVizTokens())
    read()
    return observeTheme(read)
  }, [])
  return tokens
}
