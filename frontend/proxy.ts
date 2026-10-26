import { clerkMiddleware, createRouteMatcher } from '@clerk/nextjs/server';

const isProtectedRoute = createRouteMatcher(['/dashboard(.*)', '/api/assignments(.*)']);

export default clerkMiddleware(async (auth, req) => {
  if (isProtectedRoute(req)) {
    // If a manual auth session cookie is present, allow access to dashboard
    const manualToken = req.cookies.get('uniflow_manual_token')?.value;
    if (manualToken) {
      return;
    }
    await auth.protect();
  }
});

export const config = {
  matcher: ['/dashboard(.*)', '/api/assignments(.*)'],
};

