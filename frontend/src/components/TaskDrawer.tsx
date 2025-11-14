import {
  Box,
  CircularProgress,
  Drawer,
  IconButton,
  Stack,
  Typography,
} from '@mui/material';
import CloseIcon from '@mui/icons-material/Close';
import { useTask } from '../api/hooks';
import { EditTaskForm } from '../features/tasks/EditTaskForm';

type TaskDrawerProps = {
  taskId: string | null;
  open: boolean;
  onClose: () => void;
};

export const TaskDrawer = ({ taskId, open, onClose }: TaskDrawerProps) => {
  const { data, isLoading } = useTask(taskId ?? '');

  return (
    <Drawer anchor="right" open={open} onClose={onClose}>
      <Box width={{ xs: 360, sm: 420, md: 480 }} p={3} role="dialog">
        <Stack
          direction="row"
          alignItems="center"
          justifyContent="space-between"
          mb={2}
        >
          <Typography variant="h6">Edit Task</Typography>
          <IconButton aria-label="Close detail" onClick={onClose}>
            <CloseIcon />
          </IconButton>
        </Stack>
        {isLoading && (
          <Stack alignItems="center" py={4}>
            <CircularProgress size={32} />
          </Stack>
        )}
        {!isLoading && data && (
          <EditTaskForm task={data} onSuccess={onClose} dense />
        )}
      </Box>
    </Drawer>
  );
};
