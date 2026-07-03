import type { PropsWithChildren } from "react";
import { Navigate } from "react-router-dom";

type AuthGuardProps = PropsWithChildren<{
  authenticated: boolean;
}>;

export function AuthGuard({ authenticated, children }: AuthGuardProps) {
  if (!authenticated) {
    return <Navigate to="/" replace />;
  }

  return <>{children}</>;
}
