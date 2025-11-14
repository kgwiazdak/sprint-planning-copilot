import { useMemo, useState } from 'react';
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
import type { Meeting } from '../../types';
import { formatDateTime, toDateTimeInput } from '../../utils/format';

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

  const sortedMeetings = useMemo(
    () =>
      [...meetings].sort(
        (a, b) => new Date(b.startedAt).getTime() - new Date(a.startedAt).getTime(),
      ),
    [meetings],
  );

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
    <Box>
      <Stack direction="row" justifyContent="space-between" mb={3}>
        <div>
          <Typography variant="h5" fontWeight={600}>
            Meetings
          </Typography>
          <Typography variant="body2" color="text.secondary">
            Track ingestion status and draft counts
          </Typography>
        </div>
        <Button
          variant="contained"
          onClick={() => navigate('/meetings/new')}
        >
          New meeting
        </Button>
      </Stack>
      <Paper>
        <Table>
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
                        color={meeting.status === 'processed' ? 'success' : 'default'}
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
                          onClick={() => setEditingMeeting(meeting)}
                        >
                          <EditIcon />
                        </IconButton>
                        <IconButton
                          aria-label="Delete meeting"
                          onClick={() => setConfirmTarget(meeting)}
                        >
                          <DeleteIcon />
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
