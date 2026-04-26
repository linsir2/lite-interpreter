import { ArrowRight, Play, ShieldCheck, Sparkles } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'

import { Button, PageCard, QueryFeedback, Select, StatusPill, TextArea, focusRing } from '@/components/ui'
import type { AnalysisListResponse, AssetListItem, CreateAnalysisResponse } from '@/lib/types'
import { cn, formatDate } from '@/lib/utils'

type ViewMode = 'business' | 'runtime'

const RECENT_ANALYSIS_DISPLAY_LIMIT = 10

export function AnalysesPage({
  data,
  assets,
  isLoading = false,
  errorMessage,
  onRetry,
  viewMode,
  onSubmit,
}: {
  data: AnalysisListResponse | undefined
  assets: AssetListItem[]
  isLoading?: boolean
  errorMessage?: string | null
  onRetry?: () => void
  viewMode: ViewMode
  onSubmit: (input: { question: string; assetIds: string[]; analysisModePreset?: string | null }) => Promise<CreateAnalysisResponse>
}) {
  const navigate = useNavigate()
  const items = data?.items ?? []
  const latestItem = items[0]
  const visibleRecentItems = items.slice(0, RECENT_ANALYSIS_DISPLAY_LIMIT)
  const hiddenRecentItemCount = Math.max(items.length - visibleRecentItems.length, 0)
  const activeItems = items.filter((item) => item.status !== 'success')
  const completedCount = items.filter((item) => item.status === 'success').length
  const warningCount = items.filter((item) => item.hasWarnings).length
  const assetSignature = useMemo(() => assets.map((asset) => asset.assetId).join('|'), [assets])

  const [question, setQuestion] = useState('')
  const [analysisModePreset, setAnalysisModePreset] = useState('researcher')
  const [assetIds, setAssetIds] = useState<string[]>([])
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    setAssetIds(assetSignature ? assetSignature.split('|').slice(0, 3) : [])
  }, [assetSignature])

  const selectedAssets = assets.filter((asset) => assetIds.includes(asset.assetId))
  const visibleAssetOptions = assets.slice(0, 6)
  const reviewQueue = items.filter((item) => item.hasWarnings || item.status !== 'success').slice(0, 4)
  const heroTitle = viewMode === 'runtime' ? '运行时透明度中心' : '可复核的 AI 财务分析'
  const heroDescription = viewMode === 'runtime'
    ? '从业务任务进入真实运行事件、进度与产物状态，不在首页伪造完整 DAG。'
    : '上传资料、生成证据、沉淀产物，再把结论交给业务复核。'

  return (
    <div className="space-y-6">
      {errorMessage || (isLoading && !data) ? (
        <PageCard className="p-5">
          <QueryFeedback
            errorMessage={errorMessage}
            loading={isLoading && !data}
            loadingTitle="正在加载工作台"
            loadingDescription="正在读取当前工作区的分析任务、状态和复核队列。"
            errorTitle="分析列表加载失败"
            onRetry={onRetry}
          />
        </PageCard>
      ) : null}
      <PageCard className="overflow-hidden">
        <div className="grid gap-0 xl:grid-cols-[minmax(0,1.15fr)_minmax(340px,0.85fr)]">
          <div className="relative px-6 py-7 sm:px-8 sm:py-8">
            <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_78%_10%,rgba(215,176,110,0.16),transparent_26%),radial-gradient(circle_at_10%_90%,rgba(74,222,128,0.08),transparent_28%)]" />
            <div className="relative">
              <div className="flex flex-wrap items-center gap-3">
                <span className="rounded-full border border-primary/30 bg-primary/10 px-3 py-1 text-xs font-semibold uppercase tracking-[0.18em] text-primary">
                  {viewMode === 'runtime' ? 'Runtime View' : 'Business View'}
                </span>
                <StatusPill tone="success">受控执行</StatusPill>
              </div>
              <h1 className="mt-5 max-w-4xl text-4xl font-semibold tracking-[-0.04em] text-ink sm:text-5xl">
                {heroTitle}
              </h1>
              <p className="mt-4 max-w-3xl text-base leading-8 text-muted">{heroDescription}</p>

              <div className="mt-7 grid gap-3 md:grid-cols-3">
                <MiniStat label="任务总数" value={String(data?.pagination.totalItems ?? 0)} />
                <MiniStat label="待跟进" value={String(activeItems.length)} />
                <MiniStat label="风险提示" value={String(warningCount)} />
              </div>

              <form
                className="mt-7 rounded-[28px] border border-white/10 bg-black/25 p-4 shadow-subtle sm:p-5"
                onSubmit={async (event) => {
                  event.preventDefault()
                  setSubmitting(true)
                  setError(null)
                  try {
                    const result = await onSubmit({ question, assetIds, analysisModePreset })
                    navigate(`/analyses/${result.analysisId}`)
                  } catch (submitError) {
                    setError(submitError instanceof Error ? submitError.message : '提交失败')
                  } finally {
                    setSubmitting(false)
                  }
                }}
              >
                <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_260px]">
                  <div>
                    <div className="mb-2 text-xs font-semibold uppercase tracking-[0.16em] text-[#b7b0a2]">提出您的分析问题</div>
                    <TextArea
                      className="min-h-28 resize-none"
                      placeholder="例如：分析本期毛利率下降的主要原因，并给出下一季度趋势建议。"
                      value={question}
                      onChange={(event) => setQuestion(event.target.value)}
                      required
                    />
                  </div>
                  <div className="space-y-4">
                    <div>
                      <label className="mb-2 block text-xs font-semibold uppercase tracking-[0.16em] text-[#b7b0a2]" htmlFor="quick-analysis-mode">分析模式</label>
                      <Select id="quick-analysis-mode" value={analysisModePreset} onChange={(event) => setAnalysisModePreset(event.target.value)}>
                        <option value="researcher">深度分析（推荐）</option>
                        <option value="reviewer">规则审计</option>
                        <option value="planner">结构化拆解</option>
                      </Select>
                    </div>
                    <Button className="w-full justify-center" disabled={submitting || !question.trim()} type="submit">
                      <Play className="h-4 w-4" />
                      {submitting ? '创建中…' : '开始分析'}
                    </Button>
                    {error ? <div className="rounded-2xl border border-rose-400/20 bg-rose-500/10 px-3 py-2 text-sm text-rose-200" role="alert">{error}</div> : null}
                  </div>
                </div>

                <div className="mt-4 border-t border-white/10 pt-4">
                  <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
                    <span className="text-xs font-semibold uppercase tracking-[0.16em] text-[#b7b0a2]">本次引用资料</span>
                    <span className="text-xs text-muted">已选 {selectedAssets.length} 项</span>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    {visibleAssetOptions.map((asset) => {
                      const selected = assetIds.includes(asset.assetId)
                      return (
                        <button
                          key={asset.assetId}
                          className={cn(
                            'cursor-pointer rounded-full border px-3 py-2 text-xs transition',
                            focusRing,
                            selected
                              ? 'border-primary/30 bg-primary/10 text-primary'
                              : 'border-white/10 bg-white/5 text-muted hover:border-white/20 hover:text-ink',
                          )}
                          type="button"
                          onClick={() => {
                            setAssetIds((current) =>
                              current.includes(asset.assetId)
                                ? current.filter((item) => item !== asset.assetId)
                                : [...current, asset.assetId],
                            )
                          }}
                        >
                          {asset.name}
                        </button>
                      )
                    })}
                    {!assets.length ? <span className="text-sm text-muted">当前工作区暂无资料，可先到资料库上传。</span> : null}
                  </div>
                </div>
              </form>
            </div>
          </div>

          <aside className="border-t border-white/10 bg-black/20 px-6 py-7 xl:border-l xl:border-t-0">
            <div className="space-y-4">
              <div className="rounded-[28px] border border-white/10 bg-white/5 p-5">
                <div className="flex items-center justify-between gap-3">
                  <div className="text-sm font-semibold text-ink">复核队列</div>
                  <ShieldCheck className="h-5 w-5 text-emerald-300" />
                </div>
                <div className="mt-4 space-y-3">
                  {reviewQueue.map((item) => (
                    <Link
                      key={item.analysisId}
                      className={cn('block rounded-2xl border border-white/10 bg-black/20 px-4 py-3 transition hover:border-primary/25 hover:bg-white/5', focusRing)}
                      to={`/analyses/${item.analysisId}`}
                    >
                      <div className="flex items-start justify-between gap-3">
                        <div className="min-w-0 font-medium text-ink">{item.title}</div>
                        <StatusPill tone={toneForStatus(item.status)}>{item.statusLabel}</StatusPill>
                      </div>
                      <div className="mt-2 text-xs leading-5 text-muted">{item.hasWarnings ? '含风险提示，需要复核。' : item.summary || item.question}</div>
                    </Link>
                  ))}
                  {!reviewQueue.length ? <div className="rounded-2xl border border-emerald-400/20 bg-emerald-500/10 px-4 py-3 text-sm leading-6 text-emerald-200">当前没有待复核风险或未完成任务。</div> : null}
                </div>
              </div>

              <div className="rounded-[28px] border border-white/10 bg-white/5 p-5">
                <div className="text-sm font-semibold text-ink">最新运行</div>
                {latestItem ? (
                  <div className="mt-4 space-y-4">
                    <div className="flex items-start justify-between gap-3">
                      <div>
                        <div className="font-semibold text-ink">{latestItem.title}</div>
                        <div className="mt-1 font-mono text-xs text-muted">{formatDate(latestItem.updatedAt)}</div>
                      </div>
                      <StatusPill tone={toneForStatus(latestItem.status)}>{latestItem.statusLabel}</StatusPill>
                    </div>
                    <p className="text-sm leading-6 text-muted">{latestItem.summary || latestItem.question}</p>
                    <Link className={cn('inline-flex min-h-11 items-center gap-2 rounded-full text-sm font-semibold text-primary hover:text-primary-hover', focusRing)} to={`/analyses/${latestItem.analysisId}`}>
                      查看完整结论
                      <ArrowRight className="h-4 w-4" />
                    </Link>
                  </div>
                ) : (
                  <div className="mt-4 text-sm leading-6 text-muted">还没有分析任务。提交第一个问题后，这里会显示最近运行。</div>
                )}
              </div>
            </div>
          </aside>
        </div>
      </PageCard>

      <div className="grid gap-4 md:grid-cols-4">
        <MetricCard label="当前工作区" value={data?.currentWorkspaceId ?? '—'} caption="来自 app-facing API" />
        <MetricCard label="任务总数" value={String(data?.pagination.totalItems ?? 0)} caption="真实分页总数" />
        <MetricCard label="已完成" value={String(completedCount)} caption="状态为 success" />
        <MetricCard label="待跟进" value={String(activeItems.length)} caption="含进行中/失败/需人工" tone={activeItems.length ? 'warning' : 'success'} />
      </div>

      <div className="grid gap-6 xl:grid-cols-[minmax(0,1.1fr)_420px]">
        <PageCard>
          <div className="border-b border-white/10 px-6 py-5 sm:px-7">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <div className="text-sm font-semibold text-ink">最近分析</div>
                <p className="mt-1 text-sm text-muted">按最近更新时间排序，首页仅展示最需要快速复核的最近记录。</p>
              </div>
              <Link className={cn('inline-flex min-h-11 items-center justify-center rounded-full border border-white/10 bg-white/5 px-4 text-sm font-semibold text-ink transition hover:-translate-y-[1px] hover:border-white/20 hover:bg-white/10', focusRing)} to="/analyses/new">进入完整新建流程</Link>
            </div>
          </div>
          <div className="overflow-x-auto px-4 pb-4">
            <table className="min-w-full border-separate border-spacing-y-2 text-sm">
              <thead>
                <tr className="text-left text-xs uppercase tracking-[0.14em] text-muted">
                  <th className="px-3 py-2">分析主题</th>
                  <th className="px-3 py-2">状态</th>
                  <th className="px-3 py-2">更新时间</th>
                  <th className="px-3 py-2">结果摘要</th>
                </tr>
              </thead>
              <tbody>
                {visibleRecentItems.map((item) => (
                  <tr key={item.analysisId} className="rounded-2xl bg-white/5 text-ink shadow-[inset_0_0_0_1px_rgba(255,255,255,0.05)] transition hover:bg-white/10">
                    <td className="rounded-l-2xl px-3 py-4 align-top">
                      <Link className={cn('inline-flex min-h-11 items-center rounded-lg font-semibold hover:text-primary', focusRing)} to={`/analyses/${item.analysisId}`}>
                        {item.title}
                      </Link>
                      <div className="mt-1 max-w-xl text-xs leading-5 text-muted">{item.question}</div>
                    </td>
                    <td className="px-3 py-4 align-top"><StatusPill tone={toneForStatus(item.status)}>{item.statusLabel}</StatusPill></td>
                    <td className="px-3 py-4 align-top font-mono text-xs text-muted">{formatDate(item.updatedAt)}</td>
                    <td className="rounded-r-2xl px-3 py-4 align-top text-muted">{item.summary || '等待结果'}</td>
                  </tr>
                ))}
                {!items.length ? (
                  <tr>
                    <td className="px-3 py-10 text-center text-muted" colSpan={4}>当前工作区还没有分析任务。</td>
                  </tr>
                ) : null}
              </tbody>
            </table>
            {hiddenRecentItemCount ? (
              <div className="border-t border-white/10 px-3 py-4 text-sm text-muted">
                已收起 {hiddenRecentItemCount} 条更早记录；全量历史应通过真实分页能力查看。
              </div>
            ) : null}
          </div>
        </PageCard>

        <PageCard>
          <div className="border-b border-white/10 px-6 py-5">
            <div className="flex items-center gap-2 text-sm font-semibold text-ink">
              <Sparkles className="h-4 w-4 text-primary" />
              需要继续跟进
            </div>
            <p className="mt-1 text-sm text-muted">优先处理非成功终态或带风险提示的任务。</p>
          </div>
          <div className="space-y-3 px-5 py-5">
            {activeItems.slice(0, 5).map((item) => (
              <Link key={item.analysisId} to={`/analyses/${item.analysisId}`} className={cn('block rounded-2xl border border-white/10 bg-white/5 px-4 py-3 transition hover:border-primary/25 hover:bg-white/10', focusRing)}>
                <div className="flex items-center justify-between gap-3">
                  <div className="font-medium text-ink">{item.title}</div>
                  <StatusPill tone={toneForStatus(item.status)}>{item.statusLabel}</StatusPill>
                </div>
                <div className="mt-2 text-xs leading-5 text-muted">{item.summary || item.question}</div>
              </Link>
            ))}
            {!activeItems.length ? <div className="text-sm leading-6 text-muted">当前没有需要继续跟进的任务。</div> : null}
          </div>
        </PageCard>
      </div>
    </div>
  )
}

function MetricCard({ label, value, caption, tone = 'neutral' }: { label: string; value: string; caption: string; tone?: 'neutral' | 'success' | 'warning' }) {
  return (
    <div className={cn('rounded-[26px] border bg-white/5 px-5 py-5 shadow-subtle', tone === 'success' ? 'border-emerald-400/20' : tone === 'warning' ? 'border-amber-400/20' : 'border-white/10')}>
      <div className="text-xs uppercase tracking-[0.16em] text-muted">{label}</div>
      <div className="mt-3 font-mono text-[1.9rem] font-semibold text-ink">{value}</div>
      <div className="mt-2 text-xs leading-5 text-muted">{caption}</div>
    </div>
  )
}

function MiniStat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-2xl border border-white/10 bg-black/20 px-3 py-3">
      <div className="text-[11px] uppercase tracking-[0.16em] text-muted">{label}</div>
      <div className="mt-2 font-mono text-xl font-semibold text-ink">{value}</div>
    </div>
  )
}

function toneForStatus(status: string) {
  if (status === 'success') return 'success'
  if (status === 'failed') return 'error'
  if (status === 'waiting_for_human') return 'warning'
  return 'neutral'
}
