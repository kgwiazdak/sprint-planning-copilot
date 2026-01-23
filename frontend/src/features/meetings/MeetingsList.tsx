import {useEffect, useMemo, useState} from 'react';
import {
    Alert,
    Box,
    Button,
    Chip,
    Dialog,
    DialogContent,
    DialogTitle,
    IconButton,
    Paper,
    Skeleton,
    Stack,
    Table,
    TableBody,
    TableCell,
    TableContainer,
    TableHead,
    TableRow,
    TextField,
    Typography,
    useMediaQuery,
    useTheme,
    MenuItem,
} from '@mui/material';
import DeleteIcon from '@mui/icons-material/DeleteOutline';
import EditIcon from '@mui/icons-material/EditOutlined';
import {OpenInNew} from '@mui/icons-material';
import {useNavigate} from 'react-router-dom';
import {Controller, useForm} from 'react-hook-form';
import {zodResolver} from '@hookform/resolvers/zod';
import {useSnackbar} from 'notistack';
import {useDeleteMeeting, useJiraProjects, useMeetings, useUpdateMeeting,} from '../../api/hooks';
import {ConfirmDialog} from '../../components/ConfirmDialog';
import type {MeetingUpdateValues} from '../../schemas/meeting';
import {MeetingUpdateSchema} from '../../schemas/meeting';
import type {Meeting, MeetingStatus} from '../../types';
import {formatDateTime, toDateTimeInput} from '../../utils/format';
import {PageHeader} from '../../components/PageHeader';

