import React, { createContext, useCallback, useContext, useState } from "react";
import * as DialogPrimitive from "@radix-ui/react-dialog";
import * as SelectPrimitive from "@radix-ui/react-select";
import { Slot } from "@radix-ui/react-slot";
import { cva, type VariantProps } from "class-variance-authority";
import { Check, ChevronDown, X } from "lucide-react";
import { cn } from "../../lib/utils";

/* ============================================================================
 * 1. BUTTON
 * ========================================================================== */
const buttonVariants = cva(
  "inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-card text-body font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-700 focus-visible:ring-offset-2 disabled:pointer-events-none disabled:opacity-50",
  {
    variants: {
      variant: {
        primary: "bg-brand-700 text-white hover:bg-brand-800 shadow-soft",
        secondary: "bg-canvas-card text-ink border border-border hover:bg-canvas-subtle",
        ghost: "bg-transparent text-ink-secondary hover:bg-canvas-subtle hover:text-ink",
        subtle: "bg-brand-50 text-brand-800 hover:bg-brand-100",
        danger: "bg-feedback-danger text-white hover:opacity-95",
      },
      size: {
        sm: "h-9 px-3 text-caption",
        md: "h-11 px-5 text-body",
        lg: "h-12 px-6 text-body font-semibold",
      },
    },
    defaultVariants: {
      variant: "primary",
      size: "md",
    },
  }
);

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {
  asChild?: boolean;
}

export const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, asChild = false, ...props }, ref) => {
    const Comp = asChild ? Slot : "button";
    return (
      <Comp
        className={cn(buttonVariants({ variant, size, className }))}
        ref={ref}
        {...props}
      />
    );
  }
);
Button.displayName = "Button";

/* ============================================================================
 * 2. CARD
 * ========================================================================== */
export const Card = React.forwardRef<
  HTMLDivElement,
  React.HTMLAttributes<HTMLDivElement>
>(({ className, ...props }, ref) => (
  <div
    ref={ref}
    className={cn(
      "rounded-card border border-border bg-canvas-card text-ink shadow-soft",
      className
    )}
    {...props}
  />
));
Card.displayName = "Card";

/* ============================================================================
 * 3. INPUT
 * ========================================================================== */
export interface InputProps extends React.InputHTMLAttributes<HTMLInputElement> {}

export const Input = React.forwardRef<HTMLInputElement, InputProps>(
  ({ className, type = "text", ...props }, ref) => (
    <input
      type={type}
      ref={ref}
      className={cn(
        "flex h-11 w-full rounded-card border border-border bg-canvas-card px-3.5 py-2 text-body text-ink placeholder:text-ink-muted transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-700 focus-visible:border-brand-700 disabled:cursor-not-allowed disabled:opacity-50",
        className
      )}
      {...props}
    />
  )
);
Input.displayName = "Input";

/* ============================================================================
 * 4. SELECT (Radix UI / shadcn)
 * ========================================================================== */
export interface SelectOption {
  value: string;
  label: string;
}

export interface SelectProps {
  value: string;
  onValueChange: (val: string) => void;
  options: SelectOption[];
  placeholder?: string;
  ariaLabel?: string;
  className?: string;
  id?: string;
}

export function Select({
  value,
  onValueChange,
  options,
  placeholder = "Sélectionner",
  ariaLabel,
  className,
  id,
}: SelectProps) {
  if (typeof document === "undefined") {
    const selectedOpt = options.find((o) => o.value === value);
    return (
      <button
        type="button"
        id={id}
        aria-label={ariaLabel || placeholder}
        className={cn(
          "flex h-11 w-full items-center justify-between gap-2 rounded-card border border-border bg-canvas-card px-3.5 py-2 text-body text-ink shadow-sm transition-colors",
          className
        )}
      >
        <span>{selectedOpt ? selectedOpt.label : placeholder}</span>
        <ChevronDown className="h-4 w-4 text-ink-muted shrink-0" />
      </button>
    );
  }

  return (
    <SelectPrimitive.Root value={value} onValueChange={onValueChange}>
      <SelectPrimitive.Trigger
        id={id}
        aria-label={ariaLabel || placeholder}
        className={cn(
          "flex h-11 w-full items-center justify-between gap-2 rounded-card border border-border bg-canvas-card px-3.5 py-2 text-body text-ink shadow-sm transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-700",
          className
        )}
      >
        <SelectPrimitive.Value placeholder={placeholder} />
        <SelectPrimitive.Icon asChild>
          <ChevronDown className="h-4 w-4 text-ink-muted shrink-0" />
        </SelectPrimitive.Icon>
      </SelectPrimitive.Trigger>
      <SelectPrimitive.Portal>
        <SelectPrimitive.Content
          position="popper"
          sideOffset={6}
          className="z-50 min-w-[180px] overflow-hidden rounded-card border border-border bg-canvas-card p-1 text-ink shadow-popover"
        >
          <SelectPrimitive.Viewport className="p-1">
            {options.map((opt) => (
              <SelectPrimitive.Item
                key={opt.value}
                value={opt.value}
                className="relative flex cursor-pointer select-none items-center rounded-md py-2 pl-8 pr-3 text-body text-ink outline-none focus:bg-brand-50 focus:text-brand-800 data-[disabled]:pointer-events-none data-[disabled]:opacity-50"
              >
                <span className="absolute left-2 flex h-4 w-4 items-center justify-center">
                  <SelectPrimitive.ItemIndicator>
                    <Check className="h-4 w-4 text-brand-700" />
                  </SelectPrimitive.ItemIndicator>
                </span>
                <SelectPrimitive.ItemText>{opt.label}</SelectPrimitive.ItemText>
              </SelectPrimitive.Item>
            ))}
          </SelectPrimitive.Viewport>
        </SelectPrimitive.Content>
      </SelectPrimitive.Portal>
    </SelectPrimitive.Root>
  );
}

