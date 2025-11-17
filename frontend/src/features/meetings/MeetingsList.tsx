import { useEffect, useMemo, useState } from 'react';
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
} from '@mui/material';
import DeleteIcon from '@mui/icons-material/DeleteOutline';
import EditIcon from '@mui/icons-material/EditOutlined';
import { OpenInNew } from '@mui/icons-material';
import { useNavigate } from 'react-router-dom';
import { Controller, useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { useSnackbar } from 'notistack';
import {
  useDeleteMeeting,
  useMeetings,
  useUpdateMeeting,
} from '../../api/hooks';
import { ConfirmDialog } from '../../components/ConfirmDialog';
import { MeetingUpdateSchema } from '../../schemas/meeting';
import type { MeetingUpdateValues } from '../../schemas/meeting';
import type { Meeting, MeetingStatus } from '../../types';
import { formatDateTime, toDateTimeInput } from '../../utils/format';
import { PageHeader } from '../../components/PageHeader';

const MEETING_TABLE_HEADER_HEIGHT = 60;
const MEETING_ROW_HEIGHT = 88;
const MAX_VISIBLE_MEETINGS = 3;
const MEETINGS_TABLE_MAX_HEIGHT =
  MEETING_TABLE_HEADER_HEIGHT + MAX_VISIBLE_MEETINGS * MEETING_ROW_HEIGHT;

export const MeetingsList = () => {
  const navigate = useNavigate();
  const { data: meetings = [], isLoading, isError, refetch } = useMeetings();
  const deleteMeeting = useDeleteMeeting();
  const updateMeeting = useUpdateMeeting();
  const { enqueueSnackbar } = useSnackbar();
  const [confirmTarget, setConfirmTarget] = useState<Meeting | null>(null);
  const [editingMeeting, setEditingMeeting] = useState<Meeting | null>(null);

  const handleDelete = async () => {
    if (!confirmTarget) return;
    try {
      await deleteMeeting.mutateAsync(confirmTarget.id);
      enqueueSnackbar('Meeting deleted', { variant: 'success' });
      setConfirmTarget(null);
    } catch (error) {
      enqueueSnackbar((error as Error).message, { variant: 'error' });
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
        },
      });
      enqueueSnackbar('Meeting updated', { variant: 'success' });
      setEditingMeeting(null);
    } catch (error) {
      enqueueSnackbar((error as Error).message, { variant: 'error' });
    }
  };

  useEffect(() => {
    const hasInFlight = meetings.some((meeting) =>
      ['queued', 'processing'].includes(meeting.status),
    );
    if (!hasInFlight) {
      return;
    }
    const interval = window.setInterval(() => {
      refetch();
    }, 5000);
    return () => window.clearInterval(interval);
  }, [meetings, refetch]);

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
    return { active, done, failed, draftTasks, lastRun };
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
        direction={{ xs: 'column', md: 'row' }}
        spacing={2}
        flexWrap="wrap"
        mb={3}
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
              p: 2.5,
              borderRadius: 3,
              flex: { xs: '1 1 100%', md: '1 1 25%' },
            }}
          >
            <Typography variant="overline" color="text.secondary">
              {stat.label}
            </Typography>
            <Typography variant="h4" fontWeight={700} sx={{ mt: 1 }}>
              {stat.value}
            </Typography>
            <Typography variant="body2" color="text.secondary">
              {stat.helper}
            </Typography>
          </Paper>
        ))}
      </Stack>
      <Paper
        sx={{
          borderRadius: 3,
          flexGrow: 1,
          minHeight: 0,
          display: 'flex',
          flexDirection: 'column',
          overflow: 'hidden',
        }}
      >
        <TableContainer
          sx={{
            flexGrow: 1,
            maxHeight: MEETINGS_TABLE_MAX_HEIGHT,
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
                ? Array.from({ length: 3 }).map((_, index) => (
                    <TableRow key={index}>
                      <TableCell colSpan={5}>
                        <Skeleton height={32} />
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
                            endIcon={<OpenInNew fontSize="small" />}
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
                            <EditIcon fontSize="small" />
                          </IconButton>
                          <IconButton
                            aria-label="Delete meeting"
                            color="inherit"
                            onClick={() => setConfirmTarget(meeting)}
                            size="small"
                          >
                            <DeleteIcon fontSize="small" />
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
  const { control, handleSubmit, formState } = useForm<MeetingUpdateValues>({
    resolver: zodResolver(MeetingUpdateSchema),
    mode: 'onChange',
    defaultValues: {
      title: meeting.title,
      startedAt: toDateTimeInput(meeting.startedAt),
    },
  });

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
        render={({ field, fieldState }) => (
          <TextField
            {...field}
            label="Title"
            error={Boolean(fieldState.error)}
            helperText={fieldState.error?.message}
          />
        )}
      />
      <Controller
        name="startedAt"
        control={control}
        render={({ field, fieldState }) => (
          <TextField
            {...field}
            type="datetime-local"
            label="Date & time"
            InputLabelProps={{ shrink: true }}
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