export const MeetingsList = () => {
    const navigate = useNavigate();
    const theme = useTheme();
    const isMobileView = useMediaQuery(theme.breakpoints.down('md'));
    const {
        data: meetings = [],
        isLoading,
        isError,
        refetch,
    } = useMeetings();
    const deleteMeeting = useDeleteMeeting();
    const updateMeeting = useUpdateMeeting();
    const {enqueueSnackbar} = useSnackbar();
    const [confirmTarget, setConfirmTarget] = useState<Meeting | null>(null);
    const [editingMeeting, setEditingMeeting] = useState<Meeting | null>(null);

    const handleDelete = async () => {
        if (!confirmTarget) return;
        try {
            await deleteMeeting.mutateAsync(confirmTarget.id);
            enqueueSnackbar('Meeting deleted', {variant: 'success'});
            setConfirmTarget(null);
        } catch (error) {
            enqueueSnackbar((error as Error).message, {variant: 'error'});
        }
    };

    const handleEditSubmit = async (values: MeetingUpdateValues) => {
        if (!editingMeeting) return;
        try {
            await updateMeeting.mutateAsync({
                id: editingMeeting.id,
                data: {
                    title: values.title,
                    startedAt: new Date(values.startedAt).toISOString(),
                    projectKey: values.projectKey,
                },
            });
            enqueueSnackbar('Meeting updated', {variant: 'success'});
            setEditingMeeting(null);
        } catch (error) {
            enqueueSnackbar((error as Error).message, {variant: 'error'});
        }
    };

    const getStatusColor = (status: MeetingStatus) => {
        switch (status) {
            case 'completed':
                return 'success';
            case 'processing':
                return 'info';
            case 'failed':
                return 'error';
            case 'queued':
            default:
                return 'default';
        }
    };

    const sortedMeetings = useMemo(
        () =>
            [...meetings].sort(
                (a, b) => new Date(b.startedAt).getTime() - new Date(a.startedAt).getTime(),
            ),
        [meetings],
    );

    const hasActiveMeeting = useMemo(
        () => meetings.some((meeting) => ['queued', 'processing'].includes(meeting.status)),
        [meetings],
    );

    useEffect(() => {
        if (!hasActiveMeeting) return;
        // Make sure the list keeps updating while imports run.
        void refetch({cancelRefetch: false});
        const intervalId = window.setInterval(() => {
            void refetch({cancelRefetch: false});
        }, 2000);
        return () => window.clearInterval(intervalId);
    }, [hasActiveMeeting, refetch]);

    const overviewStats = useMemo(() => {
        const active = meetings.filter((meeting) =>
            ['queued', 'processing'].includes(meeting.status),
        ).length;
        const done = meetings.filter((meeting) => meeting.status === 'completed').length;
        const failed = meetings.filter((meeting) => meeting.status === 'failed').length;
        const draftTasks = meetings.reduce(
            (total, meeting) => total + meeting.draftTaskCount,
            0,
        );
        const lastRun = sortedMeetings[0]?.startedAt;
        return {active, done, failed, draftTasks, lastRun};
    }, [meetings, sortedMeetings]);

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
                Unable to load meetings.
            </Alert>
        );
    }

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
            <PageHeader
                eyebrow="Meeting ingestion"
                title="Meetings"
                subtitle="Follow each import as it flows through blob storage, transcription, and task extraction."
                actions={
                    <Button variant="contained" onClick={() => navigate('/meetings/new')}>
                        New meeting
                    </Button>
                }
            />
            <Stack
                direction={{xs: 'column', md: 'row'}}
                spacing={1.5}
                flexWrap="wrap"
                mb={1}
                flexShrink={0}
            >
                {[
                    {
                        label: 'In flight',
                        value: overviewStats.active || '—',
                        helper: 'Queued or processing',
                    },
                    {
                        label: 'Completed',
                        value: overviewStats.done || '—',
                        helper: 'Ready for review',
                    },
                    {
                        label: 'Draft tasks',
                        value: overviewStats.draftTasks || '—',
                        helper: 'Awaiting approval',
                    },
                    {
                        label: 'Last import',
                        value: overviewStats.lastRun
                            ? formatDateTime(overviewStats.lastRun)
                            : '—',
                        helper: 'Most recent start time',
                    },
                ].map((stat) => (
                    <Paper
                        key={stat.label}
                        elevation={0}
                        sx={{
                            p: 1.5,
                            borderRadius: 2,
                            flex: {xs: '1 1 100%', md: '1 1 25%'},
                        }}
                    >
                        <Typography variant="overline" color="text.secondary" sx={{fontSize: '0.65rem'}}>
                            {stat.label}
                        </Typography>
                        <Typography variant="h6" fontWeight={700} sx={{mt: 0.5}}>
                            {stat.value}
                        </Typography>
                        <Typography variant="caption" color="text.secondary">
                            {stat.helper}
                        </Typography>
                    </Paper>
                ))}
            </Stack>
            <Paper
                sx={(theme) => ({
                    borderRadius: 3,
                    flexGrow: 1,
                    minHeight: 0,
                    display: 'flex',
                    flexDirection: 'column',
                    overflow: 'visible',
                    border: `1px solid ${theme.palette.divider}`,
                })}
            >
                {isMobileView ? (
                    <Stack spacing={1} sx={{p: 1}}>
                        {isLoading
                            ? Array.from({length: 3}).map((_, index) => (
                                  <Paper
                                      key={index}
                                      elevation={0}
                                      sx={{
                                          p: 2,
                                          borderRadius: 2,
                                          border: `1px solid ${theme.palette.divider}`,
                                          backgroundColor:
                                              theme.palette.mode === 'light'
                                                  ? 'rgba(255,255,255,0.8)'
                                                  : 'rgba(15,23,42,0.8)',
                                      }}
                                  >
                                      <Skeleton height={32}/>
                                  </Paper>
                              ))
                            : sortedMeetings.map((meeting) => (
                                  <Paper
                                      key={meeting.id}
                                      elevation={0}
                                      sx={{
                                          p: 2,
                                          borderRadius: 2,
                                          border: `1px solid ${theme.palette.divider}`,
                                          backgroundColor:
                                              theme.palette.mode === 'light'
                                                  ? 'rgba(255,255,255,0.95)'
                                                  : 'rgba(15,23,42,0.85)',
                                      }}
                                  >
                                      <Stack spacing={0.75}>
                                          <Stack
                                              direction="row"
                                              alignItems="center"
                                              justifyContent="space-between"
                                              flexWrap="wrap"
                                          >
                                              <Typography fontWeight={600}>{meeting.title}</Typography>
                                              <Chip
                                                  size="small"
                                                  label={meeting.status}
                                                  color={getStatusColor(meeting.status)}
                                              />
                                          </Stack>
                                          <Stack
                                              direction="row"
                                              flexWrap="wrap"
                                              spacing={1}
                                              sx={{color: 'text.secondary'}}
                                          >
                                              <Typography variant="caption">
                                                  {formatDateTime(meeting.startedAt)}
                                              </Typography>
                                              <Typography variant="caption">
                                                  Draft tasks: {meeting.draftTaskCount}
                                              </Typography>
                                          </Stack>
                                          <Button
                                              fullWidth
                                              size="small"
                                              variant="contained"
                                              color="primary"
                                              endIcon={<OpenInNew fontSize="small"/>}
                                              onClick={() => navigate(`/meetings/${meeting.id}/tasks`)}
                                          >
                                              Open tasks
                                          </Button>
                                          <Stack
                                              direction="row"
                                              spacing={1}
                                              justifyContent="flex-end"
                                              flexWrap="wrap"
                                          >
                                              <IconButton
                                                  aria-label="Edit meeting"
                                                  color="inherit"
                                                  onClick={() => setEditingMeeting(meeting)}
                                                  size="small"
                                              >
                                                  <EditIcon fontSize="small"/>
                                              </IconButton>
                                              <IconButton
                                                  aria-label="Delete meeting"
                                                  color="inherit"
                                                  onClick={() => setConfirmTarget(meeting)}
                                                  size="small"
                                              >
                                                  <DeleteIcon fontSize="small"/>
                                              </IconButton>
                                          </Stack>
                                      </Stack>
                                  </Paper>
                              ))}
                        {!isLoading && sortedMeetings.length === 0 && (
                            <Typography variant="body2" sx={{p: 1}}>
                                No meetings yet.
                            </Typography>
                        )}
                    </Stack>
                ) : (
                    <TableContainer
                        sx={{
                            flexGrow: 1,
                            overflowY: 'auto',
                        }}
                    >
                        <Table size="small" stickyHeader>
                            <TableHead>
                                <TableRow>
                                    <TableCell>Title</TableCell>
                                    <TableCell>Started at</TableCell>
                                    <TableCell>Status</TableCell>
                                    <TableCell>Draft tasks</TableCell>
                                    <TableCell align="right">Actions</TableCell>
                                </TableRow>
                            </TableHead>
                            <TableBody>
                                {isLoading
                                    ? Array.from({length: 3}).map((_, index) => (
                                          <TableRow key={index}>
                                              <TableCell colSpan={5}>
                                                  <Skeleton height={32}/>
                                              </TableCell>
                                          </TableRow>
                                      ))
                                    : sortedMeetings.map((meeting) => (
                                          <TableRow key={meeting.id} hover>
                                              <TableCell>
                                                  <Typography fontWeight={500}>{meeting.title}</Typography>
                                              </TableCell>
                                              <TableCell>{formatDateTime(meeting.startedAt)}</TableCell>
                                              <TableCell>
                                                  <Chip
                                                      size="small"
                                                      label={meeting.status}
                                                      color={getStatusColor(meeting.status)}
                                                  />
                                              </TableCell>
                                              <TableCell>{meeting.draftTaskCount}</TableCell>
                                              <TableCell align="right">
                                                  <Stack direction="row" spacing={1} justifyContent="flex-end">
                                                      <Button
                                                          size="small"
                                                          variant="outlined"
                                                          endIcon={<OpenInNew fontSize="small"/>}
                                                          onClick={() => navigate(`/meetings/${meeting.id}/tasks`)}
                                                      >
                                                          Open tasks
                                                      </Button>
                                                      <IconButton
                                                          aria-label="Edit meeting"
                                                          color="inherit"
                                                          onClick={() => setEditingMeeting(meeting)}
                                                          size="small"
                                                      >
                                                          <EditIcon fontSize="small"/>
                                                      </IconButton>
                                                      <IconButton
                                                          aria-label="Delete meeting"
                                                          color="inherit"
                                                          onClick={() => setConfirmTarget(meeting)}
                                                          size="small"
                                                      >
                                                          <DeleteIcon fontSize="small"/>
                                                      </IconButton>
                                                  </Stack>
                                              </TableCell>
                                          </TableRow>
                                      ))}
                                {!isLoading && sortedMeetings.length === 0 && (
                                    <TableRow>
                                        <TableCell colSpan={5}>
                                            <Typography variant="body2">No meetings yet.</Typography>
                                        </TableCell>
                                    </TableRow>
                                )}
                            </TableBody>
                        </Table>
                    </TableContainer>
                )}
            </Paper>
            <ConfirmDialog
                open={Boolean(confirmTarget)}
                title="Delete meeting"
                description="This will remove the meeting and its draft tasks."
                onClose={() => setConfirmTarget(null)}
                onConfirm={handleDelete}
                loading={deleteMeeting.isPending}
            />
            <Dialog
                open={Boolean(editingMeeting)}
                onClose={() => setEditingMeeting(null)}
                fullWidth
                maxWidth="sm"
            >
                <DialogTitle>Edit meeting</DialogTitle>
                <DialogContent>
                    {editingMeeting && (
                        <EditMeetingForm
                            meeting={editingMeeting}
                            onSubmit={handleEditSubmit}
                            onCancel={() => setEditingMeeting(null)}
                            loading={updateMeeting.isPending}
                        />
                    )}
                </DialogContent>
            </Dialog>
        </Box>
    );
};

