import { Link } from "react-router-dom";
import { IconArrowLeft } from "@tabler/icons-react";
import { PageHeader } from "@/components/page-header";

export function NotFoundPage({ title, description }: { title: string; description: string }) {
  return (
    <div className="page-stack">
      <PageHeader title={title} description={description} />
      <div className="panel flex min-h-56 flex-col items-center justify-center px-6 py-12 text-center">
        <p className="text-sm text-muted-foreground">This page does not exist.</p>
        <Link to="/" className="mt-4 inline-flex items-center gap-2 text-sm text-primary hover:text-primary/80">
          <IconArrowLeft className="size-4" aria-hidden="true" /> Back to overview
        </Link>
      </div>
    </div>
  );
}

export default NotFoundPage;
