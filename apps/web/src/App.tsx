import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { lazy, Suspense } from "react";
import { Navigate, Route, Routes } from "react-router-dom";

import { api, rememberedDemoPersona } from "./api/client";
import type { PersonaRole } from "./api/generated";
import { Shell } from "./components/shell";
import { ErrorState, LoadingState } from "./components/ui";

const CommandCenterPage = lazy(async () => ({
  default: (await import("./pages/CommandCenter")).CommandCenterPage,
}));
const SourcesPage = lazy(async () => ({
  default: (await import("./pages/Registry")).SourcesPage,
}));
const FormsPage = lazy(async () => ({
  default: (await import("./pages/Registry")).FormsPage,
}));
const MappingPage = lazy(async () => ({
  default: (await import("./pages/Operations")).MappingPage,
}));
const PipelineRunsPage = lazy(async () => ({
  default: (await import("./pages/Operations")).PipelineRunsPage,
}));
const QuarantinePage = lazy(async () => ({
  default: (await import("./pages/Operations")).QuarantinePage,
}));
const DocumentLabPage = lazy(async () => ({
  default: (await import("./pages/Research")).DocumentLabPage,
}));
const OmopPage = lazy(async () => ({
  default: (await import("./pages/Research")).OmopPage,
}));
const CatalogPage = lazy(async () => ({
  default: (await import("./pages/Research")).CatalogPage,
}));
const LineagePage = lazy(async () => ({
  default: (await import("./pages/Research")).LineagePage,
}));
const HealthPage = lazy(async () => ({
  default: (await import("./pages/Research")).HealthPage,
}));

export function App() {
  const queryClient = useQueryClient();
  const session = useQuery({
    queryKey: ["session"],
    queryFn: () => api.openSession(rememberedDemoPersona()),
    staleTime: Number.POSITIVE_INFINITY,
    retry: 2,
  });
  const switchPersona = useMutation({
    mutationFn: (role: PersonaRole) => api.openSession(role),
    onSuccess: (next) => {
      queryClient.setQueryData(["session"], next);
      void queryClient.invalidateQueries({
        predicate: (query) => query.queryKey[0] !== "session",
      });
    },
  });

  if (session.isPending)
    return (
      <div className="boot-screen">
        <LoadingState label="Opening the bounded demo workspace" />
      </div>
    );
  if (session.error)
    return (
      <div className="boot-screen">
        <ErrorState error={session.error} />
      </div>
    );

  return (
    <Shell
      actor={session.data.actor}
      onPersonaChange={(role) => switchPersona.mutate(role)}
      switching={switchPersona.isPending}
    >
      <Suspense fallback={<LoadingState label="Loading workspace" />}>
        <Routes>
          <Route path="/" element={<CommandCenterPage />} />
          <Route path="/sources" element={<SourcesPage />} />
          <Route path="/forms" element={<FormsPage />} />
          <Route path="/forms/:formVersionId" element={<FormsPage />} />
          <Route
            path="/mappings"
            element={<MappingPage actor={session.data.actor} />}
          />
          <Route
            path="/runs"
            element={<PipelineRunsPage actor={session.data.actor} />}
          />
          <Route
            path="/quarantine"
            element={<QuarantinePage actor={session.data.actor} />}
          />
          <Route
            path="/documents"
            element={<DocumentLabPage actor={session.data.actor} />}
          />
          <Route path="/omop" element={<OmopPage />} />
          <Route path="/catalog" element={<CatalogPage />} />
          <Route path="/lineage" element={<LineagePage />} />
          <Route path="/health" element={<HealthPage />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </Suspense>
    </Shell>
  );
}
