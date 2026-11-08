import React from 'react';

interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: 'primary' | 'secondary' | 'outline' | 'ghost';
  size?: 'sm' | 'md' | 'lg';
  icon?: React.ReactNode;
  loading?: boolean;
}

const VARIANT = {
  primary: 'bg-[#181715] text-[#FAF8F5] hover:bg-[#262523] border border-[#181715] active:bg-black',
  outline: 'bg-transparent text-[#181715] hover:bg-[#F4F0E8] border border-[#DDD5C7] active:border-[#181715]',
  ghost: 'bg-transparent text-[#5C5852] hover:text-[#181715] hover:bg-[#F4F0E8] border border-transparent',
  secondary: 'bg-white text-[#181715] hover:bg-[#FAF8F5] border border-[#DDD5C7] shadow-sm',
} as const;

const SIZE = {
  sm: 'px-2.5 py-1 text-xs gap-1.5',
  md: 'px-3.5 py-1.5 text-xs font-medium gap-2',
  lg: 'px-5 py-2.5 text-sm gap-2.5',
} as const;

export const Button: React.FC<ButtonProps> = ({
  variant = 'secondary',
  size = 'md',
  children,
  icon,
  loading = false,
  className = '',
  disabled,
  type = 'button',
  ...props
}) => (
  <button
    type={type}
    disabled={disabled || loading}
    aria-busy={loading || undefined}
    className={`inline-flex items-center justify-center font-sans rounded-[6px] transition-all duration-150 cursor-pointer disabled:opacity-40 disabled:cursor-not-allowed focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#181715] ${SIZE[size]} ${VARIANT[variant]} ${className}`}
    {...props}
  >
    {loading ? <span className="w-3 h-3 rounded-full border-2 border-current border-t-transparent animate-spin" aria-hidden /> : icon}
    {children}
  </button>
);
