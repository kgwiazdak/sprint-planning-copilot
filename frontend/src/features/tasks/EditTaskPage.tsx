import { Alert, Box, Button, CircularProgress, Paper, Stack } from '@mui/material';
import { useNavigate, useParams } from 'react-router-dom';
import { useTask } from '../../api/hooks';
import { EditTaskForm } from './EditTaskForm';
import { PageHeader } from '../../components/PageHeader';

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
    <Box>
      <PageHeader
        eyebrow="Task editor"
        title="Edit task"
        subtitle={data.summary}
        actions={
          <Button variant="text" onClick={() => navigate(-1)}>
            Back
          </Button>
        }
      />
      <Paper sx={{ p: 4, maxWidth: 760 }}>
        <EditTaskForm
          task={data}
          onSuccess={() => navigate(-1)}
          onCancel={() => navigate(-1)}
        />
      </Paper>
    </Box>
  );
};
