import { Alert, Button, CircularProgress, Paper, Stack, Typography } from '@mui/material';
import { useNavigate, useParams } from 'react-router-dom';
import { useTask } from '../../api/hooks';
import { EditTaskForm } from './EditTaskForm';

export const EditTaskPage = () => {
  const { id = '' } = useParams();
  const { data, isLoading, isError, refetch } = useTask(id);
  const navigate = useNavigate();

  if (isLoading) {
    return (
      <Stack alignItems="center" py={4}>
        <CircularProgress />
      </Stack>
    );
  }

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
        Failed to load task.
      </Alert>
    );
  }

  if (!data) {
    return <Alert severity="warning">Task not found.</Alert>;
  }

  return (
    <Paper sx={{ p: 4, maxWidth: 720 }}>
      <Typography variant="h5" mb={2}>
        Edit task
      </Typography>
      <EditTaskForm
        task={data}
        onSuccess={() => navigate(-1)}
        onCancel={() => navigate(-1)}
      />
    </Paper>
  );
};
