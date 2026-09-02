import { lazy, Suspense } from "react";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import { Layout } from "@/components/layout";
import { PageState } from "@/components/page-state";
import { NotFoundPage } from "@/pages/not-found";

const OverviewPage = lazy(() => import("@/pages/overview"));
const ExceptionDetailPage = lazy(() => import("@/pages/exception-detail"));
const ExceptionsPage = lazy(() => import("@/pages/exceptions"));
const RunDetailPage = lazy(() => import("@/pages/run-detail"));
const RunsPage = lazy(() => import("@/pages/runs"));
const TransactionsPage = lazy(() => import("@/pages/transactions"));
const AuditPage = lazy(() => import("@/pages/audit"));
const CopilotPage = lazy(() => import("@/pages/copilot"));
const SettingsPage = lazy(() => import("@/pages/settings"));

function App() {
  return (
    <BrowserRouter>
       <Suspense fallback={<PageState kind="loading" headingLevel="h1" title="Loading RoboRecon…" description="Getting the workspace ready." />}>
        <Routes>
          <Route element={<Layout />}>
            <Route path="/" element={<OverviewPage />} />
            <Route path="/runs" element={<RunsPage />} />
            <Route path="/runs/:runId" element={<RunDetailPage />} />
            <Route path="/transactions" element={<TransactionsPage />} />
            <Route path="/exceptions" element={<ExceptionsPage />} />
            <Route path="/exceptions/:exceptionId" element={<ExceptionDetailPage />} />
            <Route path="/audit" element={<AuditPage />} />
            <Route path="/copilot" element={<CopilotPage />} />
            <Route path="/settings" element={<SettingsPage />} />
            <Route path="*" element={<NotFoundPage title="Page not found" description="This page is not part of the workspace." />} />
          </Route>
        </Routes>
      </Suspense>
    </BrowserRouter>
  );
}

export default App;
