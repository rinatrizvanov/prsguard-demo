"use client";

import { Component, type ErrorInfo, type ReactNode } from "react";

/**
 * Keeps one malformed section (e.g. an unexpected shape from a newer local server) from blanking the whole result.
 * It never substitutes values: the section is replaced by an explicit notice.
 */
export class SectionBoundary extends Component<{ name: string; children: ReactNode }, { error: string | null }> {
  override state: { error: string | null } = { error: null };

  static getDerivedStateFromError(error: unknown): { error: string } {
    return { error: error instanceof Error ? error.message : String(error) };
  }

  override componentDidCatch(error: unknown, info: ErrorInfo): void {
    console.error(`PRSGuard: section "${this.props.name}" failed to render`, error, info.componentStack);
  }

  override render(): ReactNode {
    if (this.state.error) {
      return (
        <div className="error-box" role="alert">
          The <strong>{this.props.name}</strong> section could not be displayed for this result ({this.state.error}).
          Other sections are unaffected; nothing has been estimated in its place.
        </div>
      );
    }
    return this.props.children;
  }
}
