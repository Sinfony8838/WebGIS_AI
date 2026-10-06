type ProjectIdentity = { project_id: string };

type ProjectRecoveryAccess<T extends ProjectIdentity> = {
  read: (projectId: string) => Promise<T>;
  create: () => Promise<T>;
  remember: (projectId: string) => void;
  isCurrent: () => boolean;
};

/** A failed read is an error, never permission to create a replacement project. */
export async function restoreClassroomProject<T extends ProjectIdentity>(
  storedProjectId: string,
  access: ProjectRecoveryAccess<T>
): Promise<{ project: T; restored: boolean } | null> {
  if (!access.isCurrent()) return null;
  const restored = Boolean(storedProjectId);
  const project = restored ? await access.read(storedProjectId) : await access.create();
  if (!access.isCurrent()) return null;
  if (!restored) access.remember(project.project_id);
  return { project, restored };
}