type EditMeetingFormProps = {
    meeting: Meeting;
    loading?: boolean;
    onSubmit: (values: MeetingUpdateValues) => void;
    onCancel: () => void;
};

const EditMeetingForm = ({
                             meeting,
                             loading,
                             onSubmit,
                             onCancel,
                         }: EditMeetingFormProps) => {
    const {data: projects = [], isLoading: projectsLoading, isError: projectsError} = useJiraProjects();
    const projectOptions = useMemo(
        () => {
            const options = projects.map((project) => ({
                value: project.key,
                label: `${project.name} (${project.key})`,
            }));
            if (meeting.projectKey && !options.some((option) => option.value === meeting.projectKey)) {
                options.unshift({
                    value: meeting.projectKey,
                    label: `${meeting.projectKey} (current)`,
                });
            }
            return options;
        },
        [projects, meeting.projectKey],
    );
    const {control, handleSubmit, formState, getValues, setValue} = useForm<MeetingUpdateValues>({
        resolver: zodResolver(MeetingUpdateSchema),
        mode: 'onChange',
        defaultValues: {
            title: meeting.title,
            startedAt: toDateTimeInput(meeting.startedAt),
            projectKey: meeting.projectKey ?? '',
        },
    });
    useEffect(() => {
        const current = getValues('projectKey');
        if (current) {
            return;
        }
        const fallback = projectOptions[0]?.value || meeting.projectKey || '';
        if (fallback) {
            setValue('projectKey', fallback, {shouldValidate: true});
        }
    }, [projectOptions, meeting.projectKey, setValue, getValues]);

    return (
        <Stack
            spacing={3}
            mt={1}
            component="form"
            onSubmit={handleSubmit((values) => onSubmit(values))}
        >
            <Controller
                name="title"
                control={control}
                render={({field, fieldState}) => (
                    <TextField
                        {...field}
                        label="Title"
                        error={Boolean(fieldState.error)}
                        helperText={fieldState.error?.message}
                    />
                )}
            />
            <Controller
                name="projectKey"
                control={control}
                render={({field, fieldState}) => (
                    <TextField
                        {...field}
                        select
                        label="Jira project"
                        required
                        disabled={projectsLoading || projectOptions.length === 0}
                        error={Boolean(fieldState.error) || projectsError}
                        helperText={
                            fieldState.error?.message ||
                            (projectsError ? 'Failed to load Jira projects' : undefined)
                        }
                    >
                        {projectOptions.map((option) => (
                            <MenuItem key={option.value} value={option.value}>
                                {option.label}
                            </MenuItem>
                        ))}
                    </TextField>
                )}
            />
            <Controller
                name="startedAt"
                control={control}
                render={({field, fieldState}) => (
                    <TextField
                        {...field}
                        type="datetime-local"
                        label="Date & time"
                        InputLabelProps={{shrink: true}}
                        error={Boolean(fieldState.error)}
                        helperText={fieldState.error?.message}
                    />
                )}
            />
            <Stack direction="row" justifyContent="flex-end" spacing={2}>
                <Button onClick={onCancel} variant="text">
                    Cancel
                </Button>
                <Button type="submit" disabled={!formState.isValid || loading}>
                    Save
                </Button>
            </Stack>
        </Stack>
    );
};
