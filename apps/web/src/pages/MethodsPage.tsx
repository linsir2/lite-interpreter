import { PageCard, SectionHeader } from '@/components/ui'
import type { MethodCard } from '@/lib/types'

export function MethodsPage({ methods }: { methods: MethodCard[] }) {
  return (
    <PageCard>
      <SectionHeader title="分析方法库" description="查看当前工作区可复用的分析方法、所需能力和使用情况。" />
      <div className="grid gap-4 border-b border-border px-6 py-5 md:grid-cols-3">
        <MethodMetric label="方法总数" value={String(methods.length)} />
        <MethodMetric label="高频方法" value={String(methods.filter((method) => method.usageCount > 0).length)} />
        <MethodMetric label="已沉淀" value={String(methods.filter((method) => method.promotionStatus === 'approved').length)} />
      </div>
      <div className="grid gap-4 px-6 py-6 lg:grid-cols-2 xl:grid-cols-3">
        {methods.map((method) => (
          <article key={method.methodId} className="rounded-[28px] border border-border bg-surface-2 p-5 transition hover:-translate-y-[1px] hover:bg-white">
            <div className="text-xs uppercase tracking-[0.16em] text-accent">{method.promotionStatus}</div>
            <h3 className="mt-3 text-lg font-semibold text-ink">{method.name}</h3>
            <p className="mt-2 text-sm leading-6 text-muted">{method.description}</p>
            <div className="mt-4 flex flex-wrap gap-2">
              {method.requiredCapabilities.map((capability) => (
                <span key={capability} className="rounded-full border border-border bg-white px-3 py-1 text-xs text-muted">{capability}</span>
              ))}
            </div>
            <div className="mt-5 font-mono text-sm text-muted">使用次数：{method.usageCount}</div>
          </article>
        ))}
        {!methods.length ? <div className="text-sm text-muted">当前工作区还没有沉淀好的分析方法。</div> : null}
      </div>
    </PageCard>
  )
}

function MethodMetric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-[24px] border border-border bg-surface-2 px-4 py-4">
      <div className="text-xs font-semibold uppercase tracking-[0.14em] text-muted">{label}</div>
      <div className="mt-2 font-mono text-[1.65rem] font-semibold text-ink">{value}</div>
    </div>
  )
}
