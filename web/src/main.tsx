import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { LazyMotion, MotionConfig } from "motion/react";
import { TooltipProvider } from "@/components/ui/tooltip";
import { assertPalettesResolve } from "@/themes/registry";
import App from "@/App";
import "@/index.css";

assertPalettesResolve();

const client = new QueryClient({
  defaultOptions: {
    queries: {
      // League state changes on the platform's clock, not ours, and every fetch
      // is a real API call the platform rate-limits. Refetching because a window
      // regained focus buys nothing here.
      refetchOnWindowFocus: false,
      staleTime: 60_000,
      retry: false,
    },
  },
});

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <BrowserRouter>
      <QueryClientProvider client={client}>
      {/* Loaded after first paint, not bundled into it: `m` components carry
          no animation code of their own, and the feature set arrives in a
          second chunk. It has to come from its own module: an import of
          `motion/react` from here resolves to this same bundle and never
          splits. `strict` makes a stray
          `motion.*` import — which would do exactly that — a runtime error.
          `reducedMotion="user"` means every variant respects the OS setting
          without a branch at any call site. */}
      <LazyMotion features={() => import("@/lib/motion-features").then((mod) => mod.default)} strict>
        <MotionConfig reducedMotion="user">
          <TooltipProvider>
            <App />
          </TooltipProvider>
        </MotionConfig>
      </LazyMotion>
      </QueryClientProvider>
    </BrowserRouter>
  </StrictMode>,
);
