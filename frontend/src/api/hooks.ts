import {
  type QueryKey,
  useMutation,
  useQuery,
  useQueryClient,
} from '@tanstack/react-query';
import { apiClient } from './client';
import { queryKeys } from './queryKeys';
import type { Meeting, Task, User } from '../types';
import type { MeetingUpdateValues } from '../schemas/meeting';
import type { TaskUpdateValues } from '../schemas/task';

const fetchMeetings = async () => {
  const { data } = await apiClient.get<Meeting[]>('/meetings');
  return data;
};

const fetchMeetingTasks = async (meetingId: string) => {
  const { data } = await apiClient.get<Task[]>(`/meetings/${meetingId}/tasks`);
  return data;
};

const fetchTask = async (id: string) => {
  const { data } = await apiClient.get<Task>(`/tasks/${id}`);
  return data;
};

const fetchReviewTasks = async () => {
  const { data } = await apiClient.get<Task[]>('/tasks', {
    params: { status: 'draft' },
  });
  return data;
};

const fetchUsers = async () => {
  const { data } = await apiClient.get<User[]>('/users');
  return data;
};

export const useMeetings = () =>
  useQuery({
    queryKey: queryKeys.meetings(),
    queryFn: fetchMeetings,
  });

export const useMeeting = (id: string) =>
  useQuery({
    queryKey: queryKeys.meeting(id),
    queryFn: () => apiClient.get<Meeting>(`/meetings/${id}`).then((res) => res.data),
    enabled: Boolean(id),
  });

export const useMeetingTasks = (meetingId: string) =>
  useQuery({
    queryKey: queryKeys.tasks(meetingId),
    queryFn: () => fetchMeetingTasks(meetingId),
    enabled: Boolean(meetingId),
  });

export const useTask = (taskId: string) =>
  useQuery({
    queryKey: queryKeys.task(taskId),
    queryFn: () => fetchTask(taskId),
    enabled: Boolean(taskId),
  });

export const useReviewTasks = () =>
  useQuery({
    queryKey: queryKeys.reviewTasks(),
    queryFn: fetchReviewTasks,
  });

export const useUsers = () =>
  useQuery({
    queryKey: queryKeys.users(),
    queryFn: fetchUsers,
  });

type CreateMeetingInput = {
  title: string;
  startedAt: string;
  file: File;
};

type BlobUploadTicket = {
  uploadUrl: string;
  blobUrl: string;
  blobPath: string;
  expiresAt: string;
  meetingId: string;
};

const requestBlobUpload = async (file: File): Promise<BlobUploadTicket> => {
  const { data } = await apiClient.post<BlobUploadTicket>('/uploads/blob', {
    filename: file.name,
    contentType: file.type || 'application/octet-stream',
  });
  return data;
};

const uploadFileToBlob = async (uploadUrl: string, file: File) => {
  const response = await fetch(uploadUrl, {
    method: 'PUT',
    headers: {
      'x-ms-blob-type': 'BlockBlob',
      'Content-Type': file.type || 'application/octet-stream',
    },
    body: file,
  });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || 'Failed to upload file to storage');
  }
};

export const useCreateMeeting = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async ({ title, startedAt, file }: CreateMeetingInput) => {
      if (!file) {
        throw new Error('No file provided');
      }
      const ticket = await requestBlobUpload(file);
      await uploadFileToBlob(ticket.uploadUrl, file);
      await apiClient.post('/meetings/import', {
        title,
        startedAt,
        blobUrl: ticket.blobUrl,
        originalFilename: file.name,
        meetingId: ticket.meetingId,
      });
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.meetings() });
    },
  });
};

export const useDeleteMeeting = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => apiClient.delete(`/meetings/${id}`),
    onMutate: async (id) => {
      await queryClient.cancelQueries({ queryKey: queryKeys.meetings() });
      const previous = queryClient.getQueryData<Meeting[]>(queryKeys.meetings());
      queryClient.setQueryData<Meeting[]>(queryKeys.meetings(), (current = []) =>
        current.filter((meeting) => meeting.id !== id),
      );
      return { previous };
    },
    onError: (_error, _id, context) => {
      if (context?.previous) {
        queryClient.setQueryData(queryKeys.meetings(), context.previous);
      }
    },
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.meetings() });
    },
  });
};

type UpdateMeetingInput = {
  id: string;
  data: Partial<MeetingUpdateValues>;
};

export const useUpdateMeeting = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, data }: UpdateMeetingInput) =>
      apiClient
        .patch<Meeting>(`/meetings/${id}`, data)
        .then((res) => res.data),
    onSuccess: (meeting) => {
      queryClient.setQueryData<Meeting[]>(queryKeys.meetings(), (prev = []) =>
        prev.map((item) => (item.id === meeting.id ? meeting : item)),
      );
      queryClient.setQueryData(queryKeys.meeting(meeting.id), meeting);
    },
  });
};

type UpdateTaskInput = {
  id: string;
  data: Partial<TaskUpdateValues>;
};

type TaskCacheSnapshot = {
  review?: Task[];
  lists: Array<{ key: QueryKey; data?: Task[] }>;
  single?: Task;
};

