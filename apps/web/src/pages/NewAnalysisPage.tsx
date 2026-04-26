import { ArrowRight, FileStack, ShieldCheck, Sparkles } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'

import { Button, FeedbackState, FieldLabel, PageCard, QueryFeedback, SectionHeader, Select, StatusPill, TextArea, focusRing } from '@/components/ui'
import type { AssetListItem, CreateAnalysisResponse } from '@/lib/types'
import { cn } from '@/lib/utils'

export function NewAnalysisPage({
  assets,
  assetsLoading = false,
  assetsErrorMessage,
  onRetryAssets,
  onSubmit,
}: {
  assets: AssetListItem[]
  assetsLoading?: boolean
  assetsErrorMessage?: string | null
  onRetryAssets?: () => void
  onSubmit: (input: { question: string; assetIds: string[]; analysisModePreset?: string | null }) => Promise<CreateAnalysisResponse>
}) {
  const navigate = useNavigate()
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

  return (
    <div className="space-y-6">
      <PageCard>
        <SectionHeader
          title="新建分析任务"
          level="h1"
          description="明确分析目标、选择资料与运行策略，然后启动一次可复核的受控分析。"
          action={<StatusPill tone="success">业务输入面</StatusPill>}
        />
        <form
          className="grid gap-6 px-6 py-6 lg:grid-cols-[minmax(0,1.05fr)_420px] lg:px-7"
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
          <div className="space-y-5">
            <div className="rounded-[30px] border border-primary/20 bg-[radial-gradient(circle_at_80%_10%,rgba(215,176,110,0.16),transparent_30%)] bg-white/5 px-5 py-5 text-ink shadow-subtle">
              <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.18em] text-primary">
                <Sparkles className="h-4 w-4" />
                填写建议
              </div>
              <div className="mt-4 space-y-2 text-sm leading-6 text-muted">
                <p>说明时间范围、对比对象和希望验证的异常点。</p>
                <p>如果已有怀疑方向，可以直接写明，例如折扣、费用分摊、账龄风险。</p>
                <p>稳定结构化输入以 csv / tsv / json 为准；其他文件先作为业务说明材料处理。</p>
              </div>
            </div>

            <div>
              <FieldLabel htmlFor="new-analysis-question">分析目标与问题</FieldLabel>
              <TextArea
                id="new-analysis-question"
                className="min-h-[220px]"
                placeholder="例如：请结合利润表、费用明细和销售数据，解释本月利润下降的主要原因，并列出需要优先核对的异常项目。"
                value={question}
                onChange={(event) => setQuestion(event.target.value)}
                required
              />
            </div>

            <div className="grid gap-4 md:grid-cols-[minmax(0,1fr)_220px]">
              <div>
                <FieldLabel htmlFor="new-analysis-mode">分析策略</FieldLabel>
                <Select id="new-analysis-mode" value={analysisModePreset} onChange={(event) => setAnalysisModePreset(event.target.value)}>
                  <option value="researcher">Researcher · 先探索原因与线索</option>
                  <option value="reviewer">Reviewer · 更强调核验和风险控制</option>
                  <option value="planner">Planner · 更强调结构化拆解</option>
                </Select>
              </div>
              <div>
                <FieldLabel>已选资料</FieldLabel>
                <div className="rounded-2xl border border-white/10 bg-white/5 px-4 py-3 text-sm text-muted">
                  {selectedAssets.length} / {assets.length} 项
                </div>
              </div>
            </div>

            <QueryFeedback
              errorMessage={assetsErrorMessage}
              loading={assetsLoading && !assets.length}
              loadingTitle="正在加载可选资料"
              loadingDescription="正在读取当前工作区可用于本次分析的资料。"
              errorTitle="可选资料加载失败"
              onRetry={onRetryAssets}
              retryLabel="重新加载资料"
            />

            {error ? <FeedbackState title="分析任务创建失败" description={error} tone="error" /> : null}

            <div className="flex flex-wrap items-center gap-3">
              <Button disabled={submitting || !question.trim()} type="submit">
                {submitting ? '提交中…' : '开始分析'}
                <ArrowRight className="h-4 w-4" />
              </Button>
              <Link className={cn('inline-flex min-h-11 items-center justify-center rounded-full px-4 text-sm font-semibold text-muted transition hover:bg-white/5 hover:text-ink', focusRing)} to="/analyses">
                返回业务工作台
              </Link>
            </div>
          </div>

          <div className="space-y-5 rounded-[30px] border border-white/10 bg-white/5 p-5 shadow-subtle">
            <div className="flex items-start justify-between gap-3">
              <div>
                <div className="flex items-center gap-2 text-base font-semibold text-ink">
                  <FileStack className="h-5 w-5 text-primary" />
                  选择引用资料
                </div>
                <p className="mt-2 text-sm leading-6 text-muted">只勾选本次分析真正需要的资料，避免结论被无关输入污染。</p>
              </div>
              <ShieldCheck className="h-5 w-5 text-emerald-300" />
            </div>

            <div className="space-y-3">
              {assets.map((asset) => {
                const selected = assetIds.includes(asset.assetId)
                return (
                  <label
                    key={asset.assetId}
                    className={cn(
                      'flex cursor-pointer items-start gap-3 rounded-2xl border px-4 py-3 transition',
                      selected ? 'border-primary/30 bg-primary/10' : 'border-white/10 bg-black/20 hover:border-white/20 hover:bg-white/5',
                    )}
                  >
                    <input
                      className="mt-1 accent-[#d7b06e]"
                      type="checkbox"
                      checked={selected}
                      onChange={(event) => {
                        setAssetIds((current) =>
                          event.target.checked
                            ? [...current, asset.assetId]
                            : current.filter((item) => item !== asset.assetId),
                        )
                      }}
                    />
                    <div className="min-w-0">
                      <div className="font-medium text-ink">{asset.name}</div>
                      <div className="mt-1 text-xs text-muted">{asset.kind} · {asset.readinessLabel}</div>
                    </div>
                  </label>
                )
              })}
              {!assetsLoading && !assetsErrorMessage && !assets.length ? (
                <FeedbackState
                  title="还没有可选资料"
                  description="可以先启动仅基于问题描述的分析；如需证据链更完整，请先到资料库上传 csv / tsv / json 或业务说明材料。"
                  action={<Link className={cn('inline-flex min-h-11 items-center rounded-full text-sm font-semibold text-primary hover:text-primary-hover', focusRing)} to="/assets">前往资料库</Link>}
                />
              ) : null}
            </div>
          </div>
        </form>
      </PageCard>
    </div>
  )
}
