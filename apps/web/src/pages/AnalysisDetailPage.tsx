import { Activity, AlertTriangle, ArrowRight, Download, ExternalLink, Eye, LoaderCircle, RefreshCw, ShieldCheck, Sparkles } from 'lucide-react'
import { type ReactNode, useEffect, useRef, useState } from 'react'

import { Button, PageCard, SectionHeader, StatusPill } from '@/components/ui'
import { api } from '@/lib/api'
import type { ApiClientConfig } from '@/lib/api'
import type { AnalysisDetail, AnalysisEvent } from '@/lib/types'
import { formatDate } from '@/lib/utils'

const TEXT_PREVIEW_BYTE_LIMIT = 20 * 1024
const TEXT_PREVIEW_LINE_LIMIT = 200

type ViewMode = 'business' | 'runtime'

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
  viewMode,
}: {
  config: ApiClientConfig
  detail: AnalysisDetail | undefined
  events: AnalysisEvent[]
  isLiveRefreshing: boolean
  viewMode: ViewMode
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

  if (!detail) {
    return <div className="rounded-3xl border border-white/10 bg-surface px-6 py-10 text-sm text-muted">正在加载分析详情…</div>
  }

  const analysisId = detail.analysisId
  const liveStatusTone = toneForStatus(detail.status)
  const viewLabel = viewMode === 'runtime' ? '运行时透明度' : '业务结论'

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

  const outputSection = (
    <div className="space-y-3">
      {detail.outputs.map((output) => {
        const previewState = previewByOutputId[output.id] ?? ({ status: 'idle' } satisfies OutputPreviewState)
        return (
          <div key={output.id} className="rounded-2xl border border-white/10 bg-black/20 px-4 py-4">
            <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
              <div className="min-w-0">
                <div className="font-medium text-ink">{output.title}</div>
                <div className="mt-1 text-xs leading-5 text-muted">{output.type} · {output.summary || '无摘要'}</div>
              </div>
              <div className="flex shrink-0 flex-wrap gap-2">
                {output.previewKind !== 'none' ? (
                  <Button
                    className="px-3 py-1.5 text-xs"
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
                  className="px-3 py-1.5 text-xs"
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
              <div className="mt-4 rounded-2xl border border-white/10 bg-white/5 p-4">
                {previewState.status === 'loading' ? (
                  <div className="flex items-center gap-2 text-sm text-muted">
                    <LoaderCircle className="h-4 w-4 animate-spin" />
                    正在加载预览…
                  </div>
                ) : null}
                {previewState.status === 'error' ? (
                  <div className="space-y-3">
                    <div className="text-sm text-rose-200">{previewState.message}</div>
                    <Button className="px-3 py-1.5 text-xs" variant="secondary" onClick={() => void loadPreview(output)} type="button">
                      <RefreshCw className="h-3.5 w-3.5" />
                      重试
                    </Button>
                  </div>
                ) : null}
                {previewState.status === 'ready' && previewState.kind === 'text' ? (
                  <div className="space-y-3">
                    <pre className="max-h-[420px] overflow-auto rounded-2xl border border-white/10 bg-[#05080b] px-4 py-4 text-xs leading-6 text-[#e8ded0]">
                      {previewState.content || '预览为空。'}
                    </pre>
                    {previewState.truncated ? (
                      <div className="flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-white/10 bg-black/20 px-3 py-3 text-xs text-muted">
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
                  <div className="overflow-hidden rounded-2xl border border-white/10 bg-white">
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
  )

  const eventStream = (
    <div className="space-y-3">
      {events.map((event) => (
        <div key={event.eventId} className="rounded-2xl border border-white/10 bg-black/20 px-4 py-4 transition hover:bg-white/5">
          <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
            <div>
              <div className="flex flex-wrap items-center gap-2">
                <div className="text-sm font-semibold text-ink">{event.title}</div>
                {event.status ? <StatusPill tone={toneForStatus(event.status)}>{event.status}</StatusPill> : null}
              </div>
              <div className="mt-1 text-sm leading-6 text-muted">{event.message || '—'}</div>
            </div>
            <div className="font-mono text-xs text-muted">{formatDate(event.timestamp)}</div>
          </div>
        </div>
      ))}
      {!events.length ? <div className="text-sm text-muted">当前还没有事件记录。</div> : null}
    </div>
  )

  return (
    <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_390px]">
      <div className="space-y-6">
        <PageCard>
          <div className="relative border-b border-white/10 px-6 py-7 sm:px-7">
            <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_80%_0%,rgba(215,176,110,0.16),transparent_25%),radial-gradient(circle_at_10%_100%,rgba(96,165,250,0.09),transparent_28%)]" />
            <div className="relative">
              <div className="flex flex-wrap items-center gap-3">
                <span className="rounded-full border border-primary/30 bg-primary/10 px-3 py-1 text-xs font-semibold uppercase tracking-[0.18em] text-primary">{viewLabel}</span>
                <StatusPill tone={toneForStatus(detail.status)}>{detail.statusLabel}</StatusPill>
                <StatusPill tone={isLiveRefreshing ? 'warning' : liveStatusTone}>{isLiveRefreshing ? '实时刷新中' : '已同步'}</StatusPill>
              </div>
              <h1 className="mt-5 text-3xl font-semibold tracking-[-0.04em] text-ink sm:text-4xl">{detail.title}</h1>
              <p className="mt-3 max-w-4xl text-sm leading-7 text-muted">{detail.question}</p>
              <div className="mt-6 rounded-[28px] border border-white/10 bg-black/25 p-5">
                <div className="flex items-center gap-2 text-sm font-semibold text-ink">
                  <Sparkles className="h-4 w-4 text-primary" />
                  结论摘要
                </div>
                <p className="mt-3 text-base leading-8 text-[#d8d1c6]">{detail.summary || '当前还没有可展示的结论摘要。'}</p>
                {detail.nextAction ? (
                  <div className="mt-5 rounded-2xl border border-primary/20 bg-primary/10 px-4 py-3 text-sm leading-6 text-[#f1dfbd]">
                    建议下一步：{detail.nextAction}
                  </div>
                ) : null}
              </div>
            </div>
          </div>

          <div className="grid gap-4 border-b border-white/10 px-6 py-5 md:grid-cols-4 sm:px-7">
            <MetricStrip label="当前阶段" value={detail.progress.currentStep} />
            <MetricStrip label="执行环节" value={String(detail.progress.executionCount)} />
            <MetricStrip label="结果产物" value={String(detail.outputs.length)} />
            <MetricStrip label="最后更新" value={formatDate(detail.updatedAt)} />
          </div>

          {viewMode === 'runtime' ? (
            <div className="grid gap-6 px-6 py-6 lg:grid-cols-[minmax(0,1fr)_390px] sm:px-7">
              <div className="space-y-5">
                <InnerPanel title="运行时透明度摘要" icon={<Activity className="h-4 w-4 text-sky-300" />}>
                  <div className="grid gap-3 md:grid-cols-2">
                    <KeyValue label="当前状态" value={detail.progress.statusLabel || detail.statusLabel} />
                    <KeyValue label="当前阶段" value={detail.progress.currentStep} />
                    <KeyValue label="执行环节" value={String(detail.progress.executionCount)} />
                    <KeyValue label="更新时间" value={formatDate(detail.progress.updatedAt || detail.updatedAt)} />
                  </div>
                  <p className="mt-4 rounded-2xl border border-white/10 bg-black/20 px-4 py-3 text-sm leading-6 text-muted">{detail.progress.activitySummary}</p>
                </InnerPanel>
                <InnerPanel title="事件流" icon={<Activity className="h-4 w-4 text-primary" />}>
                  {eventStream}
                </InnerPanel>
              </div>
              <div className="space-y-5">
                <InnerPanel title="产物与验证摘要" icon={<ShieldCheck className="h-4 w-4 text-emerald-300" />}>
                  <div className="grid gap-3">
                    <KeyValue label="证据索引" value={`${detail.evidence.length} 项`} />
                    <KeyValue label="结果产物" value={`${detail.outputs.length} 项`} />
                    <KeyValue label="风险提示" value={`${detail.warnings.length} 条`} />
                    <KeyValue label="调试可见" value={detail.isDebugAvailable ? '是' : '否'} />
                  </div>
                </InnerPanel>
                <InnerPanel title="结果产物" icon={<Download className="h-4 w-4 text-primary" />}>
                  {outputSection}
                </InnerPanel>
              </div>
            </div>
          ) : (
            <div className="grid gap-6 px-6 py-6 lg:grid-cols-[minmax(0,1fr)_390px] sm:px-7">
              <div className="space-y-5">
                <InnerPanel title="关键发现" icon={<Sparkles className="h-4 w-4 text-primary" />}>
                  <ul className="space-y-3 text-sm leading-6 text-muted">
                    {detail.keyFindings.map((item) => <li key={item} className="rounded-2xl border border-white/10 bg-black/20 px-4 py-3">{item}</li>)}
                    {!detail.keyFindings.length ? <li>暂无关键发现。</li> : null}
                  </ul>
                </InnerPanel>
                <InnerPanel title="证据索引" icon={<ShieldCheck className="h-4 w-4 text-emerald-300" />}>
                  <div className="flex flex-wrap gap-2">
                    {detail.evidence.map((item) => <span key={item.id} className="rounded-full border border-sky-400/20 bg-sky-500/10 px-3 py-1 text-xs text-sky-200">{item.label}</span>)}
                    {!detail.evidence.length ? <span className="text-sm text-muted">暂无证据索引。</span> : null}
                  </div>
                </InnerPanel>
                <InnerPanel title="结果产物" icon={<Download className="h-4 w-4 text-primary" />}>
                  {outputSection}
                </InnerPanel>
              </div>
              <div className="space-y-5">
                <InnerPanel title="进度概览" icon={<Activity className="h-4 w-4 text-primary" />}>
                  <div className="space-y-3">
                    <KeyValue label="当前阶段" value={detail.progress.currentStep} />
                    <KeyValue label="执行环节" value={String(detail.progress.executionCount)} />
                    <KeyValue label="最后更新时间" value={formatDate(detail.updatedAt)} />
                  </div>
                  <p className="mt-4 rounded-2xl border border-white/10 bg-black/20 px-4 py-3 text-sm leading-6 text-muted">{detail.progress.activitySummary}</p>
                </InnerPanel>
                <InnerPanel title="风险与注意事项" icon={<AlertTriangle className="h-4 w-4 text-amber-300" />}>
                  <ul className="space-y-2 text-sm leading-6 text-muted">
                    {detail.warnings.map((warning) => <li key={warning} className="rounded-2xl border border-amber-400/20 bg-amber-500/10 px-4 py-3 text-amber-100">{warning}</li>)}
                    {!detail.warnings.length ? <li>当前没有额外风险提示。</li> : null}
                  </ul>
                </InnerPanel>
              </div>
            </div>
          )}
        </PageCard>

        {viewMode === 'business' ? (
          <PageCard>
            <SectionHeader title="进度事件" description="按时间顺序查看分析任务最近经历的关键步骤。" />
            <div className="px-6 py-5 sm:px-7">{eventStream}</div>
          </PageCard>
        ) : null}
      </div>

      <aside className="space-y-6">
        <RailCard title={viewMode === 'runtime' ? '治理与执行' : '最终结论'}>
          <div className="flex items-start gap-4">
            <div className="flex h-14 w-14 items-center justify-center rounded-2xl border border-primary/25 bg-primary/10 text-primary">
              <ShieldCheck className="h-7 w-7" />
            </div>
            <div>
              <div className="text-xs uppercase tracking-[0.16em] text-muted">Terminal Status</div>
              <div className="mt-2 text-2xl font-semibold text-ink">{detail.statusLabel}</div>
            </div>
          </div>
          <div className="mt-6 space-y-3">
            <KeyValue label="置信/状态" value={detail.status} />
            <KeyValue label="产物数量" value={`${detail.outputs.length} 项`} />
            <KeyValue label="证据数量" value={`${detail.evidence.length} 项`} />
            <KeyValue label="完成时间" value={formatDate(detail.updatedAt)} />
          </div>
        </RailCard>

        <RailCard title="运行时透明度">
          <div className="space-y-3">
            <KeyValue label="刷新状态" value={isLiveRefreshing ? '实时刷新中' : isTerminalAnalysisStatus(detail.status) ? '终态停止刷新' : '状态已同步'} />
            <KeyValue label="当前阶段" value={detail.progress.currentStep} />
            <KeyValue label="事件数量" value={`${events.length} 条`} />
            <KeyValue label="调试入口" value={detail.isDebugAvailable ? '可见' : '不可见'} />
          </div>
        </RailCard>

        <RailCard title="建议下一步">
          <p className="text-sm leading-7 text-muted">{detail.nextAction || '当前没有额外建议。'}</p>
          {detail.warnings.length ? (
            <div className="mt-4 rounded-2xl border border-amber-400/20 bg-amber-500/10 px-4 py-3 text-sm leading-6 text-amber-100">
              仍有 {detail.warnings.length} 条风险提示，需要复核。
            </div>
          ) : (
            <div className="mt-4 rounded-2xl border border-emerald-400/20 bg-emerald-500/10 px-4 py-3 text-sm leading-6 text-emerald-200">
              当前没有额外风险提示。
            </div>
          )}
          <a className="mt-4 inline-flex min-h-11 items-center gap-2 rounded-full border border-white/10 px-4 text-sm font-semibold text-primary transition hover:border-primary/25 hover:bg-primary/10 hover:text-primary-hover" href="#top">
            回到摘要
            <ArrowRight className="h-4 w-4" />
          </a>
        </RailCard>
      </aside>
    </div>
  )
}

function InnerPanel({ title, icon, children }: { title: string; icon?: ReactNode; children: ReactNode }) {
  return (
    <div className="rounded-[28px] border border-white/10 bg-white/5 p-5 shadow-subtle">
      <div className="mb-4 flex items-center gap-2 text-sm font-semibold text-ink">
        {icon}
        {title}
      </div>
      {children}
    </div>
  )
}

function RailCard({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="rounded-[30px] border border-white/10 bg-surface p-5 shadow-panel backdrop-blur-xl">
      <div className="mb-5 text-lg font-semibold text-ink">{title}</div>
      {children}
    </div>
  )
}

function KeyValue({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-start justify-between gap-4 rounded-2xl border border-white/10 bg-black/20 px-4 py-3 text-sm">
      <span className="text-muted">{label}</span>
      <span className="text-right font-medium text-ink">{value || '—'}</span>
    </div>
  )
}

function MetricStrip({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-2xl border border-white/10 bg-white/5 px-4 py-4">
      <div className="text-xs font-semibold uppercase tracking-[0.14em] text-muted">{label}</div>
      <div className="mt-2 text-sm font-semibold text-ink">{value || '—'}</div>
    </div>
  )
}

function toneForStatus(status: string): 'neutral' | 'success' | 'warning' | 'error' {
  if (status === 'success') return 'success'
  if (status === 'failed') return 'error'
  if (status === 'waiting_for_human') return 'warning'
  return 'neutral'
}
