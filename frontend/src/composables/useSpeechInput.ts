import { onBeforeUnmount, ref } from 'vue'

interface SpeechInputOptions {
  onFinal: (text: string) => void
  onError?: (message: string) => void
  silenceTimeoutMs?: number
}

function speechErrorMessage(code: string): string {
  switch (code) {
    case 'not-allowed':
    case 'service-not-allowed':
      return '麦克风权限被拒绝'
    case 'audio-capture':
      return '没有找到可用的麦克风'
    case 'network':
      return '语音识别服务不可用'
    case 'language-not-supported':
      return '当前语言不支持语音识别'
    default:
      return '语音识别失败，请重试'
  }
}

export function useSpeechInput(options: SpeechInputOptions) {
  const silenceTimeout = options.silenceTimeoutMs ?? 3000
  const supported = ref(false)
  const listening = ref(false)
  let recognition: SpeechRecognition | null = null
  let silenceTimer: number | null = null

  if (typeof window !== 'undefined') {
    supported.value = Boolean(window.SpeechRecognition || window.webkitSpeechRecognition)
  }

  function clearSilenceTimer(): void {
    if (silenceTimer !== null) {
      window.clearTimeout(silenceTimer)
      silenceTimer = null
    }
  }

  function scheduleSilenceStop(): void {
    clearSilenceTimer()
    silenceTimer = window.setTimeout(() => {
      silenceTimer = null
      if (listening.value) stop()
    }, silenceTimeout)
  }

  function stop(): void {
    clearSilenceTimer()
    const current = recognition
    recognition = null
    listening.value = false
    try {
      current?.stop()
    } catch {
      // 已经结束时会抛 InvalidStateError
    }
  }

  function create(): SpeechRecognition | null {
    const Constructor = window.SpeechRecognition || window.webkitSpeechRecognition
    if (!Constructor) return null
    const instance = new Constructor()
    instance.lang = document.documentElement.lang || navigator.language || 'zh-CN'
    instance.continuous = true
    instance.interimResults = true
    instance.maxAlternatives = 1

    instance.onstart = () => {
      listening.value = true
      scheduleSilenceStop()
    }
    instance.onresult = (event) => {
      let finalText = ''
      for (let index = event.resultIndex; index < event.results.length; index += 1) {
        const result = event.results[index]
        if (!result) continue
        const transcript = result[0]?.transcript ?? ''
        if (result.isFinal) finalText += transcript
      }
      if (finalText.trim()) options.onFinal(finalText.trim())
      scheduleSilenceStop()
    }
    instance.onerror = (event) => {
      clearSilenceTimer()
      listening.value = false
      if (event.error !== 'aborted' && event.error !== 'no-speech') {
        options.onError?.(speechErrorMessage(event.error))
      }
    }
    instance.onend = () => {
      clearSilenceTimer()
      listening.value = false
    }
    return instance
  }

  function start(): void {
    if (!supported.value || listening.value) return
    stop()
    recognition = create()
    if (!recognition) {
      options.onError?.('当前浏览器不支持语音识别')
      return
    }
    try {
      recognition.start()
    } catch {
      listening.value = false
      recognition = null
      options.onError?.('无法启动语音识别，请稍后重试')
    }
  }

  function toggle(): void {
    if (listening.value) stop()
    else start()
  }

  onBeforeUnmount(stop)

  return { supported, listening, start, stop, toggle }
}
