/** Date formatting utilities */

export function formatDate(dateStr: string): string {
  if (!dateStr) return '未知'
  try {
    const d = new Date(dateStr)
    if (isNaN(d.getTime())) return dateStr.slice(0, 10)
    return d.toLocaleDateString('zh-CN', { year: 'numeric', month: '2-digit', day: '2-digit' })
  } catch {
    return dateStr.slice(0, 10)
  }
}

export function formatTime(dateStr: string): string {
  if (!dateStr) return ''
  try {
    const d = new Date(dateStr)
    if (isNaN(d.getTime())) return dateStr
    return d.toLocaleString('zh-CN')
  } catch {
    return dateStr
  }
}

export function formatBytes(bytes: number): string {
  if (bytes === 0) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB']
  const i = Math.floor(Math.log(bytes) / Math.log(1024))
  return `${(bytes / Math.pow(1024, i)).toFixed(1)} ${units[i]}`
}

export function truncate(str: string, max: number): string {
  if (!str) return ''
  return str.length > max ? str.slice(0, max) + '…' : str
}