/* ============================================================================
 * 5. MODAL (Radix Dialog / shadcn)
 * ========================================================================== */
export interface ModalProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  description?: string;
  children: React.ReactNode;
  maxWidthClass?: string;
}

export function Modal({
  open,
  onOpenChange,
  title,
  description,
  children,
  maxWidthClass = "max-w-lg",
}: ModalProps) {
  if (typeof document === "undefined") {
    if (!open) return null;
    return (
      <div
        role="dialog"
        aria-modal="true"
        className={cn(
          "rounded-card border border-border bg-canvas-card p-6 shadow-popover",
          maxWidthClass
        )}
      >
        <div className="flex items-start justify-between gap-4 mb-4">
          <div>
            <h2 className="text-h2 text-ink">{title}</h2>
            {description && (
              <p className="mt-1 text-caption text-ink-muted">{description}</p>
            )}
          </div>
        </div>
        {children}
      </div>
    );
  }

  return (
    <DialogPrimitive.Root open={open} onOpenChange={onOpenChange}>
      <DialogPrimitive.Portal>
        <DialogPrimitive.Overlay className="fixed inset-0 z-50 bg-ink/40 backdrop-blur-[1px]" />
        <DialogPrimitive.Content
          className={cn(
            "fixed left-1/2 top-1/2 z-50 w-[92vw] -translate-x-1/2 -translate-y-1/2 rounded-card border border-border bg-canvas-card p-6 shadow-popover focus:outline-none",
            maxWidthClass
          )}
        >
          <div className="flex items-start justify-between gap-4 mb-4">
            <div>
              <DialogPrimitive.Title className="text-h2 text-ink">
                {title}
              </DialogPrimitive.Title>
              {description && (
                <DialogPrimitive.Description className="mt-1 text-caption text-ink-muted">
                  {description}
                </DialogPrimitive.Description>
              )}
            </div>
            <DialogPrimitive.Close
              aria-label="Fermer"
              className="rounded-md p-1.5 text-ink-muted hover:bg-canvas-subtle hover:text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-700"
            >
              <X className="h-4 w-4" />
            </DialogPrimitive.Close>
          </div>
          {children}
        </DialogPrimitive.Content>
      </DialogPrimitive.Portal>
    </DialogPrimitive.Root>
  );
}

/* ============================================================================
 * 6. BADGE
 * ========================================================================== */
const badgeVariants = cva(
  "inline-flex items-center gap-1 rounded-md px-2.5 py-0.5 text-caption font-medium whitespace-nowrap shrink-0",
  {
    variants: {
      variant: {
        default: "bg-canvas-subtle text-ink-secondary border border-border",
        neutral: "bg-canvas-subtle text-ink-secondary border border-border",
        brand: "bg-brand-50 text-brand-800 border border-brand-200",
        success: "bg-feedback-successBg text-feedback-success border border-green-200",
        warning: "bg-feedback-warningBg text-feedback-warning border border-amber-200",
      },
    },
    defaultVariants: {
      variant: "neutral",
    },
  }
);

export interface BadgeProps
  extends React.HTMLAttributes<HTMLSpanElement>,
    VariantProps<typeof badgeVariants> {}

export function Badge({ className, variant, ...props }: BadgeProps) {
  return <span className={cn(badgeVariants({ variant }), className)} {...props} />;
}

/* ============================================================================
 * 7. SKELETON
 * ========================================================================== */
export function Skeleton({
  className,
  ...props
}: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn("animate-pulse rounded-card bg-slate-200/80", className)}
      {...props}
    />
  );
}

/* ============================================================================
 * 8. TOAST
 * ========================================================================== */
export interface ToastItem {
  id: string;
  title: string;
  description?: string;
  tone?: "default" | "success" | "info" | "warning" | "danger";
}

interface ToastContextValue {
  notify: (toast: Omit<ToastItem, "id">) => void;
}

const ToastContext = createContext<ToastContextValue>({
  notify: () => {},
});

export function useToast() {
  return useContext(ToastContext);
}

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toasts, setToasts] = useState<ToastItem[]>([]);

  const notify = useCallback((toast: Omit<ToastItem, "id">) => {
    const id = `${Date.now()}-${Math.random().toString(36).slice(2, 6)}`;
    setToasts((prev) => [...prev, { ...toast, id }]);
    setTimeout(() => {
      setToasts((prev) => prev.filter((t) => t.id !== id));
    }, 4000);
  }, []);

  return (
    <ToastContext.Provider value={{ notify }}>
      {children}
      <div
        aria-live="polite"
        className="fixed bottom-4 right-4 z-50 flex flex-col gap-2 max-w-sm w-full pointer-events-none px-4 sm:px-0"
      >
        {toasts.map((t) => (
          <div
            key={t.id}
            className={cn(
              "pointer-events-auto flex items-start justify-between gap-3 rounded-card border p-4 shadow-popover transition-all",
              t.tone === "success"
                ? "bg-feedback-successBg border-green-200 text-feedback-success"
                : "bg-canvas-card border-border text-ink"
            )}
          >
            <div>
              <p className="text-body font-semibold">{t.title}</p>
              {t.description && (
                <p className="mt-0.5 text-caption text-ink-secondary">{t.description}</p>
              )}
            </div>
            <button
              type="button"
              onClick={() => setToasts((prev) => prev.filter((item) => item.id !== t.id))}
              className="rounded-md p-1 text-ink-muted hover:text-ink"
              aria-label="Fermer la notification"
            >
              <X className="h-4 w-4" />
            </button>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}