const updateTaskCollections = (
  queryClient: ReturnType<typeof useQueryClient>,
  updated: Task,
) => {
  queryClient.setQueryData<Task[]>(queryKeys.reviewTasks(), (tasks = []) =>
    tasks.map((task) => (task.id === updated.id ? { ...task, ...updated } : task)),
  );
  queryClient.setQueryData<Task[]>(
    queryKeys.tasks(updated.meetingId),
    (tasks = []) =>
      tasks.map((task) =>
        task.id === updated.id ? { ...task, ...updated } : task,
      ),
  );
  queryClient.setQueryData<Task>(queryKeys.task(updated.id), (task) =>
    task ? { ...task, ...updated } : updated,
  );
};

export const useUpdateTask = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, data }: UpdateTaskInput) =>
      apiClient.patch<Task>(`/tasks/${id}`, data).then((res) => res.data),
    onMutate: async ({ id, data }) => {
      const snapshot: TaskCacheSnapshot = { lists: [] };
      await Promise.all([
        queryClient.cancelQueries({ queryKey: queryKeys.reviewTasks() }),
        queryClient.cancelQueries({ queryKey: ['tasks'] }),
        queryClient.cancelQueries({ queryKey: ['task', id] }),
      ]);

      snapshot.review = queryClient.getQueryData<Task[]>(queryKeys.reviewTasks());
      queryClient.setQueryData<Task[]>(queryKeys.reviewTasks(), (tasks = []) =>
        tasks.map((task) =>
          task.id === id ? { ...task, ...data, id: task.id } : task,
        ),
      );

      const taskQueries = queryClient.getQueriesData<Task[]>({
        queryKey: ['tasks'],
      });
      taskQueries.forEach(([key, value]) => {
        snapshot.lists.push({ key, data: value });
        queryClient.setQueryData<Task[]>(key, (tasks = []) =>
          tasks.map((task) =>
            task.id === id ? { ...task, ...data, id: task.id } : task,
          ),
        );
      });

      snapshot.single = queryClient.getQueryData<Task>(queryKeys.task(id));
      if (snapshot.single) {
        queryClient.setQueryData<Task>(queryKeys.task(id), (task) =>
          task ? { ...task, ...data } : task,
        );
      }

      return snapshot;
    },
    onError: (_error, _variables, snapshot) => {
      if (!snapshot) return;
      if (snapshot.review) {
        queryClient.setQueryData(queryKeys.reviewTasks(), snapshot.review);
      }
      snapshot.lists.forEach(({ key, data }) => {
        queryClient.setQueryData(key, data);
      });
      if (snapshot.single) {
        queryClient.setQueryData(
          queryKeys.task(snapshot.single.id),
          snapshot.single,
        );
      }
    },
    onSuccess: (task) => {
      updateTaskCollections(queryClient, task);
    },
    onSettled: (_data, _error, variables) => {
      queryClient.invalidateQueries({ queryKey: queryKeys.reviewTasks() });
      queryClient.invalidateQueries({ queryKey: ['tasks'] });
      if (variables?.id) {
        queryClient.invalidateQueries({ queryKey: queryKeys.task(variables.id) });
      }
    },
  });
};

type BulkInput = { ids: string[] };

const mutateTaskStatus = (
  tasks: Task[] | undefined,
  ids: string[],
  status: Task['status'],
) =>
  tasks?.map((task) =>
    ids.includes(task.id) ? { ...task, status } : task,
  ) ?? tasks;

const useBulkTaskMutation = (status: Task['status'], url: string) => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ ids }: BulkInput) =>
      apiClient.post(url, { ids }).then((res) => res.data),
    onMutate: async ({ ids }) => {
      await Promise.all([
        queryClient.cancelQueries({ queryKey: queryKeys.reviewTasks() }),
        queryClient.cancelQueries({ queryKey: ['tasks'] }),
      ]);
      const snapshot: TaskCacheSnapshot = { lists: [] };
      snapshot.review = queryClient.getQueryData(queryKeys.reviewTasks());
      queryClient.setQueryData(queryKeys.reviewTasks(), (tasks: Task[] = []) =>
        mutateTaskStatus(tasks, ids, status),
      );
      const taskQueries = queryClient.getQueriesData<Task[]>({
        queryKey: ['tasks'],
      });
      taskQueries.forEach(([key, data]) => {
        snapshot.lists.push({ key, data });
        queryClient.setQueryData(key, (tasks: Task[] = []) =>
          mutateTaskStatus(tasks, ids, status),
        );
      });
      ids.forEach((id) => {
        const task = queryClient.getQueryData<Task>(queryKeys.task(id));
        if (task) {
          queryClient.setQueryData(queryKeys.task(id), {
            ...task,
            status,
          });
        }
      });
      return snapshot;
    },
    onError: (_error, _variables, snapshot) => {
      if (!snapshot) return;
      if (snapshot.review) {
        queryClient.setQueryData(queryKeys.reviewTasks(), snapshot.review);
      }
      snapshot.lists.forEach(({ key, data }) => {
        queryClient.setQueryData(key, data);
      });
    },
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.reviewTasks() });
      queryClient.invalidateQueries({ queryKey: ['tasks'] });
    },
  });
};

export const useApproveTasks = () =>
  useBulkTaskMutation('approved', '/tasks/bulk-approve');

export const useRejectTasks = () =>
  useBulkTaskMutation('rejected', '/tasks/bulk-reject');
