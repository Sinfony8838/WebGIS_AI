/** Confirmation jobs share the submission lock and scope fence with ordinary turns. */
export async function submitAssistantConfirmation(options: {
  blocked: () => boolean;
  setSubmitting: (value: boolean) => void;
  request: () => Promise<{ job_id: string }>;
  isCurrent: () => boolean;
  cancelStale: (jobId: string) => Promise<unknown>;
  accept: (jobId: string) => void;
}): Promise<boolean> {
  if (options.blocked()) return false;
  options.setSubmitting(true);
  try {
    const response = await options.request();
    if (!options.isCurrent()) {
      await options.cancelStale(response.job_id);
      return false;
    }
    options.accept(response.job_id);
    return true;
  } finally {
    options.setSubmitting(false);
  }
}

/** A newer project timestamp alone cannot attest removal from the rendered map. */
export function removedLayersApplied(options: {
  removedIds?: string[];
  currentLayerIds: string[] | undefined;
  hasPlaneLayer: (id: string) => boolean;
  hasGlobeLayer: (id: string) => boolean | undefined;
}): boolean {
  if (!options.removedIds?.length) return true;
  return !!options.currentLayerIds && options.removedIds.every(id =>
    !options.currentLayerIds!.includes(id) && !options.hasPlaneLayer(id) && options.hasGlobeLayer(id) === false);
}
