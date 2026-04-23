import { Download, ExternalLink, Eye, LoaderCircle, RefreshCw } from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'

import { api } from '@/lib/api'
import { Button, PageCard, SectionHeader, StatusPill } from '@/components/ui'
import type { ApiClientConfig } from '@/lib/api'
import type { AnalysisDetail, AnalysisEvent } from '@/lib/types'
import { formatDate } from '@/lib/utils'

const TEXT_PREVIEW_BYTE_LIMIT = 20 * 1024
const TEXT_PREVIEW_LINE_LIMIT = 200

type OutputPreviewState =
  | { status: 'idle' }
  | { status: 'loading' }
  | { status: 'error'; message: string }
  | { status: 'ready'; kind: 'text'; content: string; truncated: boolean }
  | { status: 'ready'; kind: 'image'; imageUrl: string }

function isTerminalAnalysisStatus(status: string | null | undefined) {
  return new Set(['success', 'failed', 'waiting_for_human']).has(String(status || '').trim())
}

function truncateTextPreview(source: string) {
  const encoder = new TextEncoder()
  const lines = source.split('\n')
  const keptLines: string[] = []
  let byteLength = 0
  let truncated = false

  for (const line of lines) {
    const normalizedLine = keptLines.length ? `\n${line}` : line
    const nextByteLength = byteLength + encoder.encode(normalizedLine).length
    if (nextByteLength > TEXT_PREVIEW_BYTE_LIMIT || keptLines.length >= TEXT_PREVIEW_LINE_LIMIT) {
      truncated = true
      break
    }
    keptLines.push(line)
    byteLength = nextByteLength
  }

  return {
    content: keptLines.join('\n'),
    truncated: truncated || keptLines.length < lines.length,
  }
}

function triggerBrowserDownload(blob: Blob, fileName: string) {
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = fileName
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  window.setTimeout(() => URL.revokeObjectURL(url), 0)
}

