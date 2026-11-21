// Shared wrapper for project quality requests: loading flag on, error cleared, failure shown with a fallback text.
type ProjectQualityLoadingSetters = {
  setProjectQualityLoading: (loading: boolean) => void;
  setProjectQualityError: (error: string | null) => void;
};

export async function withProjectQualityLoading(
  s: ProjectQualityLoadingSetters,
  fallback: string,
  work: () => Promise<void>,
) {
  s.setProjectQualityLoading(true);
  s.setProjectQualityError(null);
  try {
    await work();
  } catch (error) {
    s.setProjectQualityError(error instanceof Error ? error.message : fallback);
  } finally {
    s.setProjectQualityLoading(false);
  }
}
