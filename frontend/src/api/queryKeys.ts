export const queryKeys = {
  meetings: () => ['meetings'] as const,
  meeting: (id: string) => ['meeting', id] as const,
  tasks: (meetingId: string) => ['tasks', meetingId] as const,
  reviewTasks: () => ['reviewTasks'] as const,
  task: (id: string) => ['task', id] as const,
  users: () => ['users'] as const,
};
