import { FeedbackState, PageCard, QueryFeedback, SectionHeader, StatusPill } from '@/components/ui'
import type { MethodCard } from '@/lib/types'

export function MethodsPage({
  methods,
  isLoading = false,
  errorMessage,
  onRetry,
}: {
  methods: MethodCard[]
  isLoading?: boolean
  errorMessage?: string | null
  onRetry?: () => void
}) {
  return (
    <PageCard>
      <SectionHeader title="分析方法库" level="h1" description="查看当前工作区可复用的分析方法、所需能力和使用情况。" />
      <div className="grid gap-4 border-b border-white/10 px-6 py-5 md:grid-cols-3 sm:px-7">
        <MethodMetric label="方法总数" value={String(methods.length)} />
        <MethodMetric label="高频方法" value={String(methods.filter((method) => method.usageCount > 0).length)} />
        <MethodMetric label="已沉淀" value={String(methods.filter((method) => method.promotionStatus === 'approved').length)} />
      </div>
      {errorMessage || (isLoading && !methods.length) ? (
        <div className="border-b border-white/10 px-6 py-5 sm:px-7">
          <QueryFeedback
            errorMessage={errorMessage}
            loading={isLoading && !methods.length}
            loadingTitle="正在加载方法库"
            loadingDescription="正在读取当前工作区可复用的分析方法和能力要求。"
            errorTitle="方法库加载失败"
            onRetry={onRetry}
            retryLabel="重新加载方法库"
          />
        </div>
      ) : null}
      <div className="grid gap-4 px-6 py-6 lg:grid-cols-2 xl:grid-cols-3 sm:px-7">
        {methods.map((method) => (
          <article key={method.methodId} className="rounded-[28px] border border-white/10 bg-white/5 p-5 transition hover:-translate-y-[1px] hover:bg-white/10">
            <StatusPill tone={method.promotionStatus === 'approved' ? 'success' : method.promotionStatus ? 'warning' : 'neutral'}>{method.promotionStatus || 'draft'}</StatusPill>
            <h3 className="mt-4 text-lg font-semibold text-ink">{method.name}</h3>
            <p className="mt-2 text-sm leading-6 text-muted">{method.description}</p>
            <div className="mt-4 flex flex-wrap gap-2">
              {method.requiredCapabilities.map((capability) => (
                <span key={capability} className="rounded-full border border-white/10 bg-black/20 px-3 py-1 text-xs text-muted">{capability}</span>
              ))}
            </div>
            <div className="mt-5 font-mono text-sm text-muted">使用次数：{method.usageCount}</div>
          </article>
        ))}
        {!methods.length ? (
          <div className="lg:col-span-2 xl:col-span-3">
            <FeedbackState
              title="还没有沉淀好的分析方法"
              description="当工作区开始产生可复用的分析流程后，这里会展示方法名称、所需能力和使用次数。"
            />
          </div>
        ) : null}
      </div>
    </PageCard>
  )
}

function MethodMetric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-[24px] border border-white/10 bg-white/5 px-4 py-4">
      <div className="text-xs font-semibold uppercase tracking-[0.14em] text-muted">{label}</div>
      <div className="mt-2 font-mono text-[1.65rem] font-semibold text-ink">{value}</div>
    </div>
  )
}
