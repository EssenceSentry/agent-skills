/** Pictures pasted or attached to a message, made small enough to send. */

export const LONGEST = 2000 // pixels on the long side; both tools downscale beyond this
export const MAX_BYTES = 3_500_000
const SENDABLE = new Set(["image/png", "image/jpeg", "image/gif", "image/webp"])

export type Pasted = { media: string; data: string; preview: string }

export function fitWithin(width: number, height: number, max: number) {
  const scale = Math.min(1, max / Math.max(width, height))
  return { width: Math.round(width * scale), height: Math.round(height * scale) }
}

export function needsShrinking(image: { width: number; height: number; bytes: number }) {
  return Math.max(image.width, image.height) > LONGEST || image.bytes > MAX_BYTES
}

function read(file: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(String(reader.result))
    reader.onerror = () => reject(reader.error)
    reader.readAsDataURL(file)
  })
}

function load(url: string): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const image = new Image()
    image.onload = () => resolve(image)
    image.onerror = () => reject(new Error("that file isn't a picture this browser can read"))
    image.src = url
  })
}

/** A file as a picture to send: as it is when it fits, else redrawn smaller as JPEG. */
export async function prepare(file: File): Promise<Pasted> {
  const url = await read(file)
  const image = await load(url)
  const size = { width: image.naturalWidth, height: image.naturalHeight, bytes: file.size }
  if (SENDABLE.has(file.type) && !needsShrinking(size)) {
    return { media: file.type, data: url.slice(url.indexOf(",") + 1), preview: url }
  }
  const fit = fitWithin(size.width, size.height, LONGEST)
  const canvas = document.createElement("canvas")
  canvas.width = fit.width
  canvas.height = fit.height
  canvas.getContext("2d")?.drawImage(image, 0, 0, fit.width, fit.height)
  const smaller = canvas.toDataURL("image/jpeg", 0.88)
  return { media: "image/jpeg", data: smaller.slice(smaller.indexOf(",") + 1), preview: smaller }
}