export function AnalysisDetailPage({
  config,
  detail,
  events,
  isLiveRefreshing,
}: {
  config: ApiClientConfig
  detail: AnalysisDetail | undefined
  events: AnalysisEvent[]
  isLiveRefreshing: boolean
}) {
  const [previewByOutputId, setPreviewByOutputId] = useState<Record<string, OutputPreviewState>>({})
  const [activePreviewOutputId, setActivePreviewOutputId] = useState<string | null>(null)
  const [downloadingOutputId, setDownloadingOutputId] = useState<string | null>(null)
  const imagePreviewUrlsRef = useRef<Record<string, string>>({})

  useEffect(() => {
    Object.values(imagePreviewUrlsRef.current).forEach((url) => URL.revokeObjectURL(url))
    imagePreviewUrlsRef.current = {}
    setPreviewByOutputId({})
    setActivePreviewOutputId(null)
    setDownloadingOutputId(null)
  }, [detail?.analysisId])

  useEffect(() => {
    return () => {
      Object.values(imagePreviewUrlsRef.current).forEach((url) => URL.revokeObjectURL(url))
    }
  }, [])

  const liveStatusTone = useMemo(() => {
    if (!detail?.status) return 'neutral'
    if (detail.status === 'failed') return 'error'
    if (detail.status === 'waiting_for_human') return 'warning'
    if (detail.status === 'success') return 'success'
    return 'neutral'
  }, [detail?.status])

  if (!detail) {
    return <div className="rounded-3xl border border-border bg-surface px-6 py-10 text-sm text-muted">正在加载分析详情…</div>
  }
  const analysisId = detail.analysisId

  async function loadPreview(output: AnalysisDetail['outputs'][number]) {
    if (!output.downloadUrl) {
      setPreviewByOutputId((current) => ({
        ...current,
        [output.id]: { status: 'error', message: '当前结果还不能读取，请稍后再试。' },
      }))
      setActivePreviewOutputId(output.id)
      return
    }
    setActivePreviewOutputId(output.id)
    setPreviewByOutputId((current) => ({ ...current, [output.id]: { status: 'loading' } }))
    try {
      const { blob } = await api.getAnalysisOutput(config, analysisId, output.id)
      if (output.previewKind === 'image') {
        if (imagePreviewUrlsRef.current[output.id]) {
          URL.revokeObjectURL(imagePreviewUrlsRef.current[output.id])
        }
        const imageUrl = URL.createObjectURL(blob)
        imagePreviewUrlsRef.current[output.id] = imageUrl
        setPreviewByOutputId((current) => ({
          ...current,
          [output.id]: { status: 'ready', kind: 'image', imageUrl },
        }))
        return
      }
      const textContent = await blob.text()
      const preview = truncateTextPreview(textContent)
      setPreviewByOutputId((current) => ({
        ...current,
        [output.id]: { status: 'ready', kind: 'text', content: preview.content, truncated: preview.truncated },
      }))
    } catch (error) {
      setPreviewByOutputId((current) => ({
        ...current,
        [output.id]: { status: 'error', message: error instanceof Error ? error.message : '预览失败' },
      }))
    }
  }

  async function downloadOutput(output: AnalysisDetail['outputs'][number]) {
    if (!output.downloadUrl) {
      setPreviewByOutputId((current) => ({
        ...current,
        [output.id]: { status: 'error', message: '当前结果还不能下载，请稍后再试。' },
      }))
      return
    }
    setDownloadingOutputId(output.id)
    try {
      const { blob, fileName } = await api.getAnalysisOutput(config, analysisId, output.id)
      triggerBrowserDownload(blob, fileName || output.title)
    } catch (error) {
      setPreviewByOutputId((current) => ({
        ...current,
        [output.id]: { status: 'error', message: error instanceof Error ? error.message : '下载失败' },
      }))
      setActivePreviewOutputId(output.id)
    } finally {
      setDownloadingOutputId((current) => (current === output.id ? null : current))
    }
  }

  return (
    <div className="space-y-6">
      <PageCard>
        <SectionHeader title={detail.title} description={detail.question} action={<StatusPill tone={detail.status === 'success' ? 'success' : detail.status === 'failed' ? 'error' : 'neutral'}>{detail.statusLabel}</StatusPill>} />
        <div className="border-b border-border px-6 py-4">
          <div className="flex flex-wrap items-center justify-between gap-3 rounded-[24px] bg-surface-2 px-4 py-4">
            <div>
              <div className="text-xs font-semibold uppercase tracking-[0.14em] text-muted">任务状态</div>
              <div className="mt-2 text-sm font-semibold text-ink">
                {isLiveRefreshing ? '任务进行中，页面会自动刷新。' : isTerminalAnalysisStatus(detail.status) ? '任务已进入终态，页面已停止自动刷新。' : '任务状态已同步。'}
              </div>
            </div>
            <StatusPill tone={liveStatusTone}>
              {isLiveRefreshing ? '实时刷新中' : detail.statusLabel}
            </StatusPill>
          </div>
        </div>
        <div className="grid gap-4 border-b border-border px-6 py-5 md:grid-cols-3">
          <MetricStrip label="当前阶段" value={detail.progress.currentStep} />
          <MetricStrip label="结果产物" value={String(detail.outputs.length)} />
          <MetricStrip label="最后更新" value={formatDate(detail.updatedAt)} />
        </div>
        <div className="grid gap-5 px-6 py-6 lg:grid-cols-[1.15fr_0.85fr]">
          <div className="space-y-5">
            <div className="rounded-[30px] border border-border bg-gradient-to-br from-[#163a34] to-[#0f2f29] p-6 text-white shadow-panel">
              <div className="text-sm font-semibold text-white">结论摘要</div>
              <p className="mt-3 text-base leading-8 text-white/78">{detail.summary}</p>
              {detail.nextAction ? <p className="mt-5 rounded-2xl bg-white px-4 py-3 text-sm text-ink">建议下一步：{detail.nextAction}</p> : null}
            </div>
            <div className="rounded-[28px] border border-border bg-surface-2 p-5">
              <div className="text-sm font-semibold text-ink">关键发现</div>
              <ul className="mt-3 space-y-2 text-sm leading-6 text-muted">
                {detail.keyFindings.map((item) => <li key={item}>• {item}</li>)}
                {!detail.keyFindings.length ? <li>暂无关键发现。</li> : null}
              </ul>
            </div>
            <div className="rounded-[28px] border border-border bg-surface-2 p-5">
              <div className="text-sm font-semibold text-ink">证据索引</div>
              <div className="mt-3 flex flex-wrap gap-2">
                {detail.evidence.map((item) => <span key={item.id} className="rounded-full border border-border bg-white px-3 py-1 text-xs text-muted">{item.label}</span>)}
                {!detail.evidence.length ? <span className="text-sm text-muted">暂无证据索引。</span> : null}
              </div>
            </div>
          </div>
          <div className="space-y-5">
            <div className="rounded-[28px] border border-border bg-surface-2 p-5">
              <div className="text-sm font-semibold text-ink">进度概览</div>
              <dl className="mt-4 space-y-3 text-sm text-muted">
                <div className="flex justify-between gap-3"><dt>当前阶段</dt><dd className="font-medium text-ink">{detail.progress.currentStep}</dd></div>
                <div className="flex justify-between gap-3"><dt>执行环节</dt><dd className="font-medium text-ink">{detail.progress.executionCount}</dd></div>
                <div className="flex justify-between gap-3"><dt>最后更新时间</dt><dd className="font-medium text-ink">{formatDate(detail.updatedAt)}</dd></div>
              </dl>
              <p className="mt-4 rounded-2xl bg-white px-4 py-3 text-sm leading-6 text-muted">{detail.progress.activitySummary}</p>
            </div>
            <div className="rounded-[28px] border border-border bg-surface-2 p-5">
              <div className="text-sm font-semibold text-ink">风险与注意事项</div>
              <ul className="mt-3 space-y-2 text-sm leading-6 text-muted">
                {detail.warnings.map((warning) => <li key={warning}>• {warning}</li>)}
                {!detail.warnings.length ? <li>当前没有额外风险提示。</li> : null}
              </ul>
            </div>
            <div className="rounded-[28px] border border-border bg-surface-2 p-5">
              <div className="text-sm font-semibold text-ink">结果产物</div>
              <div className="mt-3 space-y-3">
                {detail.outputs.map((output) => {
                  const previewState = previewByOutputId[output.id] ?? ({ status: 'idle' } satisfies OutputPreviewState)
                  return (
                    <div key={output.id} className="rounded-2xl border border-border bg-white px-4 py-3">
                    <div className="flex items-start justify-between gap-3">
                      <div>
                        <div className="font-medium text-ink">{output.title}</div>
                        <div className="mt-1 text-xs text-muted">{output.type} · {output.summary || '无摘要'}</div>
                      </div>
                      <div className="flex flex-wrap gap-2">
                        {output.previewKind !== 'none' ? (
                          <Button
                            className="gap-1.5"
                            disabled={!output.downloadUrl}
                            variant="secondary"
                            onClick={() => {
                              void loadPreview(output)
                            }}
                            type="button"
                          >
                            {previewState.status === 'loading' && activePreviewOutputId === output.id ? (
                              <LoaderCircle className="h-3.5 w-3.5 animate-spin" />
                            ) : (
                              <Eye className="h-3.5 w-3.5" />
                            )}
                            预览
                          </Button>
                        ) : null}
                        <Button
                          className="gap-1.5"
                          disabled={!output.downloadUrl}
                          variant="ghost"
                          onClick={() => {
                            void downloadOutput(output)
                          }}
                          type="button"
                        >
                          {downloadingOutputId === output.id ? (
                            <LoaderCircle className="h-3.5 w-3.5 animate-spin" />
                          ) : (
                            <Download className="h-3.5 w-3.5" />
                          )}
                          下载
                        </Button>
                      </div>
                    </div>
                    {activePreviewOutputId === output.id ? (
                      <div className="mt-4 rounded-2xl border border-border bg-surface-2 p-4">
                        {previewState.status === 'loading' ? (
                          <div className="flex items-center gap-2 text-sm text-muted">
                            <LoaderCircle className="h-4 w-4 animate-spin" />
                            正在加载预览…
                          </div>
                        ) : null}
                        {previewState.status === 'error' ? (
                          <div className="space-y-3">
                            <div className="text-sm text-error">{previewState.message}</div>
                            <Button className="gap-1.5" variant="secondary" onClick={() => void loadPreview(output)} type="button">
                              <RefreshCw className="h-3.5 w-3.5" />
                              重试
                            </Button>
                          </div>
                        ) : null}
                        {previewState.status === 'ready' && previewState.kind === 'text' ? (
                          <div className="space-y-3">
                            <pre className="max-h-[420px] overflow-auto rounded-2xl bg-[#10231f] px-4 py-4 text-xs leading-6 text-white">
                              {previewState.content || '预览为空。'}
                            </pre>
                            {previewState.truncated ? (
                              <div className="flex flex-wrap items-center justify-between gap-3 rounded-2xl bg-white px-3 py-3 text-xs text-muted">
                                <span>预览已截断：仅显示前 20 KB 或前 200 行。</span>
                                <button
                                  className="inline-flex items-center gap-1 font-semibold text-primary hover:text-primary-hover"
                                  onClick={() => {
                                    void downloadOutput(output)
                                  }}
                                  type="button"
                                >
                                  下载完整文件
                                  <ExternalLink className="h-3.5 w-3.5" />
                                </button>
                              </div>
                            ) : null}
                          </div>
                        ) : null}
                        {previewState.status === 'ready' && previewState.kind === 'image' ? (
                          <div className="overflow-hidden rounded-2xl border border-border bg-white">
                            <img
                              alt={output.title}
                              className="max-h-[480px] w-full object-contain"
                              src={previewState.imageUrl}
                            />
                          </div>
                        ) : null}
                      </div>
                    ) : null}
                    </div>
                  )
                })}
                {!detail.outputs.length ? <div className="text-sm text-muted">还没有生成结果产物。</div> : null}
              </div>
            </div>
          </div>
        </div>
      </PageCard>

      <PageCard>
        <SectionHeader title="进度事件" description="按时间顺序查看分析任务最近经历的关键步骤。" />
        <div className="px-6 py-5">
          <div className="space-y-3">
            {events.map((event) => (
              <div key={event.eventId} className="rounded-[24px] border border-border bg-surface-2 px-4 py-4 transition hover:bg-white">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <div className="flex items-center gap-2">
                      <div className="text-sm font-semibold text-ink">{event.title}</div>
                      {event.status ? <StatusPill tone={event.status === 'failed' ? 'error' : event.status === 'success' ? 'success' : 'neutral'}>{event.status}</StatusPill> : null}
                    </div>
                    <div className="mt-1 text-sm text-muted">{event.message || '—'}</div>
                  </div>
                  <div className="font-mono text-xs text-muted">{formatDate(event.timestamp)}</div>
                </div>
              </div>
            ))}
            {!events.length ? <div className="text-sm text-muted">当前还没有事件记录。</div> : null}
          </div>
        </div>
      </PageCard>
    </div>
  )
}

function MetricStrip({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-2xl border border-border bg-surface-2 px-4 py-4">
      <div className="text-xs font-semibold uppercase tracking-[0.14em] text-muted">{label}</div>
      <div className="mt-2 text-sm font-semibold text-ink">{value}</div>
    </div>
  )
}
