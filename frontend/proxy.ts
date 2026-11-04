import { clerkMiddleware, createRouteMatcher } from '@clerk/nextjs/server';
import { NextResponse } from 'next/server';

const isProtectedRoute = createRouteMatcher(['/dashboard(.*)', '/api/assignments(.*)']);

const clerkHandler = clerkMiddleware(async (auth, req) => {
  if (isProtectedRoute(req)) {
    const signInUrl = new URL('/sign-in', req.url).toString();
    await auth.protect({
      unauthenticatedUrl: signInUrl,
    });
  }
});

export default function proxy(req, event) {
  if (req.cookies.get('uniflow_manual_token')?.value) {
    return NextResponse.next();
  }
  return clerkHandler(req, event);
}

export const config = {
  matcher: ['/dashboard(.*)', '/api/assignments(.*)'],
};
