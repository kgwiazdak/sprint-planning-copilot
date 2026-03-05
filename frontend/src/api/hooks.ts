import {
    type QueryKey,
    type UseQueryOptions,
    useMutation,
    useQuery,
    useQueryClient,
} from '@tanstack/react-query';
import {apiClient} from './client';
import {queryKeys} from './queryKeys';
import type {JiraProject, Meeting, Task, User} from '../types';
import type {MeetingUpdateValues} from '../schemas/meeting';
import type {TaskUpdateValues} from '../schemas/task';

const fetchMeetings = async () => {
    const {data} = await apiClient.get<Meeting[]>('/meetings');
    return data;
};

const fetchMeetingTasks = async (meetingId: string) => {
    const {data} = await apiClient.get<Task[]>(`/meetings/${meetingId}/tasks`);
    return data;
};

const fetchTask = async (id: string) => {
    const {data} = await apiClient.get<Task>(`/tasks/${id}`);
    return data;
};

const fetchReviewTasks = async () => {
    const {data} = await apiClient.get<Task[]>('/tasks', {
        params: {status: 'draft'},
    });
    return data;
};

const fetchUsers = async () => {
    const {data} = await apiClient.get<User[]>('/users');
    return data;
};

const fetchJiraProjects = async () => {
    const {data} = await apiClient.get<JiraProject[]>('/jira/projects');
    return data;
};

export const useMeetings = () =>
    useQuery<Meeting[]>({
        queryKey: queryKeys.meetings(),
        queryFn: fetchMeetings,
        staleTime: 0,
        refetchOnMount: 'always',
        refetchOnReconnect: 'always',
        refetchOnWindowFocus: true,
    });

export const useMeeting = (id: string) =>
    useQuery<Meeting>({
        queryKey: queryKeys.meeting(id),
        queryFn: () => apiClient.get<Meeting>(`/meetings/${id}`).then((res) => res.data),
        enabled: Boolean(id),
        // Poll while the meeting is in flight; stop after completion/failure.
        refetchInterval: (query) => {
            const meeting = query.state.data as Meeting | undefined;
            return meeting && ['queued', 'processing'].includes(meeting.status) ? 2000 : false;
        },
        refetchIntervalInBackground: true,
        refetchOnWindowFocus: true,
    });

export const useMeetingTasks = (
    meetingId: string,
    options?: Pick<UseQueryOptions<Task[]>, 'refetchInterval' | 'refetchIntervalInBackground'>,
) =>
    useQuery<Task[]>({
        queryKey: queryKeys.tasks(meetingId),
        queryFn: () => fetchMeetingTasks(meetingId),
        enabled: Boolean(meetingId),
        ...options,
    });

export const useTask = (taskId: string) =>
    useQuery<Task>({
        queryKey: queryKeys.task(taskId),
        queryFn: () => fetchTask(taskId),
        enabled: Boolean(taskId),
    });

export const useReviewTasks = () =>
    useQuery<Task[]>({
        queryKey: queryKeys.reviewTasks(),
        queryFn: fetchReviewTasks,
    });

export const useUsers = () =>
    useQuery<User[]>({
        queryKey: queryKeys.users(),
        queryFn: fetchUsers,
    });

export const useJiraProjects = () =>
    useQuery<JiraProject[]>({
        queryKey: queryKeys.jiraProjects(),
        queryFn: fetchJiraProjects,
    });

type UploadVoiceInput = {
    file: File;
    displayName: string;
    userId?: string;
};

export const useUploadVoiceSample = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: async ({file, displayName, userId}: UploadVoiceInput) => {
            const data = new FormData();
            data.append('displayName', displayName);
            if (userId) {
                data.append('userId', userId);
            }
            data.append('file', file);
            const response = await apiClient.post('/users/voice', data);
            return response.data;
        },
        onSuccess: () => {
            queryClient.invalidateQueries({queryKey: queryKeys.users()});
        },
    });
};

type CreateMeetingInput = {
    title: string;
    startedAt: string;
    projectKey: string;
    file: File;
};

type BlobUploadTicket = {
    uploadUrl: string;
    blobUrl: string;
    blobPath: string;
    expiresAt: string;
    meetingId: string;
};

type LocalUploadTicket = {
    blobUrl: string;
    blobPath: string;
    meetingId: string;
};

type RuntimeConfig = {
    ingestBackend: 'azure' | 'local';
};

type MeetingImportResponse = {
    meetingId: string;
    status: 'queued';
};

const RUNTIME_CONFIG_TTL_MS = 60_000;

let runtimeConfigPromise: Promise<RuntimeConfig> | null = null;
let runtimeConfigFetchedAt = 0;

const isRuntimeConfig = (value: unknown): value is RuntimeConfig => {
    if (!value || typeof value !== 'object') {
        return false;
    }
    const ingestBackend = (value as {ingestBackend?: unknown}).ingestBackend;
    return ingestBackend === 'azure' || ingestBackend === 'local';
};

