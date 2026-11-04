import { clerkMiddleware, createRouteMatcher } from '@clerk/nextjs/server';
import { NextResponse } from 'next/server';

const isProtectedRoute = createRouteMatcher(['/dashboard(.*)', '/api/assignments(.*)']);

const handler = clerkMiddleware(async (auth, req) => {
  if (isProtectedRoute(req)) {
    // If a manual auth session cookie is present, allow access to dashboard
    const manualToken = req.cookies.get('uniflow_manual_token')?.value;
    if (manualToken) {
      return NextResponse.next();
    }
    const signInUrl = new URL('/sign-in', req.url).toString();
    await auth.protect({
      unauthenticatedUrl: signInUrl,
    });
  }
});

export const proxy = handler;
export default handler;

export const config = {
  matcher: ['/dashboard(.*)', '/api/assignments(.*)'],
};
