import type { ReactNode } from "react";

interface PageHeaderProps {
  title: string;
  description?: ReactNode;
  backLink?: ReactNode;
  status?: ReactNode;
  actions?: ReactNode;
}

export function PageHeader({ title, description, backLink, status, actions }: PageHeaderProps) {
  return (
    <header className="page-header">
      <div className="min-w-0">
        {backLink}
        <div className="flex flex-wrap items-center gap-2.5">
          <h1 className="page-title">{title}</h1>
          {status}
        </div>
        {description && <p className="page-description">{description}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </header>
  );
}
