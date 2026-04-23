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
        'rounded-[30px] border border-border bg-surface shadow-panel backdrop-blur-sm',
        className,
      )}
    >
      {children}
    </section>
  )
}

export function SectionHeader({ title, description, action }: { title: string; description?: string; action?: ReactNode }) {
  return (
    <div className="flex flex-col gap-3 border-b border-border px-6 py-5 sm:flex-row sm:items-end sm:justify-between">
      <div>
        <div className="mb-2 h-1 w-12 rounded-full bg-accent/70" />
        <h2 className="text-[1.05rem] font-semibold tracking-[-0.01em] text-ink">{title}</h2>
        {description ? <p className="mt-1 text-sm leading-6 text-muted">{description}</p> : null}
      </div>
      {action}
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
        'inline-flex items-center justify-center rounded-full px-4 py-2 text-sm font-semibold transition duration-150 active:scale-[0.99]',
        variant === 'primary' && 'bg-primary text-white shadow-subtle hover:-translate-y-[1px] hover:bg-primary-hover',
        variant === 'secondary' && 'border border-border bg-surface-2 text-ink hover:-translate-y-[1px] hover:bg-canvas',
        variant === 'ghost' && 'text-muted hover:bg-surface-2 hover:text-ink',
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
    <label className="mb-2 block text-sm font-medium text-ink" htmlFor={htmlFor}>
      {children}
    </label>
  )
}

export function TextInput(props: InputHTMLAttributes<HTMLInputElement>) {
  const { className, ...rest } = props
  return (
    <input
      className={cn(
        'w-full rounded-2xl border border-border bg-surface px-4 py-3 text-sm text-ink outline-none ring-0 transition focus:border-primary/30 focus:shadow-subtle placeholder:text-muted',
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
        'min-h-36 w-full rounded-2xl border border-border bg-surface px-4 py-3 text-sm text-ink outline-none transition focus:border-primary/30 focus:shadow-subtle placeholder:text-muted',
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
        'w-full rounded-2xl border border-border bg-surface px-4 py-3 text-sm text-ink outline-none transition focus:border-primary/30 focus:shadow-subtle',
        className,
      )}
      {...rest}
    />
  )
}

export function StatusPill({ tone = 'neutral', children }: PropsWithChildren<{ tone?: 'neutral' | 'success' | 'warning' | 'error' }>) {
  const toneClass = {
    neutral: 'bg-surface-2 text-muted border-border',
    success: 'bg-emerald-50 text-emerald-700 border-emerald-100',
    warning: 'bg-amber-50 text-amber-700 border-amber-100',
    error: 'bg-rose-50 text-rose-700 border-rose-100',
  }[tone]
  return <span className={cn('inline-flex rounded-full border px-3 py-1 text-[11px] font-semibold tracking-[0.08em] uppercase', toneClass)}>{children}</span>
}
