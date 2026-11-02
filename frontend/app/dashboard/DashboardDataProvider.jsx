'use client';

import { QueryClientProvider } from '@tanstack/react-query';
import { useAuth } from '@clerk/nextjs';
import { useEffect, useRef } from 'react';
import { getQueryClient } from '@/app/lib/query-client';
import { getQueryOwnerKey } from '@/app/lib/manual-auth';

function QueryIdentityBoundary({ children }) {
  const { userId } = useAuth();
  const queryClient = getQueryClient();
  const ownerKey = getQueryOwnerKey(userId);
  const previousOwner = useRef(null);

  useEffect(() => {
    const previous = previousOwner.current;
    if (previous && previous !== ownerKey) {
      void queryClient.cancelQueries({ predicate: (query) => query.queryKey.includes(previous) });
      queryClient.removeQueries({ predicate: (query) => query.queryKey.includes(previous) });
      queryClient.removeQueries({ queryKey: ['http'] });
    }
    previousOwner.current = ownerKey;
  }, [ownerKey, queryClient]);

  return children;
}

export default function DashboardDataProvider({ children }) {
  const queryClient = getQueryClient();
  return (
    <QueryClientProvider client={queryClient}>
      <QueryIdentityBoundary>{children}</QueryIdentityBoundary>
    </QueryClientProvider>
  );
}
