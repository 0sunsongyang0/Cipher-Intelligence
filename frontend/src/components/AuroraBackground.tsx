type AuroraBackgroundProps = {
  testId?: string;
};

export function AuroraBackground({ testId }: AuroraBackgroundProps) {
  return (
    <div
      className="aurora-background"
      data-testid={testId}
      aria-hidden="true"
    >
      <span className="aurora-glow aurora-glow--left" />
      <span className="aurora-glow aurora-glow--right" />
      <span className="aurora-vignette" />
    </div>
  );
}