const resetRuntimeConfigCache = () => {
    runtimeConfigPromise = null;
    runtimeConfigFetchedAt = 0;
};

const getRuntimeConfig = async (): Promise<RuntimeConfig> => {
    const now = Date.now();
    if (!runtimeConfigPromise || now - runtimeConfigFetchedAt > RUNTIME_CONFIG_TTL_MS) {
        runtimeConfigPromise = apiClient
            .get('/runtime/config')
            .then((res) => {
                const data = res.data;
                if (!isRuntimeConfig(data)) {
                    throw new Error('Invalid runtime configuration');
                }
                runtimeConfigFetchedAt = Date.now();
                return data;
            })
            .catch((error) => {
                resetRuntimeConfigCache();
                throw error;
            });
    }
    return runtimeConfigPromise;
};

const requestBlobUpload = async (file: File): Promise<BlobUploadTicket> => {
    const {data} = await apiClient.post<BlobUploadTicket>('/uploads/blob', {
        filename: file.name,
        contentType: file.type || 'application/octet-stream',
    });
    return data;
};

const uploadFileToLocal = async (file: File): Promise<LocalUploadTicket> => {
    const form = new FormData();
    form.append('file', file);
    const {data} = await apiClient.post<LocalUploadTicket>('/uploads/local', form);
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

const assertUploadMetadata = (input: {blobUrl?: string; meetingId?: string}) => {
    if (!input.blobUrl || !input.meetingId) {
        throw new Error('Upload response is missing blobUrl or meetingId');
    }
};

export const useCreateMeeting = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: async ({title, startedAt, projectKey, file}: CreateMeetingInput) => {
            if (!file) {
                throw new Error('No file provided');
            }
            let runtime: RuntimeConfig;
            try {
                runtime = await getRuntimeConfig();
            } catch {
                throw new Error('Unable to resolve ingest runtime configuration. Please refresh and try again.');
            }
            let blobUrl = '';
            let meetingId = '';
            if (runtime.ingestBackend === 'local') {
                const ticket = await uploadFileToLocal(file);
                assertUploadMetadata(ticket);
                blobUrl = ticket.blobUrl;
                meetingId = ticket.meetingId;
            } else {
                const ticket = await requestBlobUpload(file);
                assertUploadMetadata(ticket);
                await uploadFileToBlob(ticket.uploadUrl, file);
                blobUrl = ticket.blobUrl;
                meetingId = ticket.meetingId;
            }
            const {meetingId: queuedMeetingId} = await apiClient
                .post<MeetingImportResponse>('/meetings/import', {
                    title,
                    startedAt,
                    projectKey,
                    blobUrl,
                    originalFilename: file.name,
                    meetingId,
                })
                .then((res) => res.data);
            // Return meeting data for optimistic update
            return {
                id: queuedMeetingId || meetingId,
                title,
                startedAt,
                status: 'queued' as const,
                projectKey,
                draftTaskCount: 0,
            };
        },
        onMutate: async ({title, startedAt, projectKey}) => {
            // Cancel any outgoing refetches to prevent overwriting optimistic update
            await queryClient.cancelQueries({queryKey: queryKeys.meetings()});
            const previous = queryClient.getQueryData<Meeting[]>(queryKeys.meetings());
            // Optimistically add a placeholder meeting immediately
            const optimisticMeeting: Meeting = {
                id: `temp-${Date.now()}`,
                title,
                startedAt,
                status: 'queued',
                draftTaskCount: 0,
                projectKey,
            };
            queryClient.setQueryData<Meeting[]>(queryKeys.meetings(), (current = []) => [
                optimisticMeeting,
                ...current,
            ]);
            return {previous};
        },
        onError: (_error, _variables, context) => {
            // Rollback on error
            if (context?.previous) {
                queryClient.setQueryData(queryKeys.meetings(), context.previous);
            }
            resetRuntimeConfigCache();
        },
        onSettled: () => {
            // Always refetch after mutation settles to get real server state
            queryClient.invalidateQueries({queryKey: queryKeys.meetings()});
            // Also invalidate review tasks since a new meeting may create draft tasks
            queryClient.invalidateQueries({queryKey: queryKeys.reviewTasks()});
        },
    });
};

export const useDeleteMeeting = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: (id: string) => apiClient.delete(`/meetings/${id}`),
        onMutate: async (id) => {
            await queryClient.cancelQueries({queryKey: queryKeys.meetings()});
            const previous = queryClient.getQueryData<Meeting[]>(queryKeys.meetings());
            queryClient.setQueryData<Meeting[]>(queryKeys.meetings(), (current = []) =>
                current.filter((meeting) => meeting.id !== id),
            );
            return {previous};
        },
        onError: (_error, _id, context) => {
            if (context?.previous) {
                queryClient.setQueryData(queryKeys.meetings(), context.previous);
            }
        },
        onSettled: () => {
            queryClient.invalidateQueries({queryKey: queryKeys.meetings()});
            // Also invalidate review tasks since deleting a meeting removes its tasks
            queryClient.invalidateQueries({queryKey: queryKeys.reviewTasks()});
            // Invalidate all task lists
            queryClient.invalidateQueries({queryKey: ['tasks']});
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
        mutationFn: ({id, data}: UpdateMeetingInput) =>
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
        tasks.map((task) => (task.id === updated.id ? {...task, ...updated} : task)),
    );
    queryClient.setQueryData<Task[]>(
        queryKeys.tasks(updated.meetingId),
        (tasks = []) =>
            tasks.map((task) =>
                task.id === updated.id ? {...task, ...updated} : task,
            ),
    );
    queryClient.setQueryData<Task>(queryKeys.task(updated.id), (task) =>
        task ? {...task, ...updated} : updated,
    );
};

