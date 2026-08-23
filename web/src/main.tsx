import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
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
    <QueryClientProvider client={client}>
      <App />
    </QueryClientProvider>
  </StrictMode>,
);
