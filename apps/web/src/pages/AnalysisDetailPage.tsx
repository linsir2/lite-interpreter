import { ExternalLink } from 'lucide-react'

import { PageCard, SectionHeader, StatusPill } from '@/components/ui'
import type { AnalysisDetail, AnalysisEvent } from '@/lib/types'
import { formatDate } from '@/lib/utils'

export function AnalysisDetailPage({ detail, events }: { detail: AnalysisDetail | undefined; events: AnalysisEvent[] }) {
  if (!detail) {
    return <div className="rounded-3xl border border-border bg-surface px-6 py-10 text-sm text-muted">正在加载分析详情…</div>
  }

  return (
    <div className="space-y-6">
      <PageCard>
        <SectionHeader title={detail.title} description={detail.question} action={<StatusPill tone={detail.status === 'success' ? 'success' : detail.status === 'failed' ? 'error' : 'neutral'}>{detail.statusLabel}</StatusPill>} />
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
                {detail.outputs.map((output) => (
                  <div key={output.id} className="rounded-2xl border border-border bg-white px-4 py-3">
                    <div className="flex items-start justify-between gap-3">
                      <div>
                        <div className="font-medium text-ink">{output.title}</div>
                        <div className="mt-1 text-xs text-muted">{output.type} · {output.summary || '无摘要'}</div>
                      </div>
                      {output.downloadUrl ? (
                        <a className="inline-flex items-center gap-1 text-sm font-medium text-primary hover:text-primary-hover" href={output.downloadUrl} target="_blank" rel="noreferrer">
                          下载
                          <ExternalLink className="h-3.5 w-3.5" />
                        </a>
                      ) : null}
                    </div>
                  </div>
                ))}
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
