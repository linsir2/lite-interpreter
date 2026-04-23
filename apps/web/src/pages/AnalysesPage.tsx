import { Link } from 'react-router-dom'

import { Button, PageCard, SectionHeader, StatusPill } from '@/components/ui'
import type { AnalysisListResponse } from '@/lib/types'
import { formatDate } from '@/lib/utils'

export function AnalysesPage({ data }: { data: AnalysisListResponse | undefined }) {
  const items = data?.items ?? []
  const activeItems = items.filter((item) => item.status !== 'success')

  return (
    <div className="space-y-6">
      <PageCard>
        <SectionHeader
          title="分析总览"
          description="快速查看最近分析、处理状态和需要继续跟进的任务。"
          action={<Link to="/analyses/new"><Button>新建分析</Button></Link>}
        />
        <div className="grid gap-4 px-6 py-6 md:grid-cols-3">
          <MetricCard label="分析任务数" value={String(data?.pagination.totalItems ?? 0)} />
          <MetricCard label="当前工作区" value={data?.currentWorkspaceId ?? '—'} />
          <MetricCard label="已完成" value={String(items.filter((item) => item.status === 'success').length)} />
        </div>
        <div className="grid gap-4 border-t border-border px-6 py-6 xl:grid-cols-[1.1fr_0.9fr]">
          <div className="rounded-[30px] border border-border bg-gradient-to-br from-[#123a34] via-[#153e38] to-[#0d2d28] px-6 py-6 text-white shadow-panel">
            <div className="text-xs font-semibold uppercase tracking-[0.16em] text-[#dec390]">本周重点</div>
            <h3 className="mt-3 text-[1.9rem] font-semibold leading-tight">先处理未完成和需要复核的分析</h3>
            <p className="mt-3 max-w-2xl text-sm leading-7 text-white/72">
              分析总览优先展示待处理任务和最近结果。建议先确认结论是否可复核，再下载结果产物或继续追踪异常项。
            </p>
          </div>
          <div className="rounded-[30px] border border-border bg-white px-5 py-5">
            <div className="text-sm font-semibold text-ink">需要继续跟进</div>
            <div className="mt-4 space-y-3">
              {activeItems.slice(0, 3).map((item) => (
                <Link key={item.analysisId} to={`/analyses/${item.analysisId}`} className="block rounded-2xl border border-border bg-surface-2 px-4 py-3 transition hover:border-primary/20 hover:bg-white">
                  <div className="flex items-center justify-between gap-3">
                    <div className="font-medium text-ink">{item.title}</div>
                    <StatusPill tone={toneForStatus(item.status)}>{item.statusLabel}</StatusPill>
                  </div>
                  <div className="mt-2 text-xs leading-5 text-muted">{item.summary || item.question}</div>
                </Link>
              ))}
              {!activeItems.length ? <div className="text-sm text-muted">当前没有需要继续跟进的任务。</div> : null}
            </div>
          </div>
        </div>
      </PageCard>

      <PageCard>
        <SectionHeader title="最近分析" description="按最近更新时间排序，继续查看或复核已有分析。" />
        <div className="overflow-x-auto px-4 pb-4">
          <table className="min-w-full border-separate border-spacing-y-2 text-sm">
            <thead>
              <tr className="text-left text-xs uppercase tracking-[0.14em] text-muted">
                <th className="px-3 py-2">分析主题</th>
                <th className="px-3 py-2">状态</th>
                <th className="px-3 py-2">更新时间</th>
                <th className="px-3 py-2">结果</th>
              </tr>
            </thead>
            <tbody>
              {data?.items.map((item) => (
                <tr key={item.analysisId} className="rounded-2xl bg-surface-2 text-ink shadow-[inset_0_0_0_1px_rgba(13,92,77,0.05)] transition hover:bg-white">
                  <td className="rounded-l-2xl px-3 py-4 align-top">
                    <Link className="font-semibold hover:text-primary" to={`/analyses/${item.analysisId}`}>
                      {item.title}
                    </Link>
                    <div className="mt-1 max-w-xl text-xs leading-5 text-muted">{item.question}</div>
                  </td>
                  <td className="px-3 py-4 align-top"><StatusPill tone={toneForStatus(item.status)}>{item.statusLabel}</StatusPill></td>
                  <td className="px-3 py-4 align-top font-mono text-xs text-muted">{formatDate(item.updatedAt)}</td>
                  <td className="rounded-r-2xl px-3 py-4 align-top text-muted">{item.summary || '等待结果'}</td>
                </tr>
              ))}
              {!data?.items.length ? (
                <tr>
                  <td className="px-3 py-10 text-center text-muted" colSpan={4}>当前工作区还没有分析任务。</td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>
      </PageCard>
    </div>
  )
}

function MetricCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-[26px] border border-border bg-surface-2 px-5 py-5">
      <div className="text-xs uppercase tracking-[0.16em] text-muted">{label}</div>
      <div className="mt-3 font-mono text-[1.8rem] font-semibold text-ink">{value}</div>
    </div>
  )
}

function toneForStatus(status: string) {
  if (status === 'success') return 'success'
  if (status === 'failed') return 'error'
  if (status === 'waiting_for_human') return 'warning'
  return 'neutral'
}
