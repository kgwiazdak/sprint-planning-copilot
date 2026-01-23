import {useEffect, useMemo, useState, type ReactNode} from 'react';
import {Alert, Box, Button, Chip, MenuItem, Paper, Stack, TextField, Typography} from '@mui/material';
import {useNavigate, useParams} from 'react-router-dom';
import {useSnackbar} from 'notistack';
import {useApproveTasks, useJiraProjects, useMeeting, useMeetingTasks, useRejectTasks, useUpdateMeeting, useUsers,} from '../../api/hooks';
import {TasksTable} from './TasksTable';
import {DataGridToolbar} from '../../components/DataGridToolbar';
import {TaskDrawer} from '../../components/TaskDrawer';
import type {MeetingStatus, TaskStatus} from '../../types';
import {PageHeader} from '../../components/PageHeader';
import {formatDateTime} from '../../utils/format';

type StatusFilter = TaskStatus | 'all';

type MetadataItemProps = {
    label: string;
    value: ReactNode;
};

const MetadataItem = ({label, value}: MetadataItemProps) => (
    <Stack
        direction="row"
        spacing={0.75}
        alignItems="center"
        minWidth={{xs: '100%', md: 200}}
        flexShrink={0}
    >
        <Typography
            variant="overline"
            color="text.secondary"
            sx={{lineHeight: 1.4, whiteSpace: 'nowrap'}}
        >
            {label}
        </Typography>
        {typeof value === 'string' || typeof value === 'number' ? (
            <Typography variant="body2" fontWeight={600}>
                {value}
            </Typography>
        ) : (
            value
        )}
    </Stack>
);

