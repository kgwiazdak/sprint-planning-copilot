import { Paper, Typography } from '@mui/material';
import { useNavigate } from 'react-router-dom';
import { useSnackbar } from 'notistack';
import { MeetingForm } from './MeetingForm';
import { useCreateMeeting } from '../../api/hooks';
import type { MeetingFormValues } from '../../schemas/meeting';

export const NewMeetingForm = () => {
  const createMeeting = useCreateMeeting();
  const { enqueueSnackbar } = useSnackbar();
  const navigate = useNavigate();

  const handleSubmit = async (values: MeetingFormValues) => {
    try {
      await createMeeting.mutateAsync({
        ...values,
        startedAt: new Date(values.startedAt).toISOString(),
      });
      enqueueSnackbar('Meeting created', { variant: 'success' });
      navigate('/meetings');
    } catch (error) {
      enqueueSnackbar((error as Error).message, { variant: 'error' });
    }
  };

  return (
    <Paper sx={{ p: 4, maxWidth: 640 }}>
      <Typography variant="h5" mb={2}>
        New Meeting
      </Typography>
      <MeetingForm
        onSubmit={handleSubmit}
        loading={createMeeting.isPending}
        submitLabel="Create meeting"
        onCancel={() => navigate(-1)}
      />
    </Paper>
  );
};
