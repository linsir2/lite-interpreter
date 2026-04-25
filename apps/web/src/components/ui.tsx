import type {
  ButtonHTMLAttributes,
  InputHTMLAttributes,
  PropsWithChildren,
  ReactNode,
  SelectHTMLAttributes,
  TextareaHTMLAttributes,
} from 'react'

import { cn } from '@/lib/utils'

export function PageCard({ className, children }: PropsWithChildren<{ className?: string }>) {
  return (
    <section
      className={cn(
        'relative overflow-hidden rounded-[32px] border border-white/10 bg-surface shadow-panel backdrop-blur-xl',
        className,
      )}
    >
      {children}
    </section>
  )
}

type SectionHeaderLevel = 'h1' | 'h2'

export function SectionHeader({
  title,
  description,
  action,
  level = 'h2',
}: {
  title: string
  description?: string
  action?: ReactNode
  level?: SectionHeaderLevel
}) {
  const HeadingTag = level

  return (
    <div className="flex flex-col gap-4 border-b border-white/10 px-6 py-5 sm:flex-row sm:items-end sm:justify-between sm:px-7">
      <div className="max-w-3xl">
        <div className="mb-3 h-1 w-14 rounded-full bg-gradient-to-r from-primary via-[#f2d39a] to-primary shadow-[0_0_0_1px_rgba(255,255,255,0.06)]" />
        <HeadingTag
          className={cn(
            'font-semibold tracking-[-0.02em] text-ink',
            level === 'h1' ? 'text-[1.35rem] sm:text-[1.55rem]' : 'text-[1.1rem] sm:text-[1.2rem]',
          )}
        >
          {title}
        </HeadingTag>
        {description ? <p className="mt-2 text-sm leading-6 text-muted">{description}</p> : null}
      </div>
      {action ? <div className="shrink-0">{action}</div> : null}
    </div>
  )
}

export function Button({
  className,
  variant = 'primary',
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: 'primary' | 'secondary' | 'ghost' }) {
  return (
    <button
      className={cn(
        'inline-flex min-h-11 items-center justify-center gap-2 rounded-full px-4 py-2 text-sm font-semibold transition duration-150 active:scale-[0.99] disabled:cursor-not-allowed disabled:opacity-60',
        variant === 'primary' && 'bg-primary text-[#0a0d10] shadow-[0_12px_30px_rgba(215,176,110,0.22)] hover:-translate-y-[1px] hover:bg-primary-hover',
        variant === 'secondary' && 'border border-white/10 bg-white/5 text-ink hover:-translate-y-[1px] hover:border-white/20 hover:bg-white/10',
        variant === 'ghost' && 'text-muted hover:bg-white/5 hover:text-ink',
        className,
      )}
      {...props}
    />
  )
}

export function FieldLabel({
  children,
  htmlFor,
}: PropsWithChildren<{ htmlFor?: string }>) {
  return (
    <label className="mb-2 block text-xs font-semibold uppercase tracking-[0.16em] text-[#b7b0a2]" htmlFor={htmlFor}>
      {children}
    </label>
  )
}

export function TextInput(props: InputHTMLAttributes<HTMLInputElement>) {
  const { className, ...rest } = props
  return (
    <input
      className={cn(
        'w-full rounded-2xl border border-white/10 bg-[rgba(10,14,19,0.88)] px-4 py-3 text-sm text-ink outline-none ring-0 transition placeholder:text-[#7f7a70] focus:border-primary/50 focus:shadow-[0_0_0_4px_rgba(215,176,110,0.08)]',
        className,
      )}
      {...rest}
    />
  )
}

export function TextArea(props: TextareaHTMLAttributes<HTMLTextAreaElement>) {
  const { className, ...rest } = props
  return (
    <textarea
      className={cn(
        'min-h-36 w-full rounded-2xl border border-white/10 bg-[rgba(10,14,19,0.88)] px-4 py-3 text-sm text-ink outline-none transition placeholder:text-[#7f7a70] focus:border-primary/50 focus:shadow-[0_0_0_4px_rgba(215,176,110,0.08)]',
        className,
      )}
      {...rest}
    />
  )
}

export function Select(props: SelectHTMLAttributes<HTMLSelectElement>) {
  const { className, ...rest } = props
  return (
    <select
      className={cn(
        'w-full rounded-2xl border border-white/10 bg-[rgba(10,14,19,0.88)] px-4 py-3 text-sm text-ink outline-none transition focus:border-primary/50 focus:shadow-[0_0_0_4px_rgba(215,176,110,0.08)]',
        className,
      )}
      {...rest}
    />
  )
}

export function StatusPill({ tone = 'neutral', children }: PropsWithChildren<{ tone?: 'neutral' | 'success' | 'warning' | 'error' }>) {
  const toneClass = {
    neutral: 'border-white/10 bg-white/5 text-ink',
    success: 'border-emerald-400/20 bg-emerald-500/10 text-emerald-300',
    warning: 'border-amber-400/20 bg-amber-500/10 text-amber-300',
    error: 'border-rose-400/20 bg-rose-500/10 text-rose-300',
  }[tone]
  return <span className={cn('inline-flex rounded-full border px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.1em]', toneClass)}>{children}</span>
}
