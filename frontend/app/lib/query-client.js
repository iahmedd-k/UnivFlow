'use client';

import { QueryClient } from '@tanstack/react-query';

let browserQueryClient;

export function getQueryClient() {
  if (typeof window === 'undefined') {
    return new QueryClient({
      defaultOptions: {
        queries: { staleTime: 60_000, gcTime: 5 * 60_000, retry: false, refetchOnWindowFocus: false },
      },
    });
  }

  browserQueryClient ??= new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 60_000,
        gcTime: 5 * 60_000,
        retry: false,
        refetchOnWindowFocus: false,
        refetchOnReconnect: true,
      },
    },
  });

  return browserQueryClient;
}
