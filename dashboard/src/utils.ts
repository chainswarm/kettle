/**
 * Truncate an address/peer ID in 6...4...6 format.
 * Example: "12D3KooWKxAhu5U8SreDZpokVkN6ciTBbsHxteo3Vmq6Cpuf8KEt"
 *       → "12D3Ko...5U8S...f8KEt"
 */
export function truncateAddress(addr: string): string {
  if (!addr || addr.length <= 20) return addr || ''
  const mid = Math.floor(addr.length / 2)
  return `${addr.slice(0, 6)}...${addr.slice(mid - 2, mid + 2)}...${addr.slice(-5)}`
}
