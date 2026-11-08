import React from 'react';

const base =
  'h-9 px-3 bg-white border border-[#DDD5C7] rounded-md text-sm text-[#181715] placeholder:text-[#8C867D] transition-colors hover:border-[#BDB3A1] focus:border-[#181715] focus:outline-none';

export const TextInput = React.forwardRef<HTMLInputElement, React.InputHTMLAttributes<HTMLInputElement>>(
  ({ className = '', ...props }, ref) => <input ref={ref} className={`${base} ${className}`} {...props} />,
);
TextInput.displayName = 'TextInput';

export const Select: React.FC<React.SelectHTMLAttributes<HTMLSelectElement>> = ({ className = '', children, ...props }) => (
  <select className={`${base} pr-8 cursor-pointer ${className}`} {...props}>
    {children}
  </select>
);

/** Label + control wrapper. */
export const Field: React.FC<{ label: string; htmlFor: string; children: React.ReactNode; className?: string }> = ({
  label,
  htmlFor,
  children,
  className = '',
}) => (
  <div className={`flex flex-col gap-1 ${className}`}>
    <label htmlFor={htmlFor} className="editorial-label text-[10px]">
      {label}
    </label>
    {children}
  </div>
);
