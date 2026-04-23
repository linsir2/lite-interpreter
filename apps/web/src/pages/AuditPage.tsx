import { PageCard, SectionHeader } from '@/components/ui'
import type { AuditListItem } from '@/lib/types'
import { formatDate } from '@/lib/utils'

export function AuditPage({ items }: { items: AuditListItem[] }) {
  return (
    <PageCard>
      <SectionHeader title="审计记录" description="按时间顺序查看当前工作区的重要操作和结果。" />
      <div className="grid gap-4 border-b border-border px-6 py-5 md:grid-cols-3">
        <AuditMetric label="记录总数" value={String(items.length)} />
        <AuditMetric label="成功" value={String(items.filter((item) => item.outcome === 'success').length)} />
        <AuditMetric label="失败/拒绝" value={String(items.filter((item) => item.outcome !== 'success').length)} />
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
              <tr key={item.auditId} className="bg-surface-2 transition hover:bg-white">
                <td className="rounded-l-2xl px-3 py-4 text-ink">{item.action}</td>
                <td className="px-3 py-4 text-muted">{item.outcome}</td>
                <td className="px-3 py-4 text-muted">{item.subject} · {item.role}</td>
                <td className="rounded-r-2xl px-3 py-4 font-mono text-xs text-muted">{formatDate(item.recordedAt)}</td>
              </tr>
            ))}
            {!items.length ? <tr><td className="px-3 py-10 text-center text-muted" colSpan={4}>当前没有审计记录。</td></tr> : null}
          </tbody>
        </table>
      </div>
    </PageCard>
  )
}

function AuditMetric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-[24px] border border-border bg-surface-2 px-4 py-4">
      <div className="text-xs font-semibold uppercase tracking-[0.14em] text-muted">{label}</div>
      <div className="mt-2 font-mono text-[1.65rem] font-semibold text-ink">{value}</div>
    </div>
  )
}