export const MeetingTasksPage = () => {
    const {id = ''} = useParams();
    const {data: meeting} = useMeeting(id);
    const meetingStatus = meeting?.status;
    const {
        data: tasks = [],
        isLoading,
        isError,
        refetch,
        isFetching,
    } = useMeetingTasks(id, {
        refetchInterval:
            meetingStatus && ['queued', 'processing'].includes(meetingStatus) ? 2000 : false,
        refetchIntervalInBackground: true,
    });
    const {data: users = []} = useUsers();
    const {data: projects = [], isLoading: projectsLoading, isError: projectsError} = useJiraProjects();
    const projectOptions = useMemo(
        () => {
            const options = projects.map((project) => ({
                value: project.key,
                label: `${project.name} (${project.key})`,
            }));
            if (meeting?.projectKey && !options.some((option) => option.value === meeting.projectKey)) {
                options.unshift({
                    value: meeting.projectKey,
                    label: `${meeting.projectKey} (current)`,
                });
            }
            return options;
        },
        [projects, meeting?.projectKey],
    );
    const approveTasks = useApproveTasks();
    const rejectTasks = useRejectTasks();
    const updateMeeting = useUpdateMeeting();
    const navigate = useNavigate();
    const {enqueueSnackbar} = useSnackbar();
    const [selectedIds, setSelectedIds] = useState<string[]>([]);
    const [statusFilter, setStatusFilter] = useState<StatusFilter>('all');
    const [search, setSearch] = useState('');
    const [drawerTaskId, setDrawerTaskId] = useState<string | null>(null);
    useEffect(() => {
        if (meeting?.projectKey && meeting.projectKey !== selectedProjectKey) {
            setSelectedProjectKey(meeting.projectKey);
            return;
        }
        if (!selectedProjectKey && projectOptions.length) {
            setSelectedProjectKey(projectOptions[0].value);
        }
    }, [meeting?.projectKey, projectOptions, selectedProjectKey]);
    const [selectedProjectKey, setSelectedProjectKey] = useState<string>('');

    const filteredTasks = useMemo(
        () =>
            tasks
                .filter((task) =>
                    statusFilter === 'all' ? true : task.status === statusFilter,
                )
                .filter((task) =>
                    task.summary.toLowerCase().includes(search.toLowerCase()),
                ),
        [tasks, statusFilter, search],
    );

    const handleProjectChange = async (value: string) => {
        setSelectedProjectKey(value);
        if (!meeting || !value || meeting.projectKey === value) {
            return;
        }
        try {
            await updateMeeting.mutateAsync({
                id: meeting.id,
                data: {projectKey: value},
            });
        } catch (error) {
            enqueueSnackbar((error as Error).message, {variant: 'error'});
        }
    };

    if (!id) {
        return <Alert severity="warning">Meeting not found.</Alert>;
    }

    const baseActionDisabled =
        approveTasks.isPending ||
        rejectTasks.isPending ||
        isLoading ||
        isFetching;
    const selectionDisabled = baseActionDisabled || selectedIds.length === 0;
    const targetProjectKey = selectedProjectKey || '';
    const approveDisabled =
        selectionDisabled || !targetProjectKey;

    const handleApprove = async (ids: string[], message: string) => {
        if (!ids.length) return;
        if (!targetProjectKey) {
            enqueueSnackbar('This meeting has no target Jira project; set one before pushing tasks.', {
                variant: 'warning',
            });
            return;
        }
        try {
            await approveTasks.mutateAsync({ids, projectKey: targetProjectKey});
            enqueueSnackbar(message, {variant: 'success'});
            setSelectedIds([]);
        } catch (error) {
            enqueueSnackbar((error as Error).message, {variant: 'error'});
        }
    };

    const handleReject = async (ids: string[], message: string) => {
        if (!ids.length) return;
        try {
            await rejectTasks.mutateAsync({ids});
            enqueueSnackbar(message, {variant: 'success'});
            setSelectedIds([]);
        } catch (error) {
            enqueueSnackbar((error as Error).message, {variant: 'error'});
        }
    };

    if (isError) {
        return (
            <Alert
                severity="error"
                action={
                    <Button color="inherit" size="small" onClick={() => refetch()}>
                        Retry
                    </Button>
                }
            >
                Failed to load meeting tasks.
            </Alert>
        );
    }

    const getStatusColor = (status: MeetingStatus) => {
        switch (status) {
            case 'completed':
                return 'success';
            case 'processing':
                return 'info';
            case 'failed':
                return 'error';
            default:
                return 'default';
        }
    };

    return (
        <Box
            sx={{
                display: 'flex',
                flexDirection: 'column',
                height: '100%',
                minHeight: 0,
                overflow: 'hidden',
            }}
        >
            <Paper
                sx={{
                    p: {xs: 1.25, md: 1.5},
                    mb: 1.25,
                    borderRadius: 2.25,
                }}
            >
                <Stack spacing={meeting ? 1.25 : 1}>
                    <PageHeader
                        eyebrow="Meeting review"
                        title={meeting ? meeting.title : 'Meeting tasks'}
                        subtitle={
                            meeting
                                ? undefined
                                : 'Review extracted tasks for the selected meeting.'
                        }
                        actions={
                            <Button variant="text" onClick={() => navigate('/meetings')}>
                                Back to meetings
                            </Button>
                        }
                    />
                    {meeting && (
                        <Stack
                            direction={{xs: 'column', md: 'row'}}
                            spacing={{xs: 1.5, md: 3}}
                            useFlexGap
                            flexWrap="wrap"
                            alignItems="center"
                        >
                            <MetadataItem label="Meeting ID" value={meeting.id}/>
                            <MetadataItem
                                label="Started at"
                                value={formatDateTime(meeting.startedAt)}
                            />
                            <MetadataItem
                                label="Status"
                                value={<Chip label={meeting.status} color={getStatusColor(meeting.status)} size="small"/>}
                            />
                            <MetadataItem
                                label="Draft tasks"
                                value={
                                    <Typography variant="h6" fontWeight={700}>
                                        {meeting.draftTaskCount ?? 0}
                                    </Typography>
                                }
                            />
                            <MetadataItem
                                label="Target project"
                                value={
                                    <TextField
                                        select
                                        size="small"
                                        value={selectedProjectKey}
                                        onChange={(event) => handleProjectChange(event.target.value)}
                                        disabled={projectsLoading || projectOptions.length === 0}
                                        error={projectsError}
                                        helperText={
                                            projectsError
                                                ? 'Failed to load Jira projects'
                                                : projectOptions.length === 0
                                                    ? 'No Jira projects available'
                                                    : 'Used when pushing tasks to Jira'
                                        }
                                        sx={{minWidth: 240}}
                                    >
                                        {projectOptions.map((option) => (
                                            <MenuItem key={option.value} value={option.value}>
                                                {option.label}
                                            </MenuItem>
                                        ))}
                                    </TextField>
                                }
                            />
                        </Stack>
                    )}
                </Stack>
            </Paper>
            <Paper
                sx={{
                    p: {xs: 1, md: 1.5},
                    borderRadius: 2.5,
                    flexGrow: 1,
                    minHeight: 0,
                    display: 'flex',
                    flexDirection: 'column',
                    overflow: 'hidden',
                }}
            >
                <DataGridToolbar
                    variant="inline"
                    title="Selection"
                    selectionCount={selectedIds.length}
                    onApproveSelected={() =>
                        handleApprove(selectedIds, 'Tasks approved')
                    }
                    onRejectSelected={() =>
                        handleReject(selectedIds, 'Tasks rejected')
                    }
                    disableActions={selectionDisabled}
                    disableApprove={approveDisabled}
                    disableReject={selectionDisabled}
                    statusFilter={statusFilter}
                    onStatusFilterChange={setStatusFilter}
                    search={search}
                    onSearchChange={setSearch}
                />
                <Box
                    sx={{
                        flexGrow: 1,
                        minHeight: 0,
                    }}
                >
                    <TasksTable
                        tasks={filteredTasks}
                        users={users}
                        loading={isLoading || isFetching}
                        selectedIds={selectedIds}
                        onSelectionChange={setSelectedIds}
                        onRowDoubleClick={(task) => setDrawerTaskId(task.id)}
                    />
                </Box>
            </Paper>
            <TaskDrawer
                open={Boolean(drawerTaskId)}
                taskId={drawerTaskId}
                onClose={() => setDrawerTaskId(null)}
            />
        </Box>
    );
};
