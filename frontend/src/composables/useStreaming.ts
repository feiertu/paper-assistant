/**
 * Composable for handling SSE streaming responses.
 * Parses Server-Sent Events from a ReadableStream.
 */

export async function* streamSSE(response: Response): AsyncGenerator<string> {
  if (!response.ok) {
    const text = await response.text().catch(() => '')
    throw new Error(`Stream error ${response.status}: ${text}`)
  }

  const reader = response.body?.getReader()
  if (!reader) throw new Error('Response body is not readable')

  const decoder = new TextDecoder()
  let buffer = ''

  try {
    while (true) {
      const { done, value } = await reader.read()
      if (done) break

      buffer += decoder.decode(value, { stream: true })
      const lines = buffer.split('\n')
      buffer = lines.pop() || ''

      for (const line of lines) {
        if (line.startsWith('data:')) {
          const token = line.slice(5).trim()
          if (token === '[DONE]') return
          yield token
        }
      }
    }
  } finally {
    reader.releaseLock()
  }
}

/**
 * Parse SSE stream for Agent events (JSON lines).
 */
export async function* streamAgentSSE(response: Response): AsyncGenerator<{ type: string; [key: string]: unknown }> {
  if (!response.ok) {
    const text = await response.text().catch(() => '')
    throw new Error(`Stream error ${response.status}: ${text}`)
  }

  const reader = response.body?.getReader()
  if (!reader) throw new Error('Response body is not readable')

  const decoder = new TextDecoder()
  let buffer = ''

  try {
    while (true) {
      const { done, value } = await reader.read()
      if (done) break

      buffer += decoder.decode(value, { stream: true })
      const lines = buffer.split('\n')
      buffer = lines.pop() || ''

      for (const line of lines) {
        if (line.startsWith('data:')) {
          const dataStr = line.slice(5).trim()
          if (dataStr === '[DONE]') return
          try {
            yield JSON.parse(dataStr)
          } catch {
            // Skip malformed JSON
          }
        }
      }
    }
  } finally {
    reader.releaseLock()
  }
}
