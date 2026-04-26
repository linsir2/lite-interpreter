import { FeedbackState, PageCard, QueryFeedback, SectionHeader, StatusPill, focusRing } from '@/components/ui'
import type { AuditListResponse } from '@/lib/types'
import { cn, formatDate } from '@/lib/utils'

export function AuditPage({
  data,
  page,
  isLoading = false,
  errorMessage,
  onRetry,
  onPageChange,
}: {
  data: AuditListResponse | undefined
  page: number
  isLoading?: boolean
  errorMessage?: string | null
  onRetry?: () => void
  onPageChange: (page: number) => void
}) {
  const items = data?.items ?? []
  const pagination = data?.pagination
  const totalItems = pagination?.totalItems ?? 0
  const totalPages = pagination?.totalPages ?? 1

  return (
    <PageCard>
      <SectionHeader title="治理与审计" level="h1" description="按时间顺序查看当前工作区的重要操作、执行人和结果。" />
      <div className="grid gap-4 border-b border-white/10 px-6 py-5 md:grid-cols-3 sm:px-7">
        <AuditMetric label="记录总数" value={String(totalItems)} />
        <AuditMetric label="当前页成功" value={String(items.filter((item) => item.outcome === 'success').length)} tone="success" />
        <AuditMetric label="当前页失败/拒绝" value={String(items.filter((item) => item.outcome !== 'success').length)} tone="warning" />
      </div>
      {errorMessage || (isLoading && !data) ? (
        <div className="border-b border-white/10 px-6 py-5 sm:px-7">
          <QueryFeedback
            errorMessage={errorMessage}
            loading={isLoading && !data}
            loadingTitle="正在加载审计记录"
            loadingDescription="正在读取当前工作区的关键操作、执行人和结果。"
            errorTitle="审计记录加载失败"
            onRetry={onRetry}
            retryLabel="重新加载审计记录"
          />
        </div>
      ) : null}
      <div className="flex items-center justify-between border-b border-white/10 px-6 py-4 text-sm text-muted sm:px-7">
        <span>第 {page} / {totalPages} 页</span>
        <div className="flex gap-2">
          <button
            className={cn('inline-flex min-h-11 cursor-pointer items-center justify-center rounded-full border border-white/10 px-4 py-2 transition hover:bg-white/5 disabled:cursor-not-allowed disabled:opacity-50', focusRing)}
            disabled={page <= 1}
            type="button"
            onClick={() => onPageChange(page - 1)}
          >
            上一页
          </button>
          <button
            className={cn('inline-flex min-h-11 cursor-pointer items-center justify-center rounded-full border border-white/10 px-4 py-2 transition hover:bg-white/5 disabled:cursor-not-allowed disabled:opacity-50', focusRing)}
            disabled={page >= totalPages}
            type="button"
            onClick={() => onPageChange(page + 1)}
          >
            下一页
          </button>
        </div>
      </div>
      <div className="overflow-x-auto px-4 pb-4">
        <table className="min-w-full border-separate border-spacing-y-2 text-sm">
          <thead>
            <tr className="text-left text-xs uppercase tracking-[0.14em] text-muted">
              <th className="px-3 py-2">动作</th>
              <th className="px-3 py-2">结果</th>
              <th className="px-3 py-2">执行人</th>
              <th className="px-3 py-2">时间</th>
            </tr>
          </thead>
          <tbody>
            {items.map((item) => (
              <tr key={item.auditId} className="bg-white/5 transition hover:bg-white/10">
                <td className="rounded-l-2xl px-3 py-4 text-ink">{item.action}</td>
                <td className="px-3 py-4"><StatusPill tone={item.outcome === 'success' ? 'success' : 'warning'}>{item.outcome}</StatusPill></td>
                <td className="px-3 py-4 text-muted">{item.subject} · {item.role}</td>
                <td className="rounded-r-2xl px-3 py-4 font-mono text-xs text-muted">{formatDate(item.recordedAt)}</td>
              </tr>
            ))}
            {!items.length ? (
              <tr>
                <td className="px-3 py-6" colSpan={4}>
                  <FeedbackState
                    title="当前没有审计记录"
                    description="当工作区发生登录、资料上传、分析创建或产物读取等关键动作后，这里会显示可追溯记录。"
                  />
                </td>
              </tr>
            ) : null}
          </tbody>
        </table>
      </div>
    </PageCard>
  )
}

function AuditMetric({ label, value, tone = 'neutral' }: { label: string; value: string; tone?: 'neutral' | 'success' | 'warning' }) {
  const borderClass = tone === 'success' ? 'border-emerald-400/20' : tone === 'warning' ? 'border-amber-400/20' : 'border-white/10'
  return (
    <div className={`rounded-[24px] border ${borderClass} bg-white/5 px-4 py-4`}>
      <div className="text-xs font-semibold uppercase tracking-[0.14em] text-muted">{label}</div>
      <div className="mt-2 font-mono text-[1.65rem] font-semibold text-ink">{value}</div>
    </div>
  )
}