export const useUpdateTask = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: ({id, data}: UpdateTaskInput) =>
            apiClient.patch<Task>(`/tasks/${id}`, data).then((res) => res.data),
        onMutate: async ({id, data}) => {
            const snapshot: TaskCacheSnapshot = {lists: []};
            await Promise.all([
                queryClient.cancelQueries({queryKey: queryKeys.reviewTasks()}),
                queryClient.cancelQueries({queryKey: ['tasks']}),
                queryClient.cancelQueries({queryKey: ['task', id]}),
            ]);

            snapshot.review = queryClient.getQueryData<Task[]>(queryKeys.reviewTasks());
            queryClient.setQueryData<Task[]>(queryKeys.reviewTasks(), (tasks = []) =>
                tasks.map((task) =>
                    task.id === id ? {...task, ...data, id: task.id} : task,
                ),
            );

            const taskQueries = queryClient.getQueriesData<Task[]>({
                queryKey: ['tasks'],
            });
            taskQueries.forEach(([key, value]) => {
                snapshot.lists.push({key, data: value});
                queryClient.setQueryData<Task[]>(key, (tasks = []) =>
                    tasks.map((task) =>
                        task.id === id ? {...task, ...data, id: task.id} : task,
                    ),
                );
            });

            snapshot.single = queryClient.getQueryData<Task>(queryKeys.task(id));
            if (snapshot.single) {
                queryClient.setQueryData<Task>(queryKeys.task(id), (task) =>
                    task ? {...task, ...data} : task,
                );
            }

            return snapshot;
        },
        onError: (_error, _variables, snapshot) => {
            if (!snapshot) return;
            if (snapshot.review) {
                queryClient.setQueryData(queryKeys.reviewTasks(), snapshot.review);
            }
            snapshot.lists.forEach(({key, data}) => {
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
            queryClient.invalidateQueries({queryKey: queryKeys.reviewTasks()});
            queryClient.invalidateQueries({queryKey: ['tasks']});
            if (variables?.id) {
                queryClient.invalidateQueries({queryKey: queryKeys.task(variables.id)});
            }
        },
    });
};

type BulkInput = { ids: string[] };
type BulkApproveInput = BulkInput & { projectKey: string };

const mutateTaskStatus = (
    tasks: Task[] | undefined,
    ids: string[],
    status: Task['status'],
) =>
    tasks?.map((task) =>
        ids.includes(task.id) ? {...task, status} : task,
    ) ?? tasks;

const useBulkTaskMutation = <T extends BulkInput>(
    status: Task['status'],
    url: string,
    buildPayload?: (input: T) => Record<string, unknown>,
) => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: (input: T) =>
            apiClient.post(url, buildPayload ? buildPayload(input) : {ids: input.ids}).then((res) => res.data),
        onMutate: async ({ids}: T) => {
            await Promise.all([
                queryClient.cancelQueries({queryKey: queryKeys.reviewTasks()}),
                queryClient.cancelQueries({queryKey: ['tasks']}),
            ]);
            const snapshot: TaskCacheSnapshot = {lists: []};
            snapshot.review = queryClient.getQueryData(queryKeys.reviewTasks());
            queryClient.setQueryData(queryKeys.reviewTasks(), (tasks: Task[] = []) =>
                mutateTaskStatus(tasks, ids, status),
            );
            const taskQueries = queryClient.getQueriesData<Task[]>({
                queryKey: ['tasks'],
            });
            taskQueries.forEach(([key, data]) => {
                snapshot.lists.push({key, data});
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
            snapshot.lists.forEach(({key, data}) => {
                queryClient.setQueryData(key, data);
            });
        },
        onSettled: () => {
            queryClient.invalidateQueries({queryKey: queryKeys.reviewTasks()});
            queryClient.invalidateQueries({queryKey: ['tasks']});
            // Also invalidate meetings since draft task count may have changed
            queryClient.invalidateQueries({queryKey: queryKeys.meetings()});
        },
    });
};

export const useApproveTasks = () =>
    useBulkTaskMutation<BulkApproveInput>('approved', '/tasks/bulk-approve', (input) => ({
        ids: input.ids,
        projectKey: input.projectKey,
    }));

export const useRejectTasks = () =>
    useBulkTaskMutation('rejected', '/tasks/bulk-reject');
